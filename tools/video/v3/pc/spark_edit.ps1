param([string]$only = "")
# Copy footage, art, fonts and edit.py to the Spark and start the edit there (log: ~/video-v2/edit.log).
# The Spark already has ~/video-v2/vo/s1..s8.wav and vo_lines.json (tts.py).
$b = "C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds"
cmd /c C:\Users\zohai\dev\video-v2\sync.cmd | Out-Null
ssh spark "mkdir -p ~/video-v2/raw ~/video-v2/cards ~/video-v2/fonts ~/video-v2/out ~/video-v2/work"
scp -q "$b\video-v2\raw\*" spark:video-v2/raw/
scp -q "$b\video-cards-zaytuna\*.png" spark:video-v2/cards/
scp -q C:\Users\zohai\dev\accnomos\tools\video\fonts\*.ttf spark:video-v2/fonts/
scp -q C:\Users\zohai\dev\video-v2\tools\v2\edit.py spark:video-v2/edit.py
$o = ""; if ($only) { $o = "--only $only" }
ssh spark "cd ~/video-v2 && (setsid nohup python3 edit.py . $o > edit.log 2>&1 < /dev/null &) ; echo started"
