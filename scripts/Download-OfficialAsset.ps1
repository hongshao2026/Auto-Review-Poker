param([Parameter(Mandatory)][string]$Uri, [Parameter(Mandatory)][string]$Output)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Invoke-WebRequest -Uri $Uri -OutFile $Output -ConnectionTimeoutSeconds 30 -OperationTimeoutSeconds 900 -MaximumRetryCount 2
