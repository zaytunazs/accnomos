param([string]$shots = "")
# Live web footage on the owner's PC (playwright 1.64.1 installed in C:\Users\zohai\dev\video-v2, package type module).
Set-Location C:\Users\zohai\dev\video-v2
$env:PW_FROM = "C:\Users\zohai\dev\video-v2"
$env:RECEIPT = "C:\Users\zohai\dev\video-v2\sample-receipt.png"
$env:FAKE_MIC = "C:\Users\zohai\dev\video-v2\u1.wav"   # "Add a site visit tomorrow at ten." (tts.py, bf_emma)
$raw = "C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds\video-v2\raw"
& node tools\v2\capture_live.ts $raw $shots 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath C:\Users\zohai\dev\video-v2\cap.log -Append
"CAP_EXIT $LASTEXITCODE" | Add-Content C:\Users\zohai\dev\video-v2\cap.log
