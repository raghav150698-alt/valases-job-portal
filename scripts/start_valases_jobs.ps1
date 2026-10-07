param([int]$Port = 8010)
$ErrorActionPreference = 'Stop'
$workspacePath = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $workspacePath '.codex-run-venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = (Get-Command python -ErrorAction Stop).Source
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is already occupied. Choose another port or stop the existing preview."
}
$logDirectory = Join-Path $workspacePath 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$env:JOBS_DEMO = 'true'
$env:JOBS_CREATE_SCHEMA = 'true'
$env:JOBS_SECURE_COOKIES = 'false'
$env:JOBS_PUBLIC_ORIGIN = "http://127.0.0.1:$Port"
$databaseFile = (Join-Path $workspacePath 'valases_jobs.db').Replace('\', '/')
$env:JOBS_DATABASE_URL = "sqlite:///$databaseFile"
& $pythonPath -m valases_jobs.migrate
if ($LASTEXITCODE -ne 0) { throw 'Jobs database migration failed' }
$process = Start-Process -FilePath $pythonPath -ArgumentList @('-m', 'uvicorn', 'valases_jobs.main:app', '--host', '127.0.0.1', '--port', $Port) -WorkingDirectory $workspacePath -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory 'valases-jobs.out.log') -RedirectStandardError (Join-Path $logDirectory 'valases-jobs.err.log')
Write-Output "Valases Jobs local demo starting at http://127.0.0.1:$Port (process $($process.Id))"
