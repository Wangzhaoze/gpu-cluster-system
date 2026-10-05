param([switch]$Gpu)
. "$PSScriptRoot\common.ps1"
Invoke-LabDocker compose exec -T backend python3 -m pytest -q
if ($Gpu) { Invoke-LabDocker compose run --rm --no-deps -T --entrypoint python3 backend integration/acceptance.py --gpu }
else { Invoke-LabDocker compose run --rm --no-deps -T --entrypoint python3 backend integration/acceptance.py }
