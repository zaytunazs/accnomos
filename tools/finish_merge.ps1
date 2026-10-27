# usage: finish_merge.ps1 -Message "Merge branch 'x'" [-Mobile] — resolves additive conflicts, commits, tests, builds, pushes.
param([Parameter(Mandatory=$true)][string]$Message, [switch]$Mobile)
Set-Location C:\Users\zohai\dev\accnomos
& .\.venv\Scripts\python.exe tools\resolve_keep_both.py
if ($LASTEXITCODE -ne 0) { Write-Output "RESOLVE FAILED"; exit 1 }
git add -A tools
git commit -q -m $Message
Write-Output "== python tests"
& .\.venv\Scripts\python.exe -m pytest -q services/runtime services/hmrc-relay packages 2>&1 | Select-Object -Last 1
Write-Output "== web build"
Push-Location apps\web; pnpm run build 2>&1 | Select-String -Pattern 'rror|Compiled' | Select-Object -First 5; Pop-Location
if ($Mobile) { Push-Location apps\mobile; flutter analyze 2>&1 | Select-Object -Last 1; Pop-Location }
git push -q origin main
git log --oneline -1
