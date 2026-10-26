[CmdletBinding()]
param(
    [string]$PythonVersion = '3.12',
    [string]$FfmpegBin
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$root = Split-Path -Parent $PSScriptRoot
function Run-Native([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Installation step failed ($LASTEXITCODE): $Executable" }
}
$runtime = Join-Path $root '.runtime'
$uv = Join-Path $runtime 'bin/uv.exe'
New-Item -ItemType Directory -Force (Split-Path -Parent $uv) | Out-Null
if (-not (Test-Path -LiteralPath $uv)) {
    $installedUv = Get-Command uv -ErrorAction Stop
    Copy-Item -LiteralPath $installedUv.Source -Destination $uv
}
if (-not $FfmpegBin) {
    $localMedia = Join-Path $runtime 'ffmpeg/bin'
    if (Test-Path -LiteralPath (Join-Path $localMedia 'ffmpeg.exe')) { $FfmpegBin = $localMedia }
    else { $FfmpegBin = Split-Path -Parent (Get-Command ffmpeg -ErrorAction Stop).Source }
}
$mediaTarget = Join-Path $runtime 'ffmpeg/bin'
New-Item -ItemType Directory -Force $mediaTarget | Out-Null
foreach ($name in @('ffmpeg.exe', 'ffprobe.exe')) {
    $source = Join-Path $FfmpegBin $name
    if (-not (Test-Path -LiteralPath $source)) { throw "Missing media tool: $source" }
    $target = Join-Path $mediaTarget $name
    if ([IO.Path]::GetFullPath($source) -ne [IO.Path]::GetFullPath($target)) {
        Copy-Item -LiteralPath $source -Destination $target
    }
}
# Shared builds may also need adjacent DLLs. Keep them with the executables.
if ([IO.Path]::GetFullPath($FfmpegBin) -ne [IO.Path]::GetFullPath($mediaTarget)) {
    Get-ChildItem -LiteralPath $FfmpegBin -Filter '*.dll' -File | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $mediaTarget }
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $runtime 'python'
$env:UV_CACHE_DIR = Join-Path $root 'work/cache/uv'
$env:UV_PYTHON_BIN_DIR = Join-Path $runtime 'bin'
$env:TEMP = Join-Path $root 'work/tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts/python.exe'
$concrete = @(Get-ChildItem -LiteralPath $env:UV_PYTHON_INSTALL_DIR -Directory -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match '^cpython-\d+\.\d+\.\d+-windows-' -and $_.Name.StartsWith("cpython-$PythonVersion") -and (Test-Path -LiteralPath (Join-Path $_.FullName 'python.exe'))
})
if ($concrete.Count -eq 0) {
    Run-Native $uv @('python', 'install', $PythonVersion, '--no-bin', '--no-registry')
    $concrete = @(Get-ChildItem -LiteralPath $env:UV_PYTHON_INSTALL_DIR -Directory | Where-Object {
        $_.Name -match '^cpython-\d+\.\d+\.\d+-windows-' -and $_.Name.StartsWith("cpython-$PythonVersion") -and (Test-Path -LiteralPath (Join-Path $_.FullName 'python.exe'))
    })
}
if ($concrete.Count -ne 1) { throw 'Choose an exact -PythonVersion matching one project Python installation' }
$managed = Join-Path $concrete[0].FullName 'python.exe'
# Bind to the concrete patch directory, never uv's mutable minor-version link.
$rebind = $true
if (Test-Path -LiteralPath $python) {
    $currentBase = & $python -c 'import sys; print(sys.base_prefix)' 2>$null
    $rebind = $LASTEXITCODE -ne 0 -or $currentBase -ne $concrete[0].FullName
}
if ($rebind) {
    Run-Native $uv @('venv', $venv, '--allow-existing', '--python', $managed, '--relocatable', '--link-mode', 'copy')
}
$base = & $python -c 'import sys; print(sys.base_prefix)'
if ($LASTEXITCODE -ne 0 -or -not ([IO.Path]::GetFullPath($base).StartsWith([IO.Path]::GetFullPath($runtime) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase))) {
    throw 'Existing .venv depends on an external Python. Preserve it separately and rerun setup with an empty .venv.'
}
$fonts = Join-Path $root 'assets/fonts'
New-Item -ItemType Directory -Force $fonts | Out-Null
foreach ($name in @('msyh.ttc', 'msyhbd.ttc', 'simsun.ttc', 'simkai.ttf', 'arial.ttf', 'arialbd.ttf', 'YuGothM.ttc', 'YuGothB.ttc', 'malgun.ttf', 'malgunbd.ttf')) {
    $source = Join-Path $env:WINDIR "Fonts/$name"
    $target = Join-Path $fonts $name
    if ((Test-Path -LiteralPath $source) -and -not (Test-Path -LiteralPath $target)) { Copy-Item -LiteralPath $source -Destination $target }
}
Run-Native $python @((Join-Path $PSScriptRoot 'install_dependencies.py'), '--uv', $uv)
Run-Native $python @((Join-Path $PSScriptRoot 'va.py'), 'doctor')
