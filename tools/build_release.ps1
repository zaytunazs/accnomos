# usage: build_release.ps1 -Tag 0.2.0-2  — analyzes, builds the signed AAB, copies it to builds/ (bump pubspec version first)
param([Parameter(Mandatory=$true)][string]$Tag)
Set-Location C:\Users\zohai\dev\accnomos\apps\mobile
flutter analyze 2>&1 | Select-Object -Last 2
flutter build appbundle --release 2>&1 | Select-Object -Last 2
$dst = "C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds\accnomos-$Tag.aab"
Copy-Item build\app\outputs\bundle\release\app-release.aab $dst -Force
Write-Output "AAB: $dst $((Get-Item $dst).Length) bytes"
