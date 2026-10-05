$ErrorActionPreference = 'Stop'
$LabRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $LabRoot

function Invoke-LabDocker {
    # A plain function preserves native CLI flags such as -d instead of binding
    # them as abbreviations of PowerShell function parameters.
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed (exit $LASTEXITCODE)" }
}

function Read-LabEnv {
    $values = @{}
    foreach ($line in Get-Content -LiteralPath (Join-Path $LabRoot '.env')) {
        if ($line -match '^([A-Z0-9_]+)=(.*)$') { $values[$Matches[1]] = $Matches[2] }
    }
    return $values
}

function Set-LabEnv {
    param([hashtable]$Values)
    $lines = foreach ($line in Get-Content -LiteralPath (Join-Path $LabRoot '.env')) {
        if ($line -match '^([A-Z0-9_]+)=') {
            $key = $Matches[1]
            if ($Values.ContainsKey($key)) { "$key=$($Values[$key])" } else { $line }
        } else { $line }
    }
    [IO.File]::WriteAllLines((Join-Path $LabRoot '.env'), $lines, [Text.UTF8Encoding]::new($false))
}

function New-LabSecret {
    $bytes = New-Object byte[] 24
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
}

function Get-LabRemoteUrl {
    $containerId = & docker compose --profile remote ps -q cloudflared
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect remote tunnel' }
    if (!$containerId) { return $null }
    $started = & docker inspect --format '{{.State.StartedAt}}' $containerId
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect remote tunnel start time' }
    $content = (& docker logs --since $started $containerId 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read remote tunnel logs' }
    $links = [regex]::Matches($content, 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($links.Count -gt 0 -and $content.Contains('Registered tunnel connection')) {
        return $links[$links.Count - 1].Value
    }
    return $null
}
