"""Install pinned research tools from official release URLs, with digest checks."""
import concurrent.futures
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
ROOT = Path(r"D:\Tools\REA-Research")
DOWNLOADS = ROOT / "downloads"
DOWNLOADS.mkdir(parents=True, exist_ok=True)

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

assets = read_json(WORKSPACE / "downloads/tool-assets.json")
jdk = read_json(WORKSPACE / "downloads/temurin-release.json")["binary"]["package"]
assets.append(dict(key="jdk", url=jdk["link"], name=jdk["name"], sha256=jdk["checksum"]))
node = read_json(WORKSPACE / "downloads/node-release.json")["version"]
node_name = f"node-{node}-win-x64.zip"
sums = (WORKSPACE / "downloads/node-SHASUMS256.txt").read_text(encoding="utf-8-sig")
node_hash = next(line.split()[0] for line in sums.splitlines() if line.split()[-1] == node_name)
assets.append(dict(key="node", url=f"https://nodejs.org/dist/{node}/{node_name}", name=node_name, sha256=node_hash))

def digest(path, algorithm="sha256"):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()

def install(asset):
    destination = DOWNLOADS / asset["name"]
    algorithm = "sha256" if "sha256" in asset else "md5"
    if not destination.exists() or digest(destination, algorithm) != asset[algorithm]:
        print(f"Downloading {asset['name']}", flush=True)
        partial = destination.with_suffix(destination.suffix + ".part")
        subprocess.run([r"C:\Users\Shao\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\powershell\pwsh.exe", "-NoProfile", "-File", str(WORKSPACE / "scripts/Download-OfficialAsset.ps1"), "-Uri", asset["url"], "-Output", str(partial)], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if digest(partial, algorithm) != asset[algorithm]:
            raise RuntimeError(f"Checksum mismatch: {asset['name']}")
        partial.replace(destination)
    print(f"Verified {asset['name']}", flush=True)
    if destination.suffix == ".zip":
        with zipfile.ZipFile(destination) as archive:
            top = archive.namelist()[0].split("/")[0]
            for entry in archive.infolist():
                target = (ROOT / entry.filename).resolve()
                if not target.is_relative_to(ROOT.resolve()):
                    raise RuntimeError(f"Invalid archive path: {entry.filename}")
            archive.extractall(ROOT)
        installed = ROOT / top
    else:
        installed = ROOT / "java-decompilers" / asset["name"]
        installed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination, installed)
    result = dict(asset, installed_path=str(installed), sha256=digest(destination), verified_algorithm=algorithm)
    print(f"Installed {asset['key']}: {installed}", flush=True)
    return result

results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    jobs = {pool.submit(install, asset): asset for asset in assets}
    for completed in concurrent.futures.as_completed(jobs):
        results.append(completed.result())
        (WORKSPACE / "reports/portable-tools.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print("Portable tools ready.", flush=True)
