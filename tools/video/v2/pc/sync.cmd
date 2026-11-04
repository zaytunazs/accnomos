@echo off
rem Fetch the capture/edit scripts from the branch without touching the working tree of C:\Users\zohai\dev\accnomos.
cd /d C:\Users\zohai\dev\accnomos
git fetch -q origin claude/video-v2
git show origin/claude/video-v2:tools/video/v2/capture_live.ts > C:\Users\zohai\dev\video-v2\tools\v2\capture_live.ts
git show origin/claude/video-v2:tools/video/lib/human.ts > C:\Users\zohai\dev\video-v2\tools\lib\human.ts
git show origin/claude/video-v2:tools/video/lib/recorder.ts > C:\Users\zohai\dev\video-v2\tools\lib\recorder.ts
git show origin/claude/video-v2:tools/video/v2/edit.py > C:\Users\zohai\dev\video-v2\tools\v2\edit.py
echo SYNCED
