$sdk = "C:\Users\zohai\dev\android-sdk"; $env:ANDROID_SERIAL = "emulator-5554"; $adb = "$sdk\platform-tools\adb.exe"
$out = "C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds\listing\probe"
function Shot($name) { & $adb shell screencap -p /sdcard/$name.png; & $adb pull /sdcard/$name.png "$out\$name.png" | Out-Null; Write-Output "shot $name" }
& $adb shell input tap 540 575   # Sign in with Microsoft (1080x2400 coords from the 405x900 preview: 202,216 -> x2.667)
Start-Sleep 12
Shot "11-after-signin-tap"
& $adb shell dumpsys window | Select-String 'mCurrentFocus' | Select-Object -First 1
& $adb logcat -d -t 400 | Select-String -Pattern 'MSAL|msal|redirect|AADSTS|Accnomos|flutter' | Select-Object -Last 25
