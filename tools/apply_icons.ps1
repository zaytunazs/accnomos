# Copies the generated launcher icons into the Android res folders and the web favicon/brand.
$src = "C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds\listing"
$res = "C:\Users\zohai\dev\accnomos\apps\mobile\android\app\src\main\res"
foreach ($d in "mdpi","hdpi","xhdpi","xxhdpi","xxxhdpi") {
  Copy-Item "$src\mipmap-$d\ic_launcher.png" "$res\mipmap-$d\ic_launcher.png" -Force
}
New-Item -ItemType Directory -Force "C:\Users\zohai\dev\accnomos\apps\web\public\brand" | Out-Null
Copy-Item "$src\icon.svg" "C:\Users\zohai\dev\accnomos\apps\web\public\brand\icon.svg" -Force
Copy-Item "$src\play-icon-512.png" "C:\Users\zohai\dev\accnomos\apps\web\public\brand\icon-512.png" -Force
Copy-Item "$src\feature.png" "C:\Users\zohai\dev\accnomos\apps\web\public\brand\feature-1024x500.png" -Force
git -C C:\Users\zohai\dev\accnomos status --short
