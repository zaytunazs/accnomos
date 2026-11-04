# Bring the Spark's finished files to builds\video-v2.
$d = "C:\Users\zohai\Downloads\coworksetup\CoWork\Projects\Meta Hackathon - AI Accounting\builds\video-v2"
ssh spark "tail -5 ~/video-v2/edit.log; ls -la ~/video-v2/out"
scp -q "spark:video-v2/out/*" "$d"
Get-ChildItem $d -File | Select Name, Length
