param([switch]$Remote, [switch]$NoBuild)
. "$PSScriptRoot\common.ps1"
if (!(Test-Path -LiteralPath '.env')) { & "$PSScriptRoot\bootstrap.ps1" }
$values = Read-LabEnv
if (!$NoBuild) {
    Invoke-LabDocker build --pull=false --build-arg "LOCAL_CUDA_IMAGE=$($values.LOCAL_CUDA_IMAGE)" -t $values.LAB_BASE_IMAGE -f images/lab-base-dev/Dockerfile .
    Invoke-LabDocker compose build --pull=false
}
$composeArgs = @('compose')
if ($Remote) {
    Invoke-LabDocker image inspect $values.CLOUDFLARED_IMAGE --format '{{.Id}}'
    $composeArgs += @('--profile','remote')
}
$composeArgs += @('up','-d','--no-build','--pull','never','--wait','--wait-timeout','180')
Invoke-LabDocker @composeArgs
Write-Host "Portal: http://localhost:$($values.PORTAL_PORT)"
Write-Host "Admin username: $($values.INITIAL_ADMIN_USERNAME). Read INITIAL_ADMIN_PASSWORD in .env."
if ($Remote) {
    $until = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $remoteUrl = Get-LabRemoteUrl
        if ($remoteUrl) { break }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $until)
    if ($remoteUrl) {
        Write-Host "Remote portal: $remoteUrl"
        Write-Host 'Keep this PC and Docker Desktop running. Tunnel restart changes this temporary URL.'
    } else {
        Write-Warning 'Tunnel is still connecting. Check scripts/remote-access.ps1 or the Remote Access page.'
    }
}
