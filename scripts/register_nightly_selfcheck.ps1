# Register MiniAI nightly self-check (current user, no elevation).
# Daily 03:17, run only when idle 10 minutes, do not wake the computer.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root "scripts\nightly_selfcheck.ps1"
$TaskName = "MiniAI-NightlySelfCheck"

$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Script`"" `
  -WorkingDirectory $Root

$trigger = New-ScheduledTaskTrigger -Daily -At 3:17am

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -RunOnlyIfIdle `
  -IdleDuration (New-TimeSpan -Minutes 10) `
  -IdleWaitTimeout (New-TimeSpan -Hours 2) `
  -DontStopOnIdleEnd `
  -MultipleInstances IgnoreNew

# Do not wake the computer; do not catch up a missed 03:17 run later.
$settings.WakeToRun = $false
$settings.StartWhenAvailable = $false

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Principal $principal `
  -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State, @{n='User';e={$_.Principal.UserId}}
Get-ScheduledTaskInfo -TaskName $TaskName | Format-List NextRunTime, LastRunTime, LastTaskResult
Write-Host "Registered $TaskName -> $Script"
