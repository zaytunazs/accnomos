$sdk = $env:ANDROID_HOME; if (-not $sdk) { $sdk = $env:ANDROID_SDK_ROOT }; if (-not $sdk) { $sdk = "$env:LOCALAPPDATA\Android\Sdk" }
Write-Output "SDK: $sdk"
Get-ChildItem "$sdk\system-images" -Recurse -Directory -ErrorAction SilentlyContinue | Where-Object { $_.FullName -match 'x86_64$|arm64-v8a$' } | Select -Expand FullName
Write-Output "--- avds:"
Get-ChildItem "$env:USERPROFILE\.android\avd" -Filter *.ini -ErrorAction SilentlyContinue | Select -Expand Name
& "$sdk\emulator\emulator.exe" -list-avds 2>$null
Write-Output "--- adb devices:"
& "$sdk\platform-tools\adb.exe" devices
Write-Output "--- cmdline-tools:"
Get-ChildItem "$sdk\cmdline-tools" -ErrorAction SilentlyContinue | Select -Expand Name
