"""HRC ZIP interchange, with a checked optional native continuation extension."""
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import tempfile
import uuid
import zipfile

from .hrc_benchmarks import CACHE

MAX_ARCHIVE = 1 << 30
CORE = ('settings.json', 'state.json', 'gametree.dat', 'nodedata.dat', 'idx.dat')
SOURCE_ROOT = CACHE / 'hrcz-sources'


def _json(data):
    def invalid(value):
        raise ValueError('JSON contains non-finite value: '+value)
    return json.loads(data, parse_constant=invalid)


def _checked_zip(path):
    if not 0 < Path(path).stat().st_size <= MAX_ARCHIVE:
        raise ValueError('存档为空或超过 1 GiB。')
    archive = zipfile.ZipFile(path)
    info = archive.infolist()
    names = [i.filename for i in info]
    if (len(names) != len(set(names)) or sum(i.file_size for i in info) > MAX_ARCHIVE
        or any(i.flag_bits & 1 or i.filename.startswith(('/', '\\')) or '\\' in i.filename
               or ':' in i.filename or '..' in i.filename.split('/') for i in info)):
        archive.close()
        raise ValueError('ZIP 含重复项、加密项、不安全路径或过大内容。')
    return archive


def cache_source(path):
    path = Path(path)
    with _checked_zip(path) as archive:
        if not set(CORE[:4]) <= set(archive.namelist()):
            raise ValueError('缺少 HRC 设置、结果、树或策略文件。')
    with path.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
    target = SOURCE_ROOT / f'{sha}.hrcz'
    if not target.exists():
        pending = SOURCE_ROOT / f'{sha}.{uuid.uuid4().hex}.part'
        shutil.copyfile(path, pending)
        pending.replace(target)
    return sha


class SourceArchive:
    def __init__(self, path, sha256=None):
        from .hrc_research import decoder
        from .hrc_hrcz_tree import replay_archive_tree
        from .hrc_hrcz_storage import decode_nodedata
        self.path = Path(path)
        with self.path.open('rb') as stream:
            self.sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
        if sha256 is not None and sha256 != self.sha256:
            raise ValueError('原始 HRC 存档 SHA-256 不匹配。')
        with _checked_zip(path) as archive:
            self.members = {name: archive.read(name) for name in CORE if name in archive.namelist()}
        if not set(CORE[:4]) <= self.members.keys():
            raise ValueError('缺少 HRC 核心文件。')
        if any(len(self.members[name]) > 4*1024*1024 for name in CORE[:2]):
            raise ValueError('HRC 设置或状态过大。')
        self.settings, self.state = _json(self.members['settings.json']), _json(self.members['state.json'])
        d = decoder()
        self.nodes, tree_offsets = d.parse_tree(self.members['gametree.dat'])
        self.decoder_records, data_offsets = d.parse_node_records(self.members['nodedata.dat'], self.nodes)
        if 'idx.dat' in self.members:
            d.verify_index(self.members['idx.dat'], tree_offsets, data_offsets)
        self.records, _ = decode_nodedata(self.members['nodedata.dat'], {i:len(n['child_ids']) for i,n in self.nodes.items()}, allow_missing=True)
        self.tree = replay_archive_tree(self.settings, self.members['gametree.dat'], state=self.state,
            provenance={'source_sha256':self.sha256,'format':'hrcz','original_strategy_is_imported':True})


@lru_cache(maxsize=3)
def load_source(sha256):
    if not isinstance(sha256, str) or not re.fullmatch('[0-9a-f]{64}', sha256):
        raise ValueError('无效 HRC 来源 ID。')
    return SourceArchive(SOURCE_ROOT / f'{sha256}.hrcz', sha256)


def encode_gametree(tree):
    output = bytearray(struct.pack('<i',len(tree.nodes)))
    offsets = {}
    for node_id in getattr(tree,'record_order',range(len(tree.nodes))):
        node = tree.nodes[node_id]
        start = len(output)
        if len(node.incoming_actions)>127 or len(node.children)>32767:
            raise ValueError('行动数量超过 HRC 保存格式。')
        output.extend(struct.pack('<iiBbh',node.id,node.parent_id,2 if node.terminal else 1,len(node.incoming_actions),len(node.children)))
        if not node.terminal:
            output.extend(struct.pack('<bb',node.street,node.actor))
        for a in node.incoming_actions:
            output.extend(struct.pack('<Q',a.kind | a.actor<<8 | int(a.allin)<<12 | a.street<<13 | a.amount<<16))
        for child in node.children:
            output.extend(struct.pack('<i',child))
        offsets[node.id]=(start,len(output)-start)
    return bytes(output),offsets


def _settings_config(solver):
    from .hrc_hrcz_settings import settings_to_config
    cfg = settings_to_config(solver.tree.settings)
    if solver.config['engine'] in ('hrc_custom','hrc_imported'):
        return deepcopy(solver.config)
    for key in ('utility','payouts','other_stacks','bounty','fgs','rake'):
        if key in solver.config:
            cfg[key] = deepcopy(solver.config[key])
    # Fixed tournament adapters express external stacks in BB; mapped scenes
    # use internal chip / 10000, as their local stacks do.
    if cfg.get('other_stacks'):
        cfg['other_stacks']=[v*solver.tree.rules.big_blind/10000 for v in cfg['other_stacks']]
    return cfg


