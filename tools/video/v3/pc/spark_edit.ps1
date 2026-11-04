param([string]$only = "")
# Copy new footage and the v3 edit to the Spark and start the edit there (log: ~/video-v3/edit.log).
# ~/video-v3 links raw/, cards/ and fonts/ to ~/video-v2; the voice is in ~/video-v3/vo (tts.py, bm_lewis).
$b = "C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds"
cmd /c C:\Users\zohai\dev\video-v2\sync3.cmd | Out-Null
scp -q "$b\video-v2\raw\*" spark:video-v2/raw/
scp -q C:\Users\zohai\dev\video-v2\tools\v3\edit.py spark:video-v3/edit.py
$o = ""; if ($only) { $o = "--only $only" }
ssh spark "cd ~/video-v3 && (setsid nohup python3 edit.py . $o > edit.log 2>&1 < /dev/null &) ; echo started"
