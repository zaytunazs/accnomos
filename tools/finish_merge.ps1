# Resolves the known conflicts, commits the merge, runs tests + web build, pushes.
Set-Location C:\Users\zohai\dev\accnomos
& .\.venv\Scripts\python.exe tools\resolve_conflicts.py services\runtime\app\main.py apps\web\src\lib\runtime.ts
git add services/runtime/app/main.py apps/web/src/lib/runtime.ts tools/resolve_conflicts.py tools/merge_spark.ps1 tools/emu_signin_probe.ps1 tools/emu_signin_tap.ps1 tools/finish_merge.ps1
git commit -q -m "Merge branch 'claude/mail-intake' (resolve router + runtime.ts additions)"
Write-Output "== python tests"
& .\.venv\Scripts\python.exe -m pytest -q services/runtime services/hmrc-relay packages 2>&1 | Select-Object -Last 2
Write-Output "== web build"
Push-Location apps\web; pnpm run build 2>&1 | Select-String -Pattern 'rror|Compiled' | Select-Object -First 5; Pop-Location
git push -q origin main
git log --oneline -1
