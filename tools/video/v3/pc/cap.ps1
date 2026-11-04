param([string]$shots = "")
# Live web footage on the owner's PC (playwright installed in C:\Users\zohai\dev\video-v2). v3 shots go to the same raw folder as v2's.
Set-Location C:\Users\zohai\dev\video-v2
$env:PW_FROM = "C:\Users\zohai\dev\video-v2"
$env:RECEIPT = "C:\Users\zohai\dev\video-v2\sample-receipt.png"
$env:FAKE_MIC = "C:\Users\zohai\dev\video-v2\u1.wav"
$raw = "C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds\video-v2\raw"
& node tools\v3\capture_live.ts $raw $shots 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath C:\Users\zohai\dev\video-v2\cap3.log -Append
"CAP_EXIT $LASTEXITCODE" | Add-Content C:\Users\zohai\dev\video-v2\cap3.log
