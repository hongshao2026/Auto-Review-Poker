"""Run the installed UI auditor with its JS lexer progress bug corrected.

The upstream next_regex_literal checks context relative to its search start,
while iter_html_tags checks context relative to the full document. A division
slash can consequently be rediscovered forever. Match both using full-document
context; retain all audit rules and findings. The installed skill is untouched.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path.home() / '.codex/plugins/cache/openai-curated-remote/frontend-design-premium/1.4.0/skills/frontend-design-premium/scripts/audit_project.py'
spec = importlib.util.spec_from_file_location('hrc_ui_auditor', SOURCE)
audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit
spec.loader.exec_module(audit)


def next_regex_literal(text, start, limit):
    offset = text.find('/', start, limit)
    while offset >= 0:
        if not text.startswith('//', offset) and audit.is_regex_literal_start(text, offset):
            return offset
        offset = text.find('/', offset + 1, limit)
    return -1


audit.next_regex_literal = next_regex_literal
result = audit.audit_project(ROOT, 'strict')
report = result.to_dict()
report['auditor_compatibility'] = {
    'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    'fix': 'Use the same full-document regex context in both scanner branches to prevent an infinite loop on JavaScript division.',
    'rules_modified_or_suppressed': False,
}
path = ROOT / 'reports/hrc-workbench-audit.json'
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'exit_code': audit.exit_code(result), 'report': str(path), 'findings': report.get('findings', [])}, ensure_ascii=False))
raise SystemExit(audit.exit_code(result))
