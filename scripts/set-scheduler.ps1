param([Parameter(Mandatory=$true)][ValidateSet('mock-docker','local-gpu-docker')][string]$Mode)
. "$PSScriptRoot\common.ps1"
$values = Read-LabEnv
$web = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$url = "http://localhost:$($values.PORTAL_PORT)"
Invoke-RestMethod -Uri "$url/api/auth/login" -Method Post -ContentType 'application/json' -Body (@{username=$values.INITIAL_ADMIN_USERNAME;password=$values.INITIAL_ADMIN_PASSWORD}|ConvertTo-Json) -WebSession $web | Out-Null
$queue = Invoke-RestMethod -Uri "$url/api/resources/queue" -WebSession $web
if ($queue.Count) { throw 'Cancel/finish all pending/running/debug workloads before switching scheduler mode.' }
if ($Mode -eq 'local-gpu-docker') { & "$PSScriptRoot\gpu-test.ps1" }
Set-LabEnv @{SCHEDULER_BACKEND=$Mode}
Invoke-LabDocker compose up -d --no-build --pull never --force-recreate backend scheduler-worker --wait --wait-timeout 180
Write-Host "Scheduler changed to $Mode. GPU count is controlled by MOCK_GPU_COUNT / LOCAL_GPU_COUNT in .env."
