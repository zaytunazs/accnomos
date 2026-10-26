# Creates the Google Play upload keystore for Accnomos. Run this yourself (it prompts for a password).
# Output: apps\mobile\android\upload-keystore.jks + apps\mobile\android\key.properties (both git-ignored).
# Keep the password in your password manager. Play App Signing holds the real release key; this key only uploads.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$android = Join-Path $root 'apps\mobile\android'
$ks = Join-Path $android 'upload-keystore.jks'
if (Test-Path $ks) { Write-Host "Keystore already exists: $ks"; exit 0 }
$keytool = Join-Path $env:JAVA_HOME 'bin\keytool.exe'
if (-not (Test-Path $keytool)) { $keytool = 'keytool' }
$pw = Read-Host -AsSecureString 'Choose the upload-key password (min 6 chars)'
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw))
& $keytool -genkeypair -v -keystore $ks -alias upload -keyalg RSA -keysize 2048 -validity 10000 `
  -storepass $plain -keypass $plain -dname 'CN=Accnomos, O=Zaytuna Business Services Ltd, L=London, C=GB'
@"
storeFile=upload-keystore.jks
storePassword=$plain
keyPassword=$plain
keyAlias=upload
"@ | Set-Content (Join-Path $android 'key.properties') -NoNewline
Write-Host "Done. Now: cd apps\mobile; flutter build appbundle --release  ->  build\app\outputs\bundle\release\app-release.aab"
