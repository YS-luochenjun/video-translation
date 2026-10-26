param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CliArgs)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Project Python is missing. Run bin/setup.ps1 first (requires uv and FFmpeg on PATH).'
}
& $python (Join-Path $PSScriptRoot 'va.py') @CliArgs
exit $LASTEXITCODE

