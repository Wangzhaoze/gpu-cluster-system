param([switch]$Force)
. "$PSScriptRoot\common.ps1"
if (!$Force -and (Read-Host 'Delete THIS PROJECT database, user files, results and Python volumes? Type RESET') -ne 'RESET') { return }
$target = [IO.Path]::GetFullPath((Join-Path $LabRoot 'runtime'))
$expected = [IO.Path]::GetFullPath($LabRoot).TrimEnd('\') + '\runtime'
if ($target -ne $expected) { throw 'Refusing reset outside project runtime.' }
$containers = @(& docker ps -aq --filter 'label=lab.managed=true' --filter 'label=lab.project=gpu-lab-poc')
if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate containers.' }
if ($containers.Count) { Invoke-LabDocker rm -f @containers }
Invoke-LabDocker compose --profile remote down --volumes
$volumes = @(& docker volume ls -q --filter 'label=lab.managed=true' --filter 'label=lab.project=gpu-lab-poc')
if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate volumes.' }
if ($volumes.Count) { Invoke-LabDocker volume rm @volumes }
if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
Write-Host 'Project runtime reset. External datasets and other Docker projects were not touched.'
