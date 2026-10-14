param(
    [string]$ProjectId = 'cs528-project-0-508215',
    [string]$Zone = 'us-east1-b'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$gcloudPath = (Get-Command gcloud.cmd).Source
function Invoke-Gcloud {
    param([string[]]$Arguments)
    & $gcloudPath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "gcloud failed: $($Arguments -join ' ')" }
}

$serverIp = (Invoke-Gcloud -Arguments @('compute', 'instances', 'describe', 'hw4-server',
    "--project=$ProjectId", "--zone=$Zone", '--format=value(networkInterfaces[0].networkIP)')).Trim()
if ($serverIp -notmatch '^\d+\.\d+\.\d+\.\d+$') { throw 'No server internal IPv4 address found.' }

# Transfer only the small helper scripts. The provided client must already be uploaded.
Invoke-Gcloud -Arguments @('compute', 'scp', "$PSScriptRoot/monitor.py", 'hw4-server:./monitor.py',
    "--project=$ProjectId", "--zone=$Zone", '--quiet')
Invoke-Gcloud -Arguments @('compute', 'scp', "$PSScriptRoot/monitor.py", "$PSScriptRoot/stress.py",
    'hw4-client:./', "--project=$ProjectId", "--zone=$Zone", '--quiet')

$runId = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
$remoteOut = "evidence/stress-$runId"
$localOut = Join-Path $PSScriptRoot "evidence/stress-$runId"
New-Item -ItemType Directory -Path $localOut | Out-Null
$startAt = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + 60
$serverCommand = "python3 ./monitor.py --start-at $startAt --out $remoteOut"
$clientCommand = "python3 ./stress.py --host $serverIp --start-at $startAt --out $remoteOut"
$jobCode = {
    param($cli, $vm, $project, $zoneName, $command)
    & $cli compute ssh $vm "--project=$project" "--zone=$zoneName" --quiet "--command=$command"
    if ($LASTEXITCODE -ne 0) { throw "$vm experiment command failed." }
}

Start-Transcript -Path (Join-Path $localOut 'run.txt') | Out-Null
$jobs = @()
try {
    Write-Host "Run: $runId; server internal IP: $serverIp"
    Write-Host "Scheduled start (UTC): $([DateTimeOffset]::FromUnixTimeSeconds($startAt).ToString('o'))"
    Write-Host 'Stages: 1, 2, 3, 4 clients; 180 seconds each; 15 seconds recovery between stages.'
    Write-Host 'Keep this terminal open...'
    $jobs += Start-Job -ScriptBlock $jobCode -ArgumentList @($gcloudPath, 'hw4-server', $ProjectId, $Zone, $serverCommand)
    $jobs += Start-Job -ScriptBlock $jobCode -ArgumentList @($gcloudPath, 'hw4-client', $ProjectId, $Zone, $clientCommand)
    while (@($jobs | Where-Object { $_.State -in @('Running', 'NotStarted') }).Count -gt 0) {
        Receive-Job -Job $jobs
        Start-Sleep -Seconds 5
    }
    Receive-Job -Job $jobs
    if (@($jobs | Where-Object { $_.State -ne 'Completed' }).Count -gt 0) {
        throw 'Experiment did not complete; preserve the remote output for diagnosis.'
    }

    foreach ($role in @('server', 'client')) {
        $archive = "evidence/$role-$runId.tar.gz"
        Invoke-Gcloud -Arguments @('compute', 'ssh', "hw4-$role", "--project=$ProjectId",
            "--zone=$Zone", '--quiet', "--command=tar -czf $archive -C $remoteOut .")
        $localArchive = Join-Path $localOut "$role.tar.gz"
        Invoke-Gcloud -Arguments @('compute', 'scp', "hw4-${role}:./$archive", $localArchive,
            "--project=$ProjectId", "--zone=$Zone", '--quiet')
        $extractDir = Join-Path $localOut $role
        New-Item -ItemType Directory -Path $extractDir | Out-Null
        & tar.exe -xzf $localArchive -C $extractDir
        if ($LASTEXITCODE -ne 0) { throw "Cannot extract $localArchive" }
    }
    Write-Host "Evidence saved to: $localOut"
    Write-Host 'Completed.'
} finally {
    Stop-Transcript | Out-Null
    foreach ($job in $jobs) {
        if ($job.State -in @('Completed', 'Failed', 'Stopped')) { Remove-Job -Job $job }
    }
}
