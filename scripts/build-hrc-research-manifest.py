"""Seal local investigation outputs and check evidence links without rerunning analysis."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
DEEP=ROOT/'analysis/hrc-deep'
index=json.loads((DEEP/'source-index.json').read_text(encoding='utf-8'))
bytecode=[json.loads(line) for line in (DEEP/'bytecode-index.jsonl').read_text(encoding='utf-8').splitlines()]
counts=dict(Counter(r['kind'] for r in bytecode))
reports=[ROOT/f'reports/hrc-original-{name}-validation.json' for name in ('icm','cards','strategy','tree','settlement','traversal','abstraction','nested-traversal')]
validation=[]
for path in reports:
    data=json.loads(path.read_text(encoding='utf-8'))
    validation.append({'report':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'passed':data.get('passed') is True})
docs=[ROOT/'INVESTIGATION.md',*sorted((ROOT/'research').glob('HRC-*.md')),*sorted((ROOT/'analysis/hrc-desktop').glob('*.md'))]
links=[]
for doc in docs:
    for match in re.finditer(r'\]\((D:[^)]+)\)',doc.read_text(encoding='utf-8')):
        raw=match.group(1)
        location=re.fullmatch(r'(.+?)(?::(\d+))?',raw)
        path=Path(location[1]); line=int(location[2]) if location[2] else None
        exists=path.exists()
        in_range=exists and (line is None or 1<=line<=len(path.read_text(encoding='utf-8',errors='replace').splitlines()))
        links.append({'document':str(doc.relative_to(ROOT)),'target':raw,'valid':in_range})
files=set(DEEP.rglob('*'))
files.update(docs)
files.update(reports)
files.update((ROOT/'scripts/java').glob('*.java'))
files.update((ROOT/'scripts').glob('*hrc*.py'))
files.add(ROOT/'Run-HRC-Research-Checks.ps1')
files.add(ROOT/'Run-HRC-Desktop-Checks.ps1')
files.add(ROOT/'requirements-research-desktop.txt')
files.update((ROOT/'analysis/hrc-desktop').rglob('*'))
files.update((ROOT/'native').glob('*'))
files.update((ROOT/'preflop_lab').glob('hrc_*.py'))
files.update((ROOT/'tests').glob('test_hrc_*.py'))
files.update((ROOT/'scripts/native').glob('*'))
files.update((ROOT/'reports').glob('hrc-native-*.json'))
files.update((ROOT/'analysis/hrc-native').glob('*.json'))
files.update((ROOT/'analysis/hrc-native/eight15bb-seed44-diagnostic').rglob('*'))
files.add(ROOT/'reports/hrc-strategy-difference-audit.json')
files.add(ROOT/'analysis/hrc-native/build/build.json')
files.update(ROOT/name for name in ('APP-README.md','API-CONTRACT.md','DESIGN.md','PRODUCT.md','THIRD-PARTY.md','preflop_lab/server.py'))
files.update((ROOT/'web').glob('*'))
files.update((ROOT/'reports/ui').glob('hrc-native-*'))
files.update((ROOT/'reports/figures').glob('hrc-*bb*strategy-comparison.*'))
entries=[]
for path in sorted(p for p in files if p.is_file() and '__pycache__' not in p.parts):
    with path.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    entries.append({'path':str(path.relative_to(ROOT)),'bytes':path.stat().st_size,'sha256':digest})
rea=json.loads((DEEP/'rea-evidence.json').read_text(encoding='utf-8'))
manifest={'target':index['jar'],'target_sha256':index['jar_sha256'],'target_identity_unchanged':hashlib.sha256(Path(index['jar']).read_bytes()).hexdigest()==index['jar_sha256'],
          'bytecode_inventory':counts,'native_methods_in_main_jar':sum(bool(r.get('native')) for r in bytecode),
          'decompiler_error_methods':[{'class':r['class'],'source':r['source']} for r in index['sources'] if r['decompiler_error']],
          'validation':validation,'all_reviewed_checks_passed':all(r['passed'] for r in validation),'local_document_links':len(links),'invalid_links':[r for r in links if not r['valid']],
          'files':entries,'status':'partial behavioral reconstruction; no claim of whole-HRC equivalence',
          'limitations':['ASM calls are declared targets, not resolved dynamic dispatch; ordinals are not bytecode offsets.',
                         'All 986 source artifacts and javap outputs are inventoried; not all 5847 method semantics are recovered.',
                         'The traversal fixture has synthetic terminal payoffs and scripted RNG.',
                         'The desktop HU comparison uses an independent optimizer with installed HRC showdown probabilities; it is not a full independent equity-table regeneration.',
                         'Desktop save roundtrips cover observed unlocked ChipEV formats23/25; fixed-tree nine-player training is measured separately; full independent tree/abstraction generation and whole-product equivalence remain unproven.',
                         'Exhaustive abstraction mapping verification covers one installed 64-bucket flop profile.',
                         'Classloader allowlists restrict dependencies; they are not operating-system sandboxes.']}
output=ROOT/'reports/hrc-research-manifest.json'
output.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:manifest[k] for k in ('target_identity_unchanged','bytecode_inventory','native_methods_in_main_jar','all_reviewed_checks_passed','local_document_links','invalid_links')},ensure_ascii=False,indent=2))
print(f'Sealed {len(entries)} local evidence files.')
if not manifest['target_identity_unchanged'] or not manifest['all_reviewed_checks_passed'] or manifest['invalid_links']: raise SystemExit(1)
