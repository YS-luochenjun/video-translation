param([ValidateSet('Run', 'Install', 'Status', 'Uninstall')][string]$Action = 'Run')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$settingsPath = Join-Path $projectRoot 'config\hooks.json'
$hook = (Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json).knowledge_daily
$taskSuffix = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot))).Replace('-', '').Substring(0, 10)
$taskName = "VideoLocalizer-Knowledge-$taskSuffix"
$receiptPath = Join-Path $projectRoot 'knowledge\local\curation\schedule.json'
$encoding = New-Object Text.UTF8Encoding($false)

if ($Action -eq 'Run') {
    & (Join-Path $PSScriptRoot 'va.ps1') hooks run --due
    exit $LASTEXITCODE
}
if ($Action -eq 'Status') {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $task) { @{ owner = 'project'; task_name = $taskName; state = 'not_installed' } | ConvertTo-Json; exit 1 }
    $info = Get-ScheduledTaskInfo -TaskName $taskName
    @{ owner = 'project'; task_name = $taskName; state = [string]$task.State; next_run = $info.NextRunTime.ToString('o'); last_result = $info.LastTaskResult; action = $task.Actions.Arguments } | ConvertTo-Json
    exit 0
}
if ($Action -eq 'Uninstall') {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    if (Test-Path -LiteralPath $receiptPath) {
        $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $receipt.status = 'UNINSTALLED'
        [IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json -Depth 8), $encoding)
    }
    exit 0
}

if ($hook.timezone -ne 'Asia/Shanghai') { throw 'Unsupported project hook timezone' }
if (-not $hook.enabled) { throw 'Project hook is disabled' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'knowledge\local\curation\checkpoint.json'))) { throw 'Create an explicit project baseline before installing the timer' }
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'Project task already exists; inspect it before replacing' }
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$zone = [TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$currentShanghai = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)
$firstRun = $currentShanghai.Date.Add([TimeSpan]::Parse($hook.time))
if ($firstRun -le $currentShanghai) { $firstRun = $firstRun.AddDays(1) }
$trigger = New-ScheduledTaskTrigger -Daily -At $firstRun
$trigger.StartBoundary = $firstRun.ToString("yyyy-MM-dd'T'HH:mm:ss") + '+08:00'
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $PSScriptRoot 'project-hooks.ps1') + '" -Action Run'
$program = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$taskAction = New-ScheduledTaskAction -Execute $program -Argument $arguments -WorkingDirectory $projectRoot
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger @($trigger, $logon) -Settings $taskSettings -Principal $principal -Description 'Project-owned daily incremental knowledge curation. Candidate only; no paid media model calls.' | Out-Null
$registered = Get-ScheduledTask -TaskName $taskName
$info = Get-ScheduledTaskInfo -TaskName $taskName
$receipt = @{ schema_version = 2; owner = 'project'; scheduler = 'windows_task_scheduler'; task_name = $taskName; status = 'ACTIVE'; timezone = $hook.timezone; daily_local_time = $hook.time; action_script = 'bin/project-hooks.ps1'; next_run = $info.NextRunTime.ToString('o'); installed_at = [DateTime]::UtcNow.ToString('o'); scope = 'Current-user logged-in session; computer must be awake; desktop app not required' }
[IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json -Depth 8), $encoding)
$receipt | ConvertTo-Json -Depth 8
