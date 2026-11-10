$ErrorActionPreference = 'Stop'
$desktopRoot = $PSScriptRoot
$desktopPython = Join-Path $desktopRoot '.venv/Scripts/python.exe'
$desktopData = Join-Path $desktopRoot 'analysis/hrc-desktop'
$desktopChecks = Join-Path $desktopData 'rechecks'
New-Item -ItemType Directory -Path $desktopChecks -Force | Out-Null
Push-Location -LiteralPath $desktopRoot
try {
    & $desktopPython scripts/inspect-hrc-save.py --self-test --fixture-dir "$desktopChecks/fixtures" --output "$desktopChecks/decoder-self-test.json"
    if ($LASTEXITCODE -ne 0) { throw 'Save decoder self-check failed.' }
    foreach ($desktopName in @('initial', '10m', 'reloaded')) {
        & $desktopPython scripts/inspect-hrc-save.py "$desktopData/hu10bb-pushfold-$desktopName.hrcz" --output "$desktopChecks/hu10bb-pushfold-$desktopName-decoded.json"
        if ($LASTEXITCODE -ne 0) { throw "HU save decoding failed: $desktopName" }
    }
    & $desktopPython scripts/inspect-hrc-save.py "$desktopData/hu10bb-pushfold-10m.hrcz" "$desktopData/hu10bb-pushfold-reloaded.hrcz" --output "$desktopChecks/hu10bb-save-roundtrip-comparison.json"
    if ($LASTEXITCODE -ne 0) { throw 'HU saved-state roundtrip check failed.' }
    & $desktopPython scripts/validate-hrc-desktop-hu.py --output-dir $desktopChecks
    if ($LASTEXITCODE -ne 0) { throw 'Independent HU finite-game benchmark failed.' }
    Write-Output 'Recorded HU files and independent numerical benchmark passed. This does not operate the GUI or establish full HRC equivalence.'
} finally {
    Pop-Location
}
