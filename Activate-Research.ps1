# Dot-source this file: . .\Activate-Research.ps1
$script:ResearchToolRoot = 'D:\Tools\REA-Research'
$script:ResearchNode = Join-Path $script:ResearchToolRoot 'node-v24.22.2-win-x64\node.exe'
$script:ResearchRea = Join-Path $script:ResearchToolRoot 'rea\node_modules\rea-agents\scripts\rea.mjs'
$env:JAVA_HOME = Join-Path $script:ResearchToolRoot 'jdk-21.0.13+9'
$env:GHIDRA_INSTALL_DIR = Join-Path $script:ResearchToolRoot 'ghidra_12.1.4_PUBLIC'
$env:REA_ANALYSIS_PROVIDER = 'ghidra'
$env:npm_config_cache = Join-Path $script:ResearchToolRoot 'npm-cache'
$researchPaths = @((Split-Path $script:ResearchNode), (Join-Path $env:JAVA_HOME 'bin'))
$currentPaths = $env:PATH -split ';'
$env:PATH = (@($researchPaths) + @($currentPaths | Where-Object { $_ -notin $researchPaths })) -join ';'

function rea { & $script:ResearchNode $script:ResearchRea @args }
function vineflower { & (Join-Path $env:JAVA_HOME 'bin\java.exe') -jar (Join-Path $script:ResearchToolRoot 'java-decompilers\vineflower-1.12.0.jar') @args }
function cfr { & (Join-Path $env:JAVA_HOME 'bin\java.exe') -jar (Join-Path $script:ResearchToolRoot 'java-decompilers\cfr-0.152.jar') @args }
function ghidra { & (Join-Path $env:GHIDRA_INSTALL_DIR 'ghidraRun.bat') @args }
