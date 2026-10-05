. "$PSScriptRoot\common.ps1"
$remoteUrl = Get-LabRemoteUrl
if (!$remoteUrl) { throw 'Start the tunnel first: .\scripts\remote-access.ps1 -Action Start' }
Invoke-LabDocker compose exec -T backend python3 integration/remote_acceptance.py --url $remoteUrl
