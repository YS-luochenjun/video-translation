param([int]$Port = 8768, [switch]$Background, [switch]$Open)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Project Python missing. Install the project runtime first.'
}
$serverPath = Join-Path $PSScriptRoot 'server.py'
if ($Background) {
    $logPath = Join-Path $projectRoot 'work\workbench'
    New-Item -ItemType Directory -Path $logPath -Force | Out-Null
    $arguments = @('-B', ('"' + $serverPath + '"'), '--port', $Port)
    $process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logPath "server-$Port.out.log") -RedirectStandardError (Join-Path $logPath "server-$Port.err.log") -PassThru
    [pscustomobject]@{pid=$process.Id; url="http://127.0.0.1:$Port"; started_at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logPath "server-$Port.json") -Encoding utf8
    Write-Output "Workbench process: $($process.Id); http://127.0.0.1:$Port"
    if ($Open) { Start-Process "http://127.0.0.1:$Port" }
} else {
    & $pythonPath -B $serverPath --port $Port --workspace $projectRoot
    exit $LASTEXITCODE
}
