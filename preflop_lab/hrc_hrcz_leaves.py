"""Independent absolute terminal payoffs for the HRC format1024 writer."""
from array import array
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import threading
import sys

ROOT = Path(__file__).resolve().parents[1]
_lock = threading.Lock()


def build():
    files = [ROOT/'native/hrc_hrcz_leaves.cpp', ROOT/'native/hrc_research_solver.cpp'] + sorted((ROOT/'native').glob('hrc_*.hpp'))
    digest = hashlib.sha256(b''.join(p.read_bytes() for p in files)).hexdigest()
    folder = ROOT/'analysis/hrc-native/hrcz-build'
    target = folder/f'hrc_leaves-{digest[:20]}.exe'
    with _lock:
        if target.is_file():
            return target
        folder.mkdir(parents=True, exist_ok=True)
        zig = Path(r'D:\Tools\REA-Research\zig-native\zig-x86_64-windows-0.15.2\zig.exe')
        command = [str(zig),'c++','-O3','-std=c++17','-ffp-contract=off',str(files[0]),'-o',str(target)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError('HRC 终局导出器编译失败：'+result.stderr[-5000:])
    return target


def _generate(compact, resources, output, *, baseline_only=False):
    from .hrc_native import prepare
    from .hrc_hrcz_storage import leaf_record
    output = Path(output)
    expected={n['id']:3**(sum(not f for f in compact['terminals'][n['terminal_id']]['folded'])-1)
              for n in compact['nodes'] if not n['children']}
    if not baseline_only and sum(expected.values())>2000000:
        raise ValueError('HRC leaf export vector budget exceeded')
    prepared = prepare(compact, output/'hrcz-leaf-input')
    path = output/('hrcz-baseline.bin' if baseline_only else 'hrcz-leaves.bin')
    masks = output/'hrcz-live-masks.bin'
    command=[str(build()),prepared['tree_binary'],str(resources),str(path)]
    if not baseline_only:
        masks.write_bytes(struct.pack('<I',len(compact['terminals']))+b''.join(struct.pack('<I',sum(1<<p for p,folded in enumerate(t['folded']) if not folded)) for t in compact['terminals']))
        command.append(str(masks))
    result = subprocess.run(command,
                            capture_output=True,text=True,timeout=180)
    if result.returncode:
        raise ValueError('HRC 终局向量导出失败：'+result.stderr[-4000:])
    records = {}
    with path.open('rb') as stream:
        if stream.read(8) != b'HRLEAF01':
            raise ValueError('Invalid terminal exporter output')
        players,count = struct.unpack('<II',stream.read(8))
        if players!=compact['players'] or count!=(0 if baseline_only else len(expected)):
            raise ValueError('Terminal exporter dimensions differ from input')
        baseline = list(struct.unpack(f'<{players}d',stream.read(8*players)))
        for _ in range(count):
            node,vectors = struct.unpack('<II',stream.read(8))
            if node in records or expected.get(node)!=vectors:
                raise ValueError('Unexpected/duplicate terminal export record')
            values = array('d');values.frombytes(stream.read(8*players*vectors))
            if sys.byteorder!='little': values.byteswap()
            if len(values) != players*vectors:
                raise ValueError('Truncated terminal export')
            records[node] = leaf_record(node,[values[i*players:(i+1)*players] for i in range(vectors)])
        if stream.read(1):
            raise ValueError('Trailing terminal output')
    return records,baseline,json.loads(result.stdout)


def generate_leaves(compact, resources, output):
    """Compute all absolute vectors; original terminal data is never an input."""
    return _generate(compact,resources,output)


def evaluate_baseline(compact, resources, output):
    """Return independent baseline in HRC archive units, without leaf enumeration.

    ChipEV uses internal chips / 100; monetary/FGS values use payout currency.
    Standard abstraction resources are not loaded. FGS requires its chance data.
    """
    return _generate(compact,resources,output,baseline_only=True)[1]
