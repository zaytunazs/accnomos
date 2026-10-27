# usage: merge_mobile.ps1 -Branch muse/android-signin — merges, analyzes, builds the signed AAB
param([Parameter(Mandatory=$true)][string]$Branch)
Set-Location C:\Users\zohai\dev\accnomos
git checkout -q main
git merge --no-edit -q $Branch
if ($LASTEXITCODE -ne 0) { Write-Output "MERGE CONFLICT"; git status --short; exit 1 }
Set-Location apps\mobile
flutter pub get 2>&1 | Select-Object -Last 2
flutter analyze 2>&1 | Select-Object -Last 3
flutter build appbundle --release 2>&1 | Select-Object -Last 3
git -C C:\Users\zohai\dev\accnomos log --oneline -1
