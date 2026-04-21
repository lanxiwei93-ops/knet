param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$defaultCondaExe = Join-Path $projectRoot "tools\conda\conda.exe"
$condaExe = if ([string]::IsNullOrWhiteSpace($env:KNET_CONDA_EXE)) {
    $defaultCondaExe
} else {
    $env:KNET_CONDA_EXE
}

if (-not (Test-Path -LiteralPath $condaExe -PathType Leaf)) {
    throw "Conda executable not found: $condaExe. Run scripts\\deploy-conda.ps1 first, or set KNET_CONDA_EXE."
}

& $condaExe @Arguments
exit $LASTEXITCODE
