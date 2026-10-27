# usage: merge_check.ps1 -Branch claude/hmrc-web  — merges into main (no push), runs relay tests + web build
param([Parameter(Mandatory=$true)][string]$Branch)
Set-Location C:\Users\zohai\dev\accnomos
git checkout -q main
git merge --no-edit -q $Branch
if ($LASTEXITCODE -ne 0) { Write-Output "MERGE CONFLICT"; git status --short; exit 1 }
Write-Output "== relay tests"
& .\.venv\Scripts\python.exe -m pytest -q services/hmrc-relay/tests 2>&1 | Select-Object -Last 3
Write-Output "== web build"
Push-Location apps\web
pnpm run build 2>&1 | Select-Object -Last 12
Pop-Location
git log --oneline -1
