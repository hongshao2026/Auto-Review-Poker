[CmdletBinding()]
param([switch]$Test, [switch]$Bench)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$portable = Join-Path $workspace '.research-cache/postflop-toolchain'
$toolchain = '1.99.1-x86_64-pc-windows-gnu'
$cargo = Join-Path $portable 'cargo/bin/cargo.exe'
$selection = @()
if (Test-Path -LiteralPath $cargo) {
    $env:CARGO_HOME = Join-Path $portable 'cargo'
    $env:RUSTUP_HOME = Join-Path $portable 'rustup'
    $gnu = Join-Path $env:RUSTUP_HOME "toolchains/$toolchain/lib/rustlib/x86_64-pc-windows-gnu/bin"
    $llvm = 'D:/Tools/REA-Research/llvm-mingw-20250402-ucrt-x86_64/bin'
    if (!(Test-Path -LiteralPath (Join-Path $llvm 'dlltool.exe'))) {
        throw 'Portable build requires LLVM MinGW dlltool. Use a normal Rust installation or restore the local LLVM MinGW tools.'
    }
    $env:PATH = "$llvm;$gnu;$gnu/self-contained;$env:PATH"
    $env:CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER = Join-Path $gnu 'self-contained/x86_64-w64-mingw32-gcc.exe'
    $selection = @("+$toolchain")
} else {
    $cargo = (Get-Command cargo -ErrorAction Stop).Source
}

$target = Join-Path $workspace '.research-cache/postflop-target'
$manifest = Join-Path $PSScriptRoot 'Cargo.toml'
$flags = @('--manifest-path', $manifest, '--target-dir', $target, '--locked', '--release')
& $cargo @selection build @flags --bin solver
if ($LASTEXITCODE -ne 0) { throw "Solver build exited $LASTEXITCODE" }
$bin = Join-Path $PSScriptRoot 'bin'
New-Item -ItemType Directory -Force -Path $bin | Out-Null
Copy-Item -LiteralPath (Join-Path $target 'release/solver.exe') -Destination $bin -Force
Write-Output (Join-Path $bin 'solver.exe')
if ($Bench) {
    & $cargo @selection build @flags --example compare_latency
    if ($LASTEXITCODE -ne 0) { throw "Benchmark build exited $LASTEXITCODE" }
    Write-Output (Join-Path $target 'release/examples/compare_latency.exe')
}
if ($Test) {
    & $cargo @selection test @flags
    if ($LASTEXITCODE -ne 0) { throw "Rust solver tests exited $LASTEXITCODE" }
    Push-Location -LiteralPath $workspace
    try {
        python -B -m unittest discover -s postflop_lab/tests -v
        if ($LASTEXITCODE -ne 0) { throw "Python solver tests exited $LASTEXITCODE" }
    } finally {
        Pop-Location
    }
}
