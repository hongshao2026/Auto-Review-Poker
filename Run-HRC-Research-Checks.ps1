$ErrorActionPreference = 'Stop'
$researchRoot = $PSScriptRoot
$researchPython = 'C:\Python313\python.exe'
$researchChecks = @(
    @('scripts/validate-hrc-icm.py'),
    @('scripts/validate-hrc-cards.py'),
    @('scripts/run-hrc-probe.py', 'strategy'),
    @('scripts/run-hrc-probe.py', 'tree'),
    @('scripts/run-hrc-probe.py', 'settlement'),
    @('scripts/run-hrc-probe.py', 'traversal'),
    @('scripts/validate-hrc-abstraction.py')
)
foreach ($researchCheck in $researchChecks) {
    $researchScript = Join-Path $researchRoot $researchCheck[0]
    $researchArguments = @($researchCheck | Select-Object -Skip 1)
    & $researchPython $researchScript @researchArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Research check failed: $($researchCheck -join ' ')"
    }
}
Write-Output 'All reviewed original-bytecode research checks passed. Full HRC equivalence is not established.'
