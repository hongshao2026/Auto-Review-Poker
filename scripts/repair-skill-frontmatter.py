"""Quote upstream REAP descriptions containing YAML mapping delimiters."""
import hashlib
import json
from pathlib import Path

workspace = Path(__file__).resolve().parents[1]
skills_root = Path.home() / ".codex/skills"
records = []
for name in (
    "reap-00-install-and-verify", "reap-01-getting-started",
    "reap-02-feature-tracing-any-program", "reap-03-native-binary-exploration",
    "reap-10-vulnerability-research", "reap-15-version-comparison-and-crash-work",
    "reap-16-long-running-investigations", "reap-prompt-writing-tips",
):
    source = workspace / "external/REA-Prompts/Skills" / name / "SKILL.md"
    target = skills_root / name / "SKILL.md"
    original = source.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith("description: "):
            lines[index] = "description: " + json.dumps(line[len("description: "):].strip(), ensure_ascii=False) + "\n"
            break
    repaired = "".join(lines)
    target.write_text(repaired, encoding="utf-8")
    records.append(dict(name=name, path=str(target), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), installed_sha256=hashlib.sha256(target.read_bytes()).hexdigest(), change="Quoted description to fix invalid upstream YAML; prompt body unchanged."))
(workspace / "reports/installed-skills.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
print(f"Repaired frontmatter for {len(records)} installed skills.")
