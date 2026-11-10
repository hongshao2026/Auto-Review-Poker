"""Generate the existing browser asset's preset data from the canonical JSON."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
asset = ROOT / 'web/hrc-hand-setup.js'
data = json.loads((ROOT / 'preflop_lab/data/preflop_presets.json').read_text(encoding='utf-8'))
begin, end = '// BEGIN GENERATED PREFLOP CATALOG', '// END GENERATED PREFLOP CATALOG'
block = begin + '\nwindow.HrcPreflopCatalog = ' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n' + end
text = asset.read_text(encoding='utf-8')
if begin in text:
    text = text[:text.index(begin)] + block + text[text.index(end) + len(end):]
else:
    text = text.replace('"use strict";', '"use strict";\n\n' + block, 1)
asset.write_text(text, encoding='utf-8')
print(json.dumps({'presets': len(data), 'asset': str(asset)}))
