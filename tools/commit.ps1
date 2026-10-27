# usage: commit.ps1 -Message "subject" [-Files a,b,c]  (adds trailer lines; pushes main)
param([Parameter(Mandatory=$true)][string]$Message, [string[]]$Files)
Set-Location C:\Users\zohai\dev\accnomos
if ($Files) { git add -- $Files } else { git add -A }
$msg = "$Message`n`nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`nClaude-Session: https://claude.ai/code/session_016yXB5QuWzQsiYcNDuFkMUL"
$tmp = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($tmp, $msg)
git commit -q -F $tmp
Remove-Item $tmp
git push -q origin main
git log --oneline -1
