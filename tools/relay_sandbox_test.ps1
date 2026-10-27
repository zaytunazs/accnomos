# Sandbox smoke: create a test organisation (MTD VAT) and check a VRN via the local relay.
$base = "http://127.0.0.1:8787"
$out = "C:\Users\zohai\dev\accnomos\.hmrc-test-user.json"   # git-ignored by .*? -> ensure ignored below
if (Test-Path $out) { $u = Get-Content $out | ConvertFrom-Json; Write-Output ("TEST USER (existing): userId={0} vrn={1}" -f $u.userId, $u.vrn) } else { try {
  $u = Invoke-RestMethod -Method Post -Uri "$base/hmrc/test-user" -ContentType "application/json"
  $u | ConvertTo-Json -Depth 5 | Set-Content $out
  Write-Output ("TEST USER: userId={0} vrn={1} org={2}" -f $u.userId, $u.vrn, $u.organisationDetails.name)
} catch {
  Write-Output "test-user failed: $($_.Exception.Message)"
  if ($_.ErrorDetails) { Write-Output $_.ErrorDetails.Message }
} }
try {
  $c = Invoke-RestMethod -Uri "$base/vat/check/553557881"
  Write-Output ("VRN CHECK: {0}" -f ($c | ConvertTo-Json -Compress -Depth 5))
} catch {
  Write-Output "vrn check failed: $($_.Exception.Message)"
  if ($_.ErrorDetails) { Write-Output $_.ErrorDetails.Message }
}
try {
  $body = @{ client_facts = @{ device_id = "11111111-2222-3333-4444-555555555555"; multi_factor = @(); user_ids = @{ accnomos = "demo-user" }; timezone = "UTC+00:00"; screens = @(@{ width = 1920; height = 1080; scaling_factor = 1; colour_depth = 24 }); window_size = @{ width = 1600; height = 900 }; browser_js_user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36" }; method = "WEB_APP_VIA_SERVER" } | ConvertTo-Json -Depth 6
  $v = Invoke-RestMethod -Method Post -Uri "$base/hmrc/validate-headers" -ContentType "application/json" -Body $body
  Write-Output ("VALIDATE: {0}" -f ($v | ConvertTo-Json -Compress -Depth 6))
} catch {
  Write-Output "validate failed: $($_.Exception.Message)"
  if ($_.ErrorDetails) { Write-Output $_.ErrorDetails.Message }
}
