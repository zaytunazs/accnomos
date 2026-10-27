# usage: finish_merge.ps1 -Message "Merge branch 'x'" -Slug sam-crop [-Mobile]
# Resolves additive conflicts, archives REVIEW.md/TASK_BRIEF.md to docs/reviews/<slug>/, commits, tests, builds, pushes.
param([Parameter(Mandatory=$true)][string]$Message, [string]$Slug = "", [switch]$Mobile)
Set-Location C:\Users\zohai\dev\accnomos
foreach ($f in "REVIEW.md","TASK_BRIEF.md") { if (Test-Path $f) { git checkout --theirs -- $f 2>$null } }
& .\.venv\Scripts\python.exe tools\resolve_keep_both.py
if ($LASTEXITCODE -ne 0) { Write-Output "RESOLVE FAILED"; exit 1 }
if ($Slug) {
  New-Item -ItemType Directory -Force "docs\reviews\$Slug" | Out-Null
  foreach ($f in "REVIEW.md","TASK_BRIEF.md") { if (Test-Path $f) { git mv -f $f "docs/reviews/$Slug/$f" 2>$null; if (Test-Path $f) { Move-Item -Force $f "docs\reviews\$Slug\$f" } } }
}
git add -A
git commit -q -m $Message
Write-Output "== python tests"
& .\.venv\Scripts\python.exe -m pytest -q services/runtime services/hmrc-relay packages 2>&1 | Select-Object -Last 1
Write-Output "== web build"
Push-Location apps\web; pnpm run build 2>&1 | Select-String -Pattern 'rror|Compiled' | Select-Object -First 5; Pop-Location
if ($Mobile) { Push-Location apps\mobile; flutter analyze 2>&1 | Select-Object -Last 1; Pop-Location }
git push -q origin main
git log --oneline -1
