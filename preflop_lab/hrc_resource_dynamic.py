"""Local installed-profile compression for fixed-board subtrees.

The original qa positive-bucket branch chooses a >16000-bucket resource, then
compresses reachable IDs over the whole fixed-flop domain. Raw tables stay in
the user's local research cache and must not be bundled as product assets.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import time
import zipfile

import numpy as np

from .hrc_abstraction import (
    BOARD_DIGESTS, HOLE_COLUMNS, ROW_COUNTS, canonical_board,
    canonical_boards, file_sha256,
)
from .hrc_dynamic import (
    COMBOS, COMBO_ARRAY, DynamicAbstraction, DynamicResourceLimit,
    _runouts, validate_history,
)

RESOURCE_IDS = {
    2: '741bd150aec01478de0204b90775758d730248df0458d8d4a3a534bc90deb8a7',
    3: '40624adecddaa224acf4cf2cf59e1e6f5e92d2080099d2465beac417cb6393a4',
}
PROFILE_BUCKETS = 16384
RESOURCE_JAR_SHA256 = '731b654ead51b5b49c91accee59f1a8bfe9471f4597d3104213cc7c8b27582ec'
DECODER_SHA256 = '615c0c3efef990d77831104475fba6a1f7971388691d4bad1471ad84101f6d52'
LOW = np.asarray([(mask & -mask).bit_length()-1 for mask in COMBOS])
HIGH = np.asarray([mask.bit_length()-1 for mask in COMBOS])


def prepare_profile_resources(plugins, output, *, board_cache=None, jdk=None):
    """Decode only the pinned16k turn/river tables; no HRC class execution."""
    plugins, output = Path(plugins), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    jar = plugins/'net.holdemresources.postflopabstractions.holdem_1.0.0.jar'
    decoder = plugins/'net.holdemresources.calculator.mavendependencies_0.2.0/org.brotli/dec-0.1.2.jar'
    if file_sha256(jar) != RESOURCE_JAR_SHA256 or file_sha256(decoder) != DECODER_SHA256:
        raise ValueError('Installed resource or generic decoder identity differs from reviewed version')
    root = Path(__file__).resolve().parents[1]
    jdk = Path(jdk or r'D:\Tools\REA-Research\jdk-21.0.13+9\bin')
    helper = output/'decoder-helper'
    helper.mkdir(exist_ok=True)
    manifest = dict(schema='local-hrc-subtree-resource-v1',data_origin='User-installed proprietary profile; local research only',
                    resource_jar=str(jar),resource_jar_sha256=RESOURCE_JAR_SHA256,decoder_sha256=DECODER_SHA256,profiles=[])
    compiled = False
    with zipfile.ZipFile(jar) as archive:
        for street,digest in RESOURCE_IDS.items():
            expected = ROW_COUNTS[street]*HOLE_COLUMNS[street]*2
            path = output/f'street{street}.buckets.u16'
            member = f'abstractions/Johanson13_2021-02/Johanson13_2021-02.16384.{street}.{digest}.dat.br'
            if not path.exists() or path.stat().st_size!=expected or file_sha256(path)!=digest:
                if not compiled:
                    subprocess.run([str(jdk/'javac.exe'),'-cp',str(decoder),'-d',str(helper),str(root/'scripts/java/BrotliResourceBytes.java')],check=True,capture_output=True)
                    compiled=True
                pending=path.with_suffix('.pending')
                with pending.open('wb') as stream:
                    run=subprocess.run([str(jdk/'java.exe'),'-Xmx512m','-cp',str(helper)+';'+str(decoder),'BrotliResourceBytes',str(jar),member],stdout=stream,stderr=subprocess.PIPE)
                if run.returncode:raise RuntimeError(run.stderr.decode(errors='replace'))
                if pending.stat().st_size!=expected or file_sha256(pending)!=digest:
                    raise ValueError('Decoded subtree abstraction size/hash mismatch')
                pending.replace(path)
            board_path=output/f'street{street}.boards.u64'
            if not board_path.exists() or file_sha256(board_path)!=BOARD_DIGESTS[street]:
                candidate=Path(board_cache)/board_path.name if board_cache is not None else None
                if candidate is not None and candidate.exists() and file_sha256(candidate)==BOARD_DIGESTS[street]:
                    shutil.copyfile(candidate,board_path)
                else:
                    np.asarray(canonical_boards(street),dtype='<u8').tofile(board_path)
                if file_sha256(board_path)!=BOARD_DIGESTS[street]:raise ValueError('Canonical board index mismatch')
            values=np.memmap(path,dtype='<u2',mode='r')
            if int(values.max())>=PROFILE_BUCKETS:raise ValueError('Resource bucket outside16384profile')
            manifest['profiles'].append(dict(street=street,buckets=PROFILE_BUCKETS,id=digest,
                member=member,compressed_sha256=hashlib.sha256(archive.read(member)).hexdigest(),
                values_file=path.name,values_bytes=expected,values_sha256=digest,
                boards_file=board_path.name,boards_sha256=BOARD_DIGESTS[street]))
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


class ProfileTable:
    def __init__(self, directory, street):
        if type(street) is not int or street not in RESOURCE_IDS:
            raise ValueError('Resource subtree abstraction supports turn/river only')
        directory=Path(directory)
        values=directory/f'street{street}.buckets.u16';boards=directory/f'street{street}.boards.u64'
        if file_sha256(values)!=RESOURCE_IDS[street] or file_sha256(boards)!=BOARD_DIGESTS[street]:
            raise ValueError('Local subtree profile identity mismatch')
        self.street=street
        self.rows=np.fromfile(boards,dtype='<u8')
        self.lookup={int(mask):i for i,mask in enumerate(self.rows)}
        self.values=np.memmap(values,mode='r',dtype='<u2',shape=(ROW_COUNTS[street],HOLE_COLUMNS[street]))

    def row(self, board):
        if type(board) is not int or board<0 or board>>52 or board.bit_count()!=self.street+2:
            raise ValueError('Invalid resource board')
        canonical,mapping=canonical_board(board)
        legal=(COMBO_ARRAY & np.uint64(board))==0
        cards=np.asarray([card-card%4+mapping[card%4] for card in range(52)])
        low=np.minimum(cards[LOW],cards[HIGH]);high=np.maximum(cards[LOW],cards[HIGH])
        reduced=np.asarray([card-(canonical&((1<<card)-1)).bit_count() for card in range(52)])
        a=reduced[low[legal]];b=reduced[high[legal]]
        columns=b*(b-1)//2+a
        result=np.full(1326,-1,dtype='<i4')
        result[legal]=self.values[self.lookup[canonical],columns]
        return result


def prepare_resource(prefix, street, ranges, table, *, max_seconds=120,
                     max_map_bytes=1<<30, cancel_check=None):
    """Compress over all fixed-flop runouts, including when turn/river known.

    Returns the same HRDYN001-capable object as the algorithmic mapper. Its
    prefix is intentionally only [0,flop], matching qa/oo resource branches.
    """
    history=validate_history(prefix)
    if type(street) is not int or street not in RESOURCE_IDS or table.street!=street:
        raise ValueError('Invalid subtree resource street/table')
    if not isinstance(ranges,(list,tuple)) or not 1<=len(ranges)<=10:
        raise ValueError('Expected1..10 player ranges')
    if not math.isfinite(max_seconds) or max_seconds<=0 or type(max_map_bytes) is not int or max_map_bytes<=0:
        raise ValueError('Invalid resource mapping budget')
    prefix=history[:2];supports=[]
    for row in ranges:
        if row is None:supports.append(None);continue
        weights=np.asarray(row,dtype=float)
        if weights.shape!=(1326,) or not np.isfinite(weights).all() or np.any(weights<0):
            raise ValueError('Expected1326 finite nonnegative weights')
        supports.append(weights>0)
    distinct={s.tobytes():s for s in supports if s is not None}
    rows=52**(street-1)
    if rows*1326*4*len(distinct)>max_map_bytes:raise DynamicResourceLimit('Resource map memory budget exceeded')
    started=time.monotonic()
    def check():
        if cancel_check and cancel_check():raise DynamicResourceLimit('Resource mapping cancelled')
        if time.monotonic()-started>max_seconds:raise DynamicResourceLimit('Resource mapping time budget exhausted')
    base=np.full((rows,1326),-1,dtype='<i4')
    for index,board in _runouts(prefix,street):
        check();base[index]=table.row(board[-1])
    legal=base>=0;built={}
    for identity,support in distinct.items():
        check();reachable=np.unique(base[legal & support[None,:]])
        compress=np.full(PROFILE_BUCKETS,-1,dtype='<i4');compress[reachable]=np.arange(len(reachable),dtype='<i4')
        mapping=np.full(base.shape,-1,dtype='<i4');mapping[legal]=compress[base[legal]]
        built[identity]=(len(reachable),mapping)
    return DynamicAbstraction(prefix,street,'resource',
        [0 if s is None else built[s.tobytes()][0] for s in supports],
        [None if s is None else built[s.tobytes()][1] for s in supports])
