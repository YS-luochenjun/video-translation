param(
    [ValidateSet('Run', 'Install', 'Status', 'Uninstall')][string]$Action = 'Run',
    [switch]$Execute
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$script = Join-Path $PSScriptRoot 'storage_daily.py'
$identity = $projectRoot.TrimEnd([char[]]'\/').ToLowerInvariant()
$hasher = [Security.Cryptography.SHA256]::Create()
try { $taskSuffix = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($identity))).Replace('-', '').Substring(0, 10) }
finally { $hasher.Dispose() }
$taskName = "VideoLocalizer-Storage-$taskSuffix"
$arguments = '-X utf8 "' + $script + '" --execute'
$plan = [ordered]@{
    owner = 'project'; action = $Action; task_name = $taskName; workspace = $projectRoot
    program = $python; arguments = $arguments; daily_local_time = '18:30'; timezone = 'Asia/Shanghai'
    start_when_available = $true; multiple_instances = 'IgnoreNew'
    scope = 'Current-user logged-in session; Windows runs missed triggers when available. No reset or AI task.'
}

if ($Action -eq 'Run') {
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Installed project .venv Python is missing; run project setup first.' }
    if ($Execute) { & $python -X utf8 $script --execute }
    else { & $python -X utf8 $script }
    exit $LASTEXITCODE
}
if ($Action -eq 'Status') {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $task) { $plan.state = 'not_installed'; $plan | ConvertTo-Json -Depth 5; exit 0 }
    $info = Get-ScheduledTaskInfo -TaskName $taskName
    $plan.state = [string]$task.State
    $plan.program = $task.Actions.Execute
    $plan.arguments = $task.Actions.Arguments
    $plan.start_when_available = $task.Settings.StartWhenAvailable
    $plan.next_run = $info.NextRunTime.ToString('o')
    $plan.last_result = $info.LastTaskResult
    $plan | ConvertTo-Json -Depth 5
    exit 0
}
# Installation and removal also require an explicit execution switch.
if (-not $Execute) { $plan.state = 'planned'; $plan | ConvertTo-Json -Depth 5; exit 0 }
if ($Action -eq 'Uninstall') {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    $plan.state = 'uninstalled'; $plan | ConvertTo-Json -Depth 5
    exit 0
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Installed project .venv Python is missing; run project setup first.' }
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'This workspace storage task already exists; inspect Status before replacing it.' }
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$zone = [TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$currentShanghai = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)
$firstRun = $currentShanghai.Date.AddHours(18).AddMinutes(30)
if ($firstRun -le $currentShanghai) { $firstRun = $firstRun.AddDays(1) }
$trigger = New-ScheduledTaskTrigger -Daily -At $firstRun
$trigger.StartBoundary = $firstRun.ToString("yyyy-MM-dd'T'HH:mm:ss") + '+08:00'
$taskAction = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $projectRoot
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $trigger -Settings $settings -Principal $principal -Description 'Project-owned 18:30 lifecycle sweep; workspace authorization and activity locks are checked each run.' | Out-Null
$plan.state = 'installed'; $plan | ConvertTo-Json -Depth 5
