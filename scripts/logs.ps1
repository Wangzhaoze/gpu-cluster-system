param([string]$Service)
. "$PSScriptRoot\common.ps1"
if ($Service) { Invoke-LabDocker compose logs -f --tail 100 $Service }
else { Invoke-LabDocker compose logs -f --tail 100 backend scheduler-worker traefik }
