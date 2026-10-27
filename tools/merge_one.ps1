# usage: merge_one.ps1 -Clone repo-lane-d -Branch claude/voice-ask -Slug voice-ask [-Mobile]
# fetch → merge → (auto-resolve additive conflicts) → archive review files → tests/build → push only when green.
param([Parameter(Mandatory=$true)][string]$Clone, [Parameter(Mandatory=$true)][string]$Branch, [Parameter(Mandatory=$true)][string]$Slug, [switch]$Mobile)
Set-Location C:\Users\zohai\dev\accnomos
git checkout -q main; git pull -q --no-rebase origin main
git fetch -q "spark:spark/accnomos/$Clone" $Branch; if ($LASTEXITCODE -ne 0) { Write-Output "FETCH FAILED $Branch"; exit 1 }
git branch -f $Branch FETCH_HEAD
git merge --no-edit -q $Branch 2>&1 | Select-String -Pattern 'CONFLICT' | Select-Object -First 8
if ($Mobile) { & .\tools\finish_merge.ps1 -Message "Merge branch $Branch" -Slug $Slug -Mobile } else { & .\tools\finish_merge.ps1 -Message "Merge branch $Branch" -Slug $Slug }
