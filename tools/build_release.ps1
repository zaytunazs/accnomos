# usage: build_release.ps1 -Tag 0.3.1-4  — analyzes, builds the signed AAB, copies it to builds/ (bump pubspec version first)
#
# Play re-signs the bundle with Google's app signing key, so the MSAL redirect URI on a Play install
# (msauth://com.accnomos.app/<hash>) uses THAT key's hash, not the upload key's or the debug key's.
# Play Console → Test and release → App integrity → Play app signing → App signing key certificate → SHA-1
# 54:C9:BB:EE:D0:00:0D:EF:3F:51:9C:56:22:FA:9F:46:63:22:42:B0  →  base64 of the 20 bytes below.
# A certificate fingerprint is public (it is in every installed APK), so it can live in the repo.
param(
  [Parameter(Mandatory = $true)][string]$Tag,
  [string]$MsalSigHash = "VMm77tAADe8/UZxWIvqfRmMiQrA="
)
Set-Location C:\Users\zohai\dev\accnomos\apps\mobile
flutter analyze 2>&1 | Select-Object -Last 2
$out = "build\app\outputs\bundle\release\app-release.aab"
Remove-Item $out -ErrorAction SilentlyContinue  # never copy a bundle left over from an earlier build
flutter build appbundle --release "-PmsalSignatureHash=$MsalSigHash" "--dart-define=MSAL_SIG_HASH=$MsalSigHash" 2>&1 | Select-Object -Last 2
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $out)) { Write-Output "BUILD FAILED: nothing copied"; exit 1 }
$dst = "C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds\accnomos-$Tag.aab"
Copy-Item $out $dst -Force
Write-Output "AAB: $dst $((Get-Item $dst).Length) bytes (MSAL hash $MsalSigHash)"
