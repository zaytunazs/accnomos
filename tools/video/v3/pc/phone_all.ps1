param([string]$shots = "p-home,p-receipt,p-personal")
# One at a time, with a pause: the live API rate-limits per IP.
foreach ($s in $shots.Split(",")) {
  & C:\Users\zohai\dev\video-v2\phone.ps1 $s 2>&1 | Where-Object { "$_" -notmatch "ui.xml" }
  Start-Sleep 20
}
"ALL_PHONE_DONE"
