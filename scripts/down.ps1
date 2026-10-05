. "$PSScriptRoot\common.ps1"
# Stop only this project's dynamic containers; keep named venvs and all host data.
$containers = @(& docker ps -q --filter 'label=lab.managed=true' --filter 'label=lab.project=gpu-lab-poc')
if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate managed containers.' }
if ($containers.Count -gt 0) { Invoke-LabDocker stop @containers }
Invoke-LabDocker compose --profile remote down
Write-Host 'Stopped. Persistent files, Python environments, results and database retained.'
