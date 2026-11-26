# Register the weekly database backup as a Windows scheduled task (5G, D-157). For the owner,
# once; agents never run it.
#
#   powershell -ExecutionPolicy Bypass -File scripts\register_backup_task.ps1
#
# The task "Flash weekly backup" runs scripts\backup_db.ps1 every Sunday at 21:00, only while
# you are logged in (it needs Docker Desktop, which runs in your session), and runs as soon
# as the laptop is awake again when 21:00 was missed (asleep or off). It runs as you, with
# your normal rights; no password is stored. Running this again replaces the task.

param(
    [string]$TaskName = 'Flash weekly backup'
)

$ErrorActionPreference = 'Stop'
$script = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'backup_db.ps1')).Path
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $script) `
    -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '21:00'
# StartWhenAvailable: a missed run starts when the laptop is next awake. Interactive: only
# while you are logged in. One hour is far more than a backup takes.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description 'Weekly backup of the Flash database (scripts\backup_db.ps1).' -Force | Out-Null

Write-Output "Registered: $TaskName (every Sunday 21:00; a missed run starts when the laptop is next awake)."
Write-Output ''
Write-Output 'Check it:'
Write-Output "  Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo   # LastRunTime, LastTaskResult (0 = OK), NextRunTime"
Write-Output "  Get-Content D:\FlashPrivate\backups\backup.log -Tail 5             # one line per run"
Write-Output 'Run it now (a test):'
Write-Output "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Output 'Remove it:'
Write-Output "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
