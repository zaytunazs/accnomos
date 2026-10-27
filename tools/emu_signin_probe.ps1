# Opens Settings in the app, taps the Microsoft sign-in button and captures what happens (redirect-URI check).
$sdk = "C:\Users\zohai\dev\android-sdk"; $env:ANDROID_SERIAL = "emulator-5554"; $adb = "$sdk\platform-tools\adb.exe"
$out = "C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds\listing\probe"
New-Item -ItemType Directory -Force $out | Out-Null
Set-Location C:\Users\zohai\dev\accnomos\apps\mobile
flutter build apk --debug 2>&1 | Select-Object -Last 1
& $adb install -r build\app\outputs\flutter-apk\app-debug.apk | Select-Object -Last 1
& $adb shell am force-stop com.accnomos.app
& $adb shell am start -n com.accnomos.app/com.accnomos.accnomos_mobile.MainActivity | Out-Null
Start-Sleep 10
function Shot($name) { & $adb shell screencap -p /sdcard/$name.png; & $adb pull /sdcard/$name.png "$out\$name.png" | Out-Null; Write-Output "shot $name" }
# Home -> settings gear top-right (from screenshot: ~ (1020, 240) on 1080x2400)
& $adb shell input tap 1020 240; Start-Sleep 4; Shot "10-settings"
& $adb shell uiautomator dump /sdcard/ui.xml | Out-Null
& $adb shell cat /sdcard/ui.xml | Select-String -Pattern 'Sign in' -SimpleMatch | ForEach-Object { ($_ -split 'bounds=')[1] } | Select-Object -First 3
