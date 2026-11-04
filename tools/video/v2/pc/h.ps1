# adb helpers for the emulator shots (phone.ps1): screenshots, taps, swipes, UI dump, find by text, wait, marks.
$adb = "C:\Users\zohai\dev\android-sdk\platform-tools\adb.exe"
$dir = "C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds\video-v2\scout"
New-Item -ItemType Directory -Force $dir | Out-Null
function Shot($name) { $p = Join-Path $dir "$name.png"; cmd /c "`"$adb`" exec-out screencap -p > `"$p`""; "shot $name" }
function Tap($x, $y) { & $adb shell input tap $x $y; Start-Sleep -Milliseconds 900 }
function Swipe($x1,$y1,$x2,$y2,$ms=500) { & $adb shell input swipe $x1 $y1 $x2 $y2 $ms; Start-Sleep -Milliseconds 700 }
function Dump() {
  & $adb shell uiautomator dump /sdcard/ui.xml | Out-Null
  & $adb pull /sdcard/ui.xml "$env:TEMP\ui.xml" | Out-Null
  [xml](Get-Content "$env:TEMP\ui.xml" -Raw)
}
function Find($label) {
  $x = Dump
  $n = $x.SelectNodes("//node") | Where-Object { ($_.text -like "*$label*") -or ($_.'content-desc' -like "*$label*") } | Select-Object -First 1
  if ($n -and $n.bounds -match '\[(\d+),(\d+)\]\[(\d+),(\d+)\]') { return @((([int]$matches[1] + [int]$matches[3]) / 2), (([int]$matches[2] + [int]$matches[4]) / 2)) }
  return $null
}
function TapText($label) {
  $c = Find $label
  if (-not $c) { "NOT FOUND: $label"; return $false }
  Tap $c[0] $c[1]; "tapped $label at $($c[0]),$($c[1])"; return $true
}
function Texts() { $x = Dump; ($x.SelectNodes("//node") | ForEach-Object { if ($_.text) { $_.text } elseif ($_.'content-desc') { "[" + $_.'content-desc' + "]" } }) -join " | " }
function FindExact($label) {
  $x = Dump
  $n = $x.SelectNodes("//node") | Where-Object { ($_.text -eq $label) -or ($_.'content-desc' -eq $label) } | Select-Object -First 1
  if ($n -and $n.bounds -match '\[(\d+),(\d+)\]\[(\d+),(\d+)\]') { return @((([int]$matches[1] + [int]$matches[3]) / 2), (([int]$matches[2] + [int]$matches[4]) / 2)) }
  return $null
}
function TapExact($label) {
  $c = FindExact $label
  if (-not $c) { "NOT FOUND: $label"; return $false }
  Tap $c[0] $c[1]; "tapped $label at $($c[0]),$($c[1])"; return $true
}
function WaitFor($pattern, $secs = 60) {
  $t0 = Get-Date
  while (((Get-Date) - $t0).TotalSeconds -lt $secs) { $tx = Texts; if ($tx -match $pattern) { return $true }; Start-Sleep 2 }
  return $false
}
$global:T0 = Get-Date
function Mark($name) { "MARK $name $([math]::Round(((Get-Date) - $global:T0).TotalSeconds, 2))" }
