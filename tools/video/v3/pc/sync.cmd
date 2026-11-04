@echo off
rem Fetch the v3 capture/edit scripts from the branch without touching the working tree of C:\Users\zohai\dev\accnomos.
cd /d C:\Users\zohai\dev\accnomos
git fetch -q origin claude/video-v3
if not exist C:\Users\zohai\dev\video-v2\tools\v3 mkdir C:\Users\zohai\dev\video-v2\tools\v3
git show origin/claude/video-v3:tools/video/v3/capture_live.ts > C:\Users\zohai\dev\video-v2\tools\v3\capture_live.ts
git show origin/claude/video-v3:tools/video/lib/human.ts > C:\Users\zohai\dev\video-v2\tools\lib\human.ts
git show origin/claude/video-v3:tools/video/lib/recorder.ts > C:\Users\zohai\dev\video-v2\tools\lib\recorder.ts
git show origin/claude/video-v3:tools/video/v3/edit.py > C:\Users\zohai\dev\video-v2\tools\v3\edit.py
git show origin/claude/video-v3:tools/video/v3/tts.py > C:\Users\zohai\dev\video-v2\tools\v3\tts.py
git show origin/claude/video-v3:tools/video/v3/vo_lines.json > C:\Users\zohai\dev\video-v2\tools\v3\vo_lines.json
echo SYNCED
