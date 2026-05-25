param(
    [string]$ApiBase = "http://127.0.0.1:8001"
)

$ErrorActionPreference = "Stop"
$adminHeaders = @{
    "X-User-Role" = "Admin"
    "X-User-Identity" = "demo-admin"
}

Write-Host "Checking platform health..."
Invoke-RestMethod "$ApiBase/health" | Select-Object status, version

Write-Host "Checking auth provider readiness..."
Invoke-RestMethod "$ApiBase/auth/provider-status" | Select-Object auth_mode, production_note

Write-Host "Opening mission overlay sample..."
Invoke-RestMethod "$ApiBase/ai/mission-map-overlay" | Select-Object generated_at, summary

Write-Host "Queueing a notification triage action as Admin..."
Invoke-RestMethod "$ApiBase/notifications/action" `
    -Method Post `
    -Headers $adminHeaders `
    -ContentType "application/json" `
    -Body '{"target":"Demo notification target","action":"investigate","owner":"Demo Admin","priority":"P2","note":"Demo walkthrough triage."}' |
    Select-Object status, target

Write-Host "Deployment hardening summary..."
Invoke-RestMethod "$ApiBase/deployment/hardening" | Select-Object score, status

Write-Host "Demo walkthrough complete."
