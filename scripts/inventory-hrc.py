"""Read-only installation metadata; does not execute or decompile HRC."""
import collections
import hashlib
import json
import struct
import zipfile
from pathlib import Path

workspace = Path(__file__).resolve().parents[1]
target = Path(r"D:\Program Files\HRC")
main_jars = sorted((target / "plugins").glob("net.holdemresources.calculator_*.jar"))
assert main_jars, "HRC main JAR not found"

def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

files = [target / "hrc.exe", target / "hrc.ini", *main_jars]
packages = []
for jar in main_jars:
    with zipfile.ZipFile(jar) as archive:
        names = archive.namelist()
        classes = [name for name in names if name.endswith(".class")]
        versions = collections.Counter()
        for name in classes:
            with archive.open(name) as stream:
                header = stream.read(8)
            if header[:4] == b"\xca\xfe\xba\xbe":
                versions[str(struct.unpack(">H", header[6:8])[0])] += 1
        packages.append(dict(path=str(jar),class_count=len(classes),class_major_versions=dict(versions),manifest=archive.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")))
report = dict(target=str(target),mode="read-only metadata; no target execution or decompilation",files=[dict(path=str(p),size=p.stat().st_size,sha256=sha256(p)) for p in files],packages=packages,native_libraries=[str(p) for p in target.rglob("*.dll")])
(workspace / "reports/hrc-installation-inventory.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps(dict(target=str(target),main_jar_count=len(main_jars),class_count=sum(p["class_count"] for p in packages),class_versions=[p["class_major_versions"] for p in packages]),ensure_ascii=False))
