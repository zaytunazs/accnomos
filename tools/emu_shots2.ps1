# Launches the installed app and captures the tab screens via on-device screencap + adb pull (binary-safe).
$sdk = "C:\Users\zohai\dev\android-sdk"; $env:ANDROID_SERIAL = "emulator-5554"; $adb = "$sdk\platform-tools\adb.exe"
$out = "C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds\listing\screens"
Remove-Item "$out\*.png" -ErrorAction SilentlyContinue
& $adb shell input keyevent 3 | Out-Null            # home, dismiss any ANR dialog
& $adb shell am force-stop com.accnomos.app
& $adb shell am start -n com.accnomos.app/com.accnomos.accnomos_mobile.MainActivity | Out-Null
Start-Sleep 12
function Shot($name) {
  & $adb shell screencap -p /sdcard/$name.png
  & $adb pull /sdcard/$name.png "$out\$name.png" | Out-Null
  Write-Output "shot $name $((Get-Item "$out\$name.png").Length) bytes"
}
Shot "01-first"
& $adb shell dumpsys window | Select-String -Pattern 'mCurrentFocus' | Select-Object -First 1
& $adb shell input tap 540 2300; Start-Sleep 4; Shot "02-tab-mid"
& $adb shell input tap 945 2300; Start-Sleep 4; Shot "03-tab-right"
& $adb shell input tap 135 2300; Start-Sleep 4; Shot "04-tab-left"
& $adb shell input tap 405 2300; Start-Sleep 4; Shot "05-tab-2"
& $adb shell input tap 675 2300; Start-Sleep 4; Shot "06-tab-3"
