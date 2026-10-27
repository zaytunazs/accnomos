# usage: merge_spark.ps1 -Clone repo-web -Branch claude/ask-books [-Mobile]
# Fetches a branch from a Spark clone, merges into main, runs runtime+relay tests, web build (and flutter analyze with -Mobile), pushes.
param([Parameter(Mandatory=$true)][string]$Clone, [Parameter(Mandatory=$true)][string]$Branch, [switch]$Mobile)
Set-Location C:\Users\zohai\dev\accnomos
git checkout -q main; git pull -q origin main
git fetch -q "spark:spark/accnomos/$Clone" $Branch; if ($LASTEXITCODE -ne 0) { Write-Output "FETCH FAILED"; exit 1 }
git branch -f $Branch FETCH_HEAD
git merge --no-edit -q $Branch
if ($LASTEXITCODE -ne 0) { Write-Output "MERGE CONFLICT"; git status --short; exit 1 }
Write-Output "== python tests"
& .\.venv\Scripts\python.exe -m pytest -q services/runtime services/hmrc-relay packages 2>&1 | Select-Object -Last 3
Write-Output "== web build"
Push-Location apps\web; pnpm run build 2>&1 | Select-String -Pattern 'error|Error|Compiled' | Select-Object -First 5; Pop-Location
if ($Mobile) { Push-Location apps\mobile; flutter analyze 2>&1 | Select-Object -Last 1; Pop-Location }
git push -q origin main
git log --oneline -1
