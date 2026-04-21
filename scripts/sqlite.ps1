param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$defaultSqliteExe = Join-Path $projectRoot "tools\sqlite\sqlite3.exe"
$sqliteExe = if ([string]::IsNullOrWhiteSpace($env:KNET_SQLITE_EXE)) {
    $defaultSqliteExe
} else {
    $env:KNET_SQLITE_EXE
}

if (-not (Test-Path -LiteralPath $sqliteExe -PathType Leaf)) {
    throw "SQLite executable not found: $sqliteExe. Run scripts\\deploy-sqlite.ps1 first, or set KNET_SQLITE_EXE."
}

& $sqliteExe @Arguments
exit $LASTEXITCODE
