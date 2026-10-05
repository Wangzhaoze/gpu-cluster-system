. "$PSScriptRoot\common.ps1"
$values = Read-LabEnv
Invoke-LabDocker run --rm --pull never --gpus all --entrypoint nvidia-smi $values.LAB_BASE_IMAGE '--query-gpu=index,name,memory.total' --format=csv
Write-Host 'Use .\scripts\set-scheduler.ps1 -Mode local-gpu-docker to test the real GPU through the Portal.'
