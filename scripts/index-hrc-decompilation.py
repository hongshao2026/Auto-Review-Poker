"""Keep every decompiled ZIP member in a case-safe, ordinal-scoped directory."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
JAR = Path(r'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar')
OUT = ROOT / 'analysis/hrc-deep'

with zipfile.ZipFile(JAR) as jar, zipfile.ZipFile(OUT / 'main-decompiled.zip') as archive:
    originals = {i.filename: (ordinal, hashlib.sha256(jar.read(i)).hexdigest())
                 for ordinal, i in enumerate(jar.infolist()) if i.filename.endswith('.class')}
    rows = []
    for ordinal, info in enumerate(archive.infolist()):
        if not info.filename.endswith('.java'):
            continue
        member = info.filename[:-5] + '.class'
        original = originals.get(member)
        tag = f'{original[0]:04d}' if original else f'extra-{ordinal:04d}'
        destination = OUT / 'sources' / tag / Path(info.filename).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = archive.read(info)
        destination.write_bytes(data)
        rows.append({'class': member[:-6], 'jar_member': member,
                     'jar_ordinal': original[0] if original else None,
                     'class_sha256': original[1] if original else None,
                     'source': str(destination.relative_to(ROOT)),
                     'source_sha256': hashlib.sha256(data).hexdigest(),
                     'decompiler_error': 'couldn\'t be decompiled' in data.decode('utf-8', errors='replace').lower()})
    summary = {'jar': str(JAR), 'jar_sha256': hashlib.sha256(JAR.read_bytes()).hexdigest(),
               'original_classes': len(originals), 'source_files': len(rows),
               'error_marked_sources': sum(r['decompiler_error'] for r in rows),
               'sources': rows}
    (OUT / 'source-index.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k != 'sources'}, indent=2))
