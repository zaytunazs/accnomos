Set-Location C:\Users\zohai\dev\accnomos
Get-Content .env | ForEach-Object {
  if ($_ -match '^([A-Za-z_]+)=(.*)$') {
    $k = $matches[1]; $v = $matches[2].Trim()
    if ($v.Length -gt 0) { "$k=set(len $($v.Length))" } else { "$k=EMPTY" }
  }
}
Write-Output "---"
git status --short
git log --oneline -1