def export_hrcz(job, include_resources=False, *, include_native=True):
    from .hrc_hrcz_settings import config_to_settings, config_to_state
    from .hrc_hrcz_storage import checkpoint_to_records, encode_nodedata
    solver = job.solver
    if job.result is None or job.status in ('running','cancelling'):
        raise ValueError('请先完成或停止计算后保存。')
    source = getattr(solver,'source',None)
    samples = (solver.index or {}).get('samples',0)
    if source is not None and samples==0:
        return source.path
    if solver.output is None:
        raise ValueError('没有可导出的原生策略检查点。')
    folder = Path(solver.output)
    from .hrc_training import solver_compact
    compact = solver_compact(solver)
    if not (folder/'tree.json').is_file():
        from .hrc_checkpoint import _identity
        with (folder/'checkpoint.bin').open('rb') as stream:
            header=stream.read(16)
        if len(header)!=16 or struct.unpack_from('<Q',header,8)[0] != _identity(compact):
            raise ValueError('旧检查点与当前场景身份不一致，不能生成 HRC 文件。')
        (folder/'tree.json').write_text(json.dumps(compact,sort_keys=True,separators=(',',':')),encoding='utf-8')
    cfg = _settings_config(solver)
    settings = config_to_settings(cfg)
    scale = solver.tree.rules.big_blind/100 if not getattr(solver,'equity_config',None) else 1.
    resources = Path(getattr(solver,'resource_dir',CACHE/'abstractions'))
    if source is not None:
        leaves = {i:r for i,r in source.records.items() if r['action_count']==0}
        baseline = list(source.state['eqpre'])
    else:
        from .hrc_hrcz_leaves import generate_leaves
        leaves,baseline,_ = generate_leaves(compact,resources,folder)
    records,report = checkpoint_to_records(folder,utility_scale=scale,utility_offsets=baseline,leaf_records=leaves)
    tree_bytes,tree_offsets = encode_gametree(solver.tree)
    data_bytes,data_offsets = encode_nodedata(records,len(solver.tree.nodes))
    index_bytes = b''.join(struct.pack('<qiqi',*tree_offsets[i],*data_offsets.get(i,(0,0))) for i in range(len(solver.tree.nodes)))
    mean = solver.index.get('root_mean_net_payout' if getattr(solver,'equity_config',None) else 'root_mean_net_bb')
    if not mean or not samples:
        raise ValueError('检查点没有真实根节点结果。')
    state = config_to_state(cfg,eqpre=baseline,eqpost=[b+x*scale for b,x in zip(baseline,mean)])
    payloads = dict(zip(CORE,(json.dumps(settings,ensure_ascii=False,allow_nan=False).encode(),json.dumps(state,ensure_ascii=False,allow_nan=False).encode(),tree_bytes,data_bytes,index_bytes)))
    target = folder/'calculation.hrcz'
    pending = target.with_suffix('.pending')
    extension = None
    if include_native:
        from .hrc_archive import export_archive
        extension = export_archive(job,include_resources)
    manifest = {'schema':'preflop-hrcz-extension-v1','core_sha256':{n:hashlib.sha256(v).hexdigest() for n,v in payloads.items()},'storage_conversion':report}
    if extension:
        with extension.open('rb') as stream:
            manifest['checkpoint_sha256']=hashlib.file_digest(stream,'sha256').hexdigest()
    with zipfile.ZipFile(pending,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
        for name,data in payloads.items():
            archive.writestr(name,data)
        if extension:
            archive.write(extension,'prefloplab/checkpoint.plabz')
            archive.writestr('prefloplab/native.json',json.dumps(manifest,allow_nan=False))
    pending.replace(target)
    return target


def import_hrcz(path, run_root):
    from .hrc_imported import HRCImportedSolver
    from .hrc_hrcz_settings import settings_to_config
    sha = cache_source(path)
    source = load_source(sha)
    # Only our untouched export may restore full native RNG/visit history.
    # A HRC re-save changes the core and therefore uses ordinary source import.
    with _checked_zip(path) as archive:
        if {'prefloplab/native.json','prefloplab/checkpoint.plabz'} <= set(archive.namelist()):
            if archive.getinfo('prefloplab/native.json').file_size>4*1024*1024:
                raise ValueError('原生扩展清单过大。')
            meta = _json(archive.read('prefloplab/native.json'))
            hashes = {n:hashlib.sha256(v).hexdigest() for n,v in source.members.items()}
            if meta.get('schema')=='preflop-hrcz-extension-v1' and meta.get('core_sha256')==hashes:
                with tempfile.TemporaryDirectory(prefix='hrcz-native-',dir=CACHE) as tmp:
                    embedded = Path(tmp)/'checkpoint.plabz'
                    with archive.open('prefloplab/checkpoint.plabz') as src,embedded.open('wb') as dst:
                        shutil.copyfileobj(src,dst,1024*1024)
                    with embedded.open('rb') as stream:
                        digest=hashlib.file_digest(stream,'sha256').hexdigest()
                    if digest==meta.get('checkpoint_sha256'):
                        from .hrc_archive import import_archive
                        return import_archive(embedded,run_root)
    cfg = settings_to_config(source.settings,source.state)
    cfg.update(engine='hrc_imported',source_sha256=sha)
    solver = HRCImportedSolver(cfg)
    if solver.training_supported:
        solver.initialize_checkpoint(CACHE/'runs'/uuid.uuid4().hex)
    result = solver.build_result()
    identity = uuid.uuid4().hex
    result.update(job_id=identity,created_at=datetime.now(timezone.utc).isoformat(),imported_archive=True)
    Path(run_root).mkdir(parents=True,exist_ok=True)
    (Path(run_root)/f'{identity}.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    return identity


def import_calculation(path,run_root):
    with _checked_zip(path) as archive:
        is_hrc = set(CORE[:4])<=set(archive.namelist())
    if is_hrc:
        return import_hrcz(path,run_root)
    from .hrc_archive import import_archive
    return import_archive(path,run_root)
