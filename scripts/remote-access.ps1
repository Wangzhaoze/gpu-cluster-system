param([ValidateSet('Start', 'Status', 'Stop')][string]$Action = 'Status')
. "$PSScriptRoot\common.ps1"
if ($Action -eq 'Start') {
    & "$PSScriptRoot\up.ps1" -Remote -NoBuild
    return
}
if ($Action -eq 'Stop') {
    Invoke-LabDocker compose --profile remote stop cloudflared
    Write-Host 'Remote tunnel stopped. The local portal and workloads are still running.'
    return
}
$remoteUrl = Get-LabRemoteUrl
if (!$remoteUrl) {
    Write-Host 'Remote tunnel is stopped or still connecting. Start with: .\scripts\remote-access.ps1 -Action Start'
    return
}
Write-Host "Remote portal: $remoteUrl"
try {
    $health = Invoke-RestMethod -Uri "$remoteUrl/api/health" -TimeoutSec 15
    if ($health.status -eq 'ok') { Write-Host 'Public HTTPS health check: OK' }
    else { Write-Warning 'Public service returned an unexpected health response.' }
} catch {
    Write-Warning 'The tunnel has connected, but its public URL is not reachable from this PC yet. Check again shortly.'
}
