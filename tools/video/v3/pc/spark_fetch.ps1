# Bring the Spark's finished v3 files to builds\video-v2 (next to v2's).
$d = "C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds\video-v2"
ssh spark "tail -2 ~/video-v3/edit.log; ls -la ~/video-v3/out"
scp -q "spark:video-v3/out/accnomos-demo-v3*" "$d"
scp -q "spark:video-v3/out/timeline.json" "$d\accnomos-demo-v3-timeline.json"
Get-ChildItem "$d\accnomos-demo-v3*" | Select Name, Length
