# usage: merge_local.ps1 -Branch muse/android-polish [-Mobile] — merges a local branch into main, tests, builds, pushes
param([Parameter(Mandatory=$true)][string]$Branch, [switch]$Mobile)
Set-Location C:\Users\zohai\dev\accnomos
git checkout -q main; git pull -q origin main
git merge --no-edit -q $Branch
if ($LASTEXITCODE -ne 0) { Write-Output "MERGE CONFLICT"; git status --short; exit 1 }
if ($Mobile) {
  Push-Location apps\mobile
  flutter pub get 2>&1 | Select-Object -Last 1
  flutter analyze 2>&1 | Select-Object -Last 1
  flutter test 2>&1 | Select-Object -Last 1
  Pop-Location
} else {
  & .\.venv\Scripts\python.exe -m pytest -q services/runtime services/hmrc-relay packages 2>&1 | Select-Object -Last 1
  Push-Location apps\web; pnpm run build 2>&1 | Select-String -Pattern 'rror|Compiled' | Select-Object -First 3; Pop-Location
}
git push -q origin main
git log --oneline -1
