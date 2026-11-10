"""Compile and decompile an original test class; never launch HRC."""
import json
import subprocess
from pathlib import Path

workspace = Path(__file__).resolve().parents[1]
out = workspace / "reports/smoke-test"
out.mkdir(parents=True, exist_ok=True)
root = Path(r"D:\Tools\REA-Research")
jdk = root / "jdk-21.0.13+9/bin"
source = out / "ResearchProbe.java"
source.write_text('''public record ResearchProbe(int value) {
    public int scaled(int multiplier) {
        if (multiplier < 0) throw new IllegalArgumentException("negative multiplier");
        return value * multiplier;
    }
}
''', encoding="utf-8")

def run(args, log):
    result = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
    (out / log).write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Command failed; inspect {out / log}")
    return result.stdout

run([jdk / "javac.exe", "-d", out, source], "javac.log")
bytecode = run([jdk / "javap.exe", "-c", "-p", out / "ResearchProbe.class"], "javap.log")
assert "imul" in bytecode
for name, jar, args in (
    ("vineflower", "vineflower-1.12.0.jar", [out / "ResearchProbe.class", out / "vineflower"]),
    ("cfr", "cfr-0.152.jar", [out / "ResearchProbe.class", "--outputdir", out / "cfr"]),
):
    (out / name).mkdir(exist_ok=True)
    run([jdk / "java.exe", "-jar", root / "java-decompilers" / jar, *args], name + ".log")
    recovered = (out / name / "ResearchProbe.java").read_text(encoding="utf-8")
    assert "scaled" in recovered and "negative multiplier" in recovered and "*" in recovered
    print(f"PASS: {name} decompiled Java 21 test record")
(workspace / "reports/java-verification.json").write_text(json.dumps(dict(javac=True,javap=True,vineflower=True,cfr=True,target="Original ResearchProbe test class; HRC was not executed."),indent=2),encoding="utf-8")
