# Installs the debug build on the running emulator, walks the tabs and captures Play screenshots.
$sdk = "C:\Users\zohai\dev\android-sdk"; $env:ANDROID_SERIAL = "emulator-5554"; $adb = "$sdk\platform-tools\adb.exe"
$out = "C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds\listing\screens"
New-Item -ItemType Directory -Force $out | Out-Null
& $adb wait-for-device
$b = & $adb shell getprop sys.boot_completed
Write-Output "boot_completed=$b"
Set-Location C:\Users\zohai\dev\accnomos\apps\mobile
flutter build apk --debug 2>&1 | Select-Object -Last 1
& $adb install -r build\app\outputs\flutter-apk\app-debug.apk | Select-Object -Last 1
& $adb shell settings put global window_animation_scale 0
& $adb shell settings put global transition_animation_scale 0
& $adb shell settings put global animator_duration_scale 0
& $adb shell am start -n com.accnomos.app/.MainActivity | Out-Null
Start-Sleep 8
function Shot($name) { & $adb exec-out screencap -p > "$out\$name.png"; Write-Output "shot $name" }
Shot "01-home"
# bottom nav taps: assume 4 tabs across the bottom on a 1080x2400 screen
$y = 2300
& $adb shell input tap 405 $y; Start-Sleep 3; Shot "02-review"
& $adb shell input tap 675 $y; Start-Sleep 3; Shot "03-ask"
& $adb shell input tap 945 $y; Start-Sleep 3; Shot "04-settings"
& $adb shell input tap 135 $y; Start-Sleep 3; Shot "05-first"
Get-ChildItem $out | Select -Expand Name
