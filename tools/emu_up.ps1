# Creates (once) and boots a Pixel-sized AVD for screenshots. Uses the existing android-35 google_apis x86_64 image.
$sdk = "C:\Users\zohai\dev\android-sdk"
$avdm = Get-ChildItem "$sdk\cmdline-tools" -Recurse -Filter avdmanager.bat | Select-Object -First 1 -Expand FullName
$name = "accnomos_pixel"
$have = & "$sdk\emulator\emulator.exe" -list-avds 2>$null
if ($have -notcontains $name) {
  "no" | & $avdm create avd -n $name -k "system-images;android-35;google_apis;x86_64" -d "pixel_7" --force | Out-Null
  Add-Content "$env:USERPROFILE\.android\avd\$name.avd\config.ini" "hw.keyboard=yes`nhw.lcd.density=420`nhw.lcd.width=1080`nhw.lcd.height=2400"
  Write-Output "created $name"
}
Start-Process -FilePath "$sdk\emulator\emulator.exe" -ArgumentList "-avd",$name,"-no-snapshot-load","-no-boot-anim","-gpu","swiftshader_indirect","-no-audio","-no-window" -WindowStyle Hidden
Write-Output "booting..."
$adb = "$sdk\platform-tools\adb.exe"
$t = 0
do { Start-Sleep 5; $t += 5; $b = (& $adb shell getprop sys.boot_completed 2>$null) } while ($b -notmatch '1' -and $t -lt 240)
Write-Output "boot_completed=$b after ${t}s"
& $adb devices
