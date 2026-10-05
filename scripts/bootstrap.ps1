param([string]$DatasetPath)
. "$PSScriptRoot\common.ps1"
Invoke-LabDocker version --format '{{.Server.Os}}'
Invoke-LabDocker compose version
$engineOS = & docker info --format '{{.OSType}}'
if ($engineOS -ne 'linux') { throw 'Docker Desktop must use Linux containers.' }
$cudaId = 'sha256:17e2934e1fa96152b14f78078bfbafd0f00f391df995dc6c641a720fce1202bb'
$nodeId = 'sha256:2d53098834d80fac0af3a3ed330dc81a0cb68d9cc68329386102c128243c5320'
Invoke-LabDocker image inspect $cudaId --format '{{.Id}}'
Invoke-LabDocker tag $cudaId lab-local-cuda:12.8.1
Invoke-LabDocker image inspect $nodeId --format '{{.Id}}'
Invoke-LabDocker tag $nodeId lab-local-node:20.20.2
if (!(Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
$runtimePath = Join-Path $LabRoot 'runtime'
foreach ($relative in @('users','datasets\demo','results','scratch','logs\jobs')) {
    New-Item -ItemType Directory -Path (Join-Path $runtimePath $relative) -Force | Out-Null
}
[IO.File]::WriteAllText((Join-Path $runtimePath 'datasets\demo\hello.txt'), "GPU Lab demo dataset`n", [Text.UTF8Encoding]::new($false))
$values = Read-LabEnv
$changes = @{}
foreach ($key in @('POSTGRES_PASSWORD','INITIAL_ADMIN_PASSWORD','SESSION_SECRET')) {
    if ($values[$key] -eq 'GENERATE_WITH_BOOTSTRAP') { $changes[$key] = New-LabSecret }
}
$changes['LAB_HOST_ROOT'] = $runtimePath.Replace('\','/')
if ($DatasetPath) {
    $resolved = (Resolve-Path -LiteralPath $DatasetPath).Path
    if (!(Test-Path -LiteralPath $resolved -PathType Container)) { throw 'DatasetPath must be an existing directory.' }
    $changes['DATASET_HOST_PATH'] = $resolved.Replace('\','/')
} elseif ($values['DATASET_HOST_PATH'] -eq 'SET_WITH_BOOTSTRAP') {
    $changes['DATASET_HOST_PATH'] = (Join-Path $runtimePath 'datasets').Replace('\','/')
}
Set-LabEnv $changes
# Pin the already installed Cloudflare image to its content ID; never fetch latest.
$cloudId = & docker image inspect cloudflare/cloudflared:latest --format '{{.Id}}' 2>$null
if ($LASTEXITCODE -eq 0) { Set-LabEnv @{CLOUDFLARED_IMAGE=$cloudId} }
Write-Host 'Bootstrap complete. Credentials are in .env (not printed or committed).'
Write-Host 'Next: .\scripts\up.ps1'
