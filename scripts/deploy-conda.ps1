param(
    [string]$Source = "D:\anaconda3\_conda.exe",
    [string]$TargetRelativePath = "tools\conda\conda.exe"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$targetPath = Join-Path $projectRoot $TargetRelativePath
$targetDir = Split-Path -Parent $targetPath

if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    throw "Source file not found: $Source"
}

if (-not (Test-Path -LiteralPath $targetDir -PathType Container)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

$sourceHash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash

if (Test-Path -LiteralPath $targetPath -PathType Leaf) {
    $existingTargetHash = (Get-FileHash -LiteralPath $targetPath -Algorithm SHA256).Hash
    if ($existingTargetHash -eq $sourceHash) {
        Write-Output "Conda already deployed to: $targetPath"
        Write-Output "SHA256: $sourceHash"
        exit 0
    }
}

Copy-Item -LiteralPath $Source -Destination $targetPath -Force

$targetHash = (Get-FileHash -LiteralPath $targetPath -Algorithm SHA256).Hash

if ($sourceHash -ne $targetHash) {
    throw "Copy finished, but SHA256 verification failed: $targetPath"
}

Write-Output "Conda deployed to: $targetPath"
Write-Output "SHA256: $targetHash"
