# Back up the app's database (the public schema) with pg_dump from the postgres:17 Docker
# image, in custom format, to D:\FlashPrivate\backups\flash-YYYYMMDD-HHmm.dump.
#
# For the owner, by hand or from the weekly scheduled task (scripts\register_backup_task.ps1).
# Reads DATABASE_URL from backend\.env itself and never prints or logs it: the URL reaches
# the container through an environment variable, not the command line.
#
#   powershell -ExecutionPolicy Bypass -File scripts\backup_db.ps1
#
# 5G (D-157):
# - Docker Desktop not running: it is started, and the script waits up to 3 minutes for it.
# - The newest 12 dumps are kept; older flash-YYYYMMDD-HHmm.dump files in the backup folder
#   are deleted. Nothing else is ever deleted (other files, other names, other folders).
# - One line per run is appended to backup.log in the backup folder: the time, OK or FAILED,
#   the file and its size, or the reason. Never the URL.
# - Exit code 0 when a dump was made, 1 when not.
#
# Restore: see NOTES.md ("Back up and restore"). -EnvFile, -OutDir, -Keep and -DockerWaitSeconds
# exist for tests on a throwaway database only.

param(
    [string]$EnvFile = (Join-Path $PSScriptRoot '..\backend\.env'),
    [string]$OutDir = 'D:\FlashPrivate\backups',
    [int]$Keep = 12,
    [int]$DockerWaitSeconds = 180
)

$ErrorActionPreference = 'Stop'
$Pattern = '^flash-\d{8}-\d{4}\.dump$'

function Write-Log([string]$text) {
    try {
        New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
        $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        Add-Content -LiteralPath (Join-Path $OutDir 'backup.log') -Value "$stamp  $text" -Encoding utf8
    } catch {
        # A log that cannot be written must not hide the backup's own result.
    }
}

function Stop-Backup([string]$reason) {
    Write-Output "Backup failed: $reason"
    Write-Log "FAILED  $reason"
    exit 1
}

function Test-Docker {
    $ErrorActionPreference = 'Continue'
    docker version --format '{{.Server.Version}}' *> $null
    return $LASTEXITCODE -eq 0
}

function Start-Docker {
    if (Test-Docker) { return $true }
    $exe = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),
        (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $exe) { return $false }
    Write-Output 'Starting Docker Desktop...'
    Start-Process -FilePath $exe | Out-Null
    $deadline = (Get-Date).AddSeconds($DockerWaitSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        if (Test-Docker) { return $true }
    }
    return $false
}

if (-not (Test-Path -LiteralPath $EnvFile)) { Stop-Backup 'backend\.env was not found.' }
$line = Get-Content -LiteralPath $EnvFile | Where-Object { $_ -match '^\s*DATABASE_URL\s*=' } | Select-Object -Last 1
if (-not $line) { Stop-Backup 'DATABASE_URL is not set in backend\.env.' }
$url = ($line -replace '^\s*DATABASE_URL\s*=\s*', '').Trim().Trim('"').Trim("'")
# The app may name its driver (postgresql+psycopg://); pg_dump wants postgresql://.
$url = $url -replace '^postgres(ql)?(\+\w+)?://', 'postgresql://'
if ($url -notmatch '^postgresql://') { Stop-Backup 'DATABASE_URL is not a Postgres URL.' }

if (-not (Start-Docker)) { Stop-Backup "Docker Desktop is not running and did not start within $DockerWaitSeconds s." }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$name = 'flash-{0}.dump' -f (Get-Date -Format 'yyyyMMdd-HHmm')
$file = Join-Path $OutDir $name
if (Test-Path -LiteralPath $file) { Stop-Backup "$name already exists. Wait a minute and run again." }

$env:FLASH_BACKUP_URL = $url
try {
    # Output is dropped: pg_dump's messages can name the host and user.
    $mount = '{0}:/out' -f (Resolve-Path -LiteralPath $OutDir).Path
    $ErrorActionPreference = 'Continue'
    docker run --rm -e FLASH_BACKUP_URL -v $mount postgres:17 `
        sh -c 'pg_dump --format=custom --schema=public --no-owner --no-privileges --file="/out/$0" "$FLASH_BACKUP_URL"' $name *> $null
    $code = $LASTEXITCODE
} finally {
    Remove-Item Env:FLASH_BACKUP_URL -ErrorAction SilentlyContinue
    $ErrorActionPreference = 'Stop'
}

if ($code -ne 0 -or -not (Test-Path -LiteralPath $file)) {
    if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
    Stop-Backup "pg_dump exit $code. Is the database reachable? Nothing was kept."
}
$size = (Get-Item -LiteralPath $file).Length
if ($size -le 0) {
    Remove-Item -LiteralPath $file
    Stop-Backup 'the dump was empty. Nothing was kept.'
}

# Keep the newest $Keep dumps: only files named like ours, only in this folder.
$dumps = @(Get-ChildItem -LiteralPath $OutDir -File | Where-Object { $_.Name -match $Pattern } | Sort-Object Name -Descending)
$old = @($dumps | Select-Object -Skip $Keep)
foreach ($f in $old) { Remove-Item -LiteralPath $f.FullName }

$text = '{0}  {1:N1} MB' -f $name, ($size / 1MB)
Write-Output $text
Write-Log ('OK  {0}; kept {1}, removed {2} older' -f $text, ($dumps.Count - $old.Count), $old.Count)
exit 0
