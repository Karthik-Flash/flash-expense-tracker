# Back up the app's database (the public schema) with pg_dump from the postgres:17 Docker
# image, in custom format, to D:\FlashPrivate\backups\flash-YYYYMMDD-HHmm.dump.
#
# For the owner. Needs Docker Desktop running. Reads DATABASE_URL from backend\.env itself
# and never prints it: the URL reaches the container through an environment variable, not
# the command line. Prints only the file name and its size.
#
#   powershell -ExecutionPolicy Bypass -File scripts\backup_db.ps1
#
# Restore: see NOTES.md ("Back up and restore"). -EnvFile and -OutDir exist for tests on a
# throwaway database only.

param(
    [string]$EnvFile = (Join-Path $PSScriptRoot '..\backend\.env'),
    [string]$OutDir = 'D:\FlashPrivate\backups'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $EnvFile)) {
    Write-Output 'Backup failed: backend\.env was not found.'
    exit 1
}
$line = Get-Content -LiteralPath $EnvFile | Where-Object { $_ -match '^\s*DATABASE_URL\s*=' } | Select-Object -Last 1
if (-not $line) {
    Write-Output 'Backup failed: DATABASE_URL is not set in backend\.env.'
    exit 1
}
$url = ($line -replace '^\s*DATABASE_URL\s*=\s*', '').Trim().Trim('"').Trim("'")
# The app may name its driver (postgresql+psycopg://); pg_dump wants postgresql://.
$url = $url -replace '^postgres(ql)?(\+\w+)?://', 'postgresql://'
if ($url -notmatch '^postgresql://') {
    Write-Output 'Backup failed: DATABASE_URL is not a Postgres URL.'
    exit 1
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$name = 'flash-{0}.dump' -f (Get-Date -Format 'yyyyMMdd-HHmm')
$file = Join-Path $OutDir $name
if (Test-Path -LiteralPath $file) {
    Write-Output "Backup failed: $name already exists. Wait a minute and run again."
    exit 1
}

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
}

if ($code -ne 0 -or -not (Test-Path -LiteralPath $file)) {
    if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file }
    Write-Output "Backup failed (exit $code). Is Docker Desktop running, and is the database reachable? Nothing was kept."
    exit 1
}
$size = (Get-Item -LiteralPath $file).Length
Write-Output ('{0}  {1:N1} MB' -f $name, ($size / 1MB))
