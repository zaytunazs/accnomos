param([string]$shot)
# Records one Android shot on the emulator (accnomos_pixel, APK 0.3.16) with adb screenrecord, pulls it to
# builds\video-v2\raw\<shot>.mp4 and writes MARK lines (seconds since the recording started) to <shot>.marks.txt.
# Each shot starts a fresh demo (app data cleared). Emulator: start it with -no-snapshot-load; if it crashed, rename
# %TEMP%\AndroidEmulator\emu-crash-*.db first or its consent dialog blocks the next boot.
. C:\Users\zohai\dev\video-v2\h.ps1
$raw = "C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds\video-v2\raw"
New-Item -ItemType Directory -Force $raw | Out-Null
$marks = Join-Path $raw "$shot.marks.txt"
function M($n) { (Mark $n) | Add-Content $marks }
function StartRec() {
  & $adb shell rm -f /sdcard/rec.mp4 | Out-Null
  Start-Process -WindowStyle Hidden -FilePath $adb -ArgumentList "shell","screenrecord","--bit-rate","12000000","--time-limit","175","/sdcard/rec.mp4"
  Start-Sleep -Milliseconds 1200
  $global:T0 = Get-Date
  "" | Set-Content $marks
}
function StopRec() {
  Start-Sleep 1
  & $adb shell pkill -INT screenrecord | Out-Null
  for ($k = 0; $k -lt 15; $k++) { Start-Sleep 1; $p = & $adb shell pidof screenrecord; if (-not $p) { break } }
  Start-Sleep 2
  & $adb pull /sdcard/rec.mp4 (Join-Path $raw "$shot.mp4") | Out-Null
  "saved $shot"
}
function Demo($which) {
  & $adb shell am force-stop com.accnomos.app
  & $adb shell pm clear com.accnomos.app | Out-Null
  & $adb shell pm grant com.accnomos.app android.permission.CAMERA
  & $adb shell pm grant com.accnomos.app android.permission.RECORD_AUDIO
  & $adb shell pm grant com.accnomos.app android.permission.POST_NOTIFICATIONS 2>$null
  & $adb shell monkey -p com.accnomos.app -c android.intent.category.LAUNCHER 1 | Out-Null
  Start-Sleep 8
  for ($k = 0; $k -lt 4; $k++) {
    if (Find $which) { break }
    $e = Find "Exit demo"
    if ($e) { Tap $e[0] $e[1]; Start-Sleep 6 } else { Start-Sleep 4 }
  }
  TapText $which | Out-Null
  Start-Sleep 14
}
switch ($shot) {
  "p-home" {
    Demo "Try the company demo"
    WaitFor "worded by your AI" 60 | Out-Null
    StartRec
    Start-Sleep 3; M "look"
    Swipe 540 1700 540 1100 1600; Start-Sleep 3
    Swipe 540 1700 540 1100 1600; Start-Sleep 3
    Swipe 540 1100 540 1900 1400; Start-Sleep 2
    StopRec
  }
  "p-receipt" {
    # the sample receipt (apps/web/public/sample-receipt.png) is pushed to /sdcard/Pictures beforehand
    Demo "Try the company demo"
    TapText "Tab 2 of 5" | Out-Null; Start-Sleep 5
    StartRec
    Start-Sleep 2
    Tap 1017 336; Start-Sleep 1                       # Photograph a receipt
    M "gallery"
    Tap 540 944; Start-Sleep 2                        # Choose from gallery
    if (Find "Dismiss") { TapExact "Dismiss" | Out-Null; Start-Sleep 1 }
    $c = Find "6:13:25"; if ($c) { Tap $c[0] $c[1] } else { Tap 540 825 }
    Start-Sleep 1
    Tap 886 2220; Start-Sleep 2                       # Add (1)
    M "queued"
    $u = FindExact "Upload 1"; if ($u) { Tap $u[0] $u[1] } else { Tap 540 1438 }
    M "wait"
    WaitFor "Confirm the type" 60 | Out-Null
    M "ready"
    Start-Sleep 2
    TapExact "Confirm" | Out-Null
    M "wait2"
    WaitFor "NOVEX" 120 | Out-Null
    Start-Sleep 2
    M "ready2"
    Start-Sleep 3
    Swipe 540 1800 540 1150 1500; Start-Sleep 3
    M "approve"
    TapExact "Approve" | Out-Null
    Start-Sleep 4
    StopRec
  }
  "p-personal" {
    Demo "Try the personal demo"
    WaitFor "worded by your AI|Your summary" 60 | Out-Null
    Start-Sleep 8
    StartRec
    Start-Sleep 3
    Swipe 540 1700 540 1150 1600; Start-Sleep 3
    Swipe 540 1700 540 1150 1600; Start-Sleep 3
    StopRec
  }
}
"PHONE_DONE $shot"
