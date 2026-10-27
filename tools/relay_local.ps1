# Starts the HMRC relay locally on :8787 with secrets read from the repo .env (never printed).
param([switch]$Stop)
$repo = "C:\Users\zohai\dev\accnomos"
Set-Location $repo
if ($Stop) {
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'relay.main:app' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  Write-Output "relay stopped"; exit 0
}
Get-Content .env | ForEach-Object {
  if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2].Trim().Trim('"'), 'Process') }
}
$env:HMRC_REDIRECT_URI = "http://localhost:8787/hmrc/callback"
$env:RELAY_ALLOWED_REDIRECTS = "https://accnomos.com,https://www.accnomos.com"
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$log = Join-Path $repo ".relay-local.log"
Start-Process -FilePath $py -ArgumentList "-m","uvicorn","relay.main:app","--host","127.0.0.1","--port","8787" -WorkingDirectory (Join-Path $repo "services\hmrc-relay") -RedirectStandardOutput $log -RedirectStandardError "$log.err" -WindowStyle Hidden
Start-Sleep -Seconds 4
try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/health).Content } catch { Write-Output "health failed: $_"; Get-Content "$log.err" -Tail 20 }
