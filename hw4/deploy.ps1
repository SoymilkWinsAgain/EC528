param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z][a-z0-9-]{4,28}[a-z0-9]$')]
    [string]$ProjectId,
    [string]$BucketName = 'ec528hw2',
    [string]$Region = 'us-east1',
    [string]$Zone = 'us-east1-b',
    [string]$ServerServiceAccount = '',
    [string]$ReporterServiceAccount = '',
    [string]$TopicId = 'hw4-forbidden-requests',
    [string]$SubscriptionId = 'hw4-forbidden-requests-sub',
    [switch]$Plan
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $Zone.StartsWith("$Region-")) {
    throw 'Zone must belong to Region.'
}
if (-not $ServerServiceAccount) {
    $ServerServiceAccount = "hw4-server@$ProjectId.iam.gserviceaccount.com"
}
if (-not $ReporterServiceAccount) {
    $ReporterServiceAccount = "hw4-reporter@$ProjectId.iam.gserviceaccount.com"
}

# Metadata configuration is an environment file, not a shell script.
foreach ($value in @($ProjectId, $BucketName, $TopicId, $SubscriptionId)) {
    if ($value -notmatch '^[a-zA-Z0-9._-]+$') {
        throw "Unsupported configuration value: $value"
    }
}
$gcloudPath = (Get-Command gcloud.cmd -ErrorAction SilentlyContinue).Source
if (-not $gcloudPath) { $gcloudPath = (Get-Command gcloud).Source }

function Invoke-Gcloud {
    param([string[]]$Arguments)
    & $gcloudPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "gcloud failed: $($Arguments -join ' ')"
    }
}

function Resource-Exists {
    param([string[]]$Arguments)
    $result = Invoke-Gcloud -Arguments $Arguments
    return -not [string]::IsNullOrWhiteSpace(($result -join ''))
}

function Create-Resource {
    param([string[]]$Arguments)
    if ($Plan) {
        Write-Host ('PLAN: gcloud ' + (($Arguments | ForEach-Object { '"' + $_ + '"' }) -join ' '))
    } else {
        Invoke-Gcloud -Arguments $Arguments
    }
}

function Write-Utf8LF {
    param([string]$Path, [string]$Content)
    $normalized = $Content.TrimStart([char]0xFEFF).Replace("`r`n", "`n")
    [System.IO.File]::WriteAllText($Path, $normalized, [System.Text.UTF8Encoding]::new($false))
}

$startupPath = Join-Path $PSScriptRoot 'startup.sh'
foreach ($path in @($startupPath, "$PSScriptRoot/service1/main.py",
        "$PSScriptRoot/service1/requirements.txt", "$PSScriptRoot/service2/main.py",
        "$PSScriptRoot/service2/requirements.txt")) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing source file: $path"
    }
}

# Capture deployment commands and times for the homework report.
$evidenceDir = Join-Path $PSScriptRoot 'evidence'
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$transcriptPath = Join-Path $evidenceDir "deploy-$stamp.txt"
$stageDir = Join-Path ([System.IO.Path]::GetTempPath()) ('ec528-hw4-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $stageDir | Out-Null
$stagedFiles = @()
Start-Transcript -Path $transcriptPath | Out-Null

try {
    Write-Host "Project: $ProjectId; zone: $Zone; plan only: $Plan"
    Write-Host "Started (UTC): $([DateTime]::UtcNow.ToString('o'))"
    $envText = @"
PROJECT_ID=$ProjectId
BUCKET_NAME=$BucketName
TOPIC_ID=$TopicId
SUBSCRIPTION_ID=$SubscriptionId
PORT=8080
"@
    foreach ($item in @(
        @{ Name = 'startup.sh'; Content = [IO.File]::ReadAllText($startupPath) },
        @{ Name = 'app.env'; Content = $envText }
    )) {
        $target = Join-Path $stageDir $item.Name
        $stagedFiles += $target
        Write-Utf8LF -Path $target -Content $item.Content
    }

    if (-not (Resource-Exists -Arguments @('compute', 'addresses', 'list',
            "--project=$ProjectId", "--regions=$Region", '--filter=name=hw4-server-ip', '--format=value(name)'))) {
        Create-Resource -Arguments @('compute', 'addresses', 'create', 'hw4-server-ip',
            "--project=$ProjectId", "--region=$Region", '--network-tier=PREMIUM')
    } else { Write-Host 'Existing static IP: hw4-server-ip' }

    if (-not (Resource-Exists -Arguments @('compute', 'firewall-rules', 'list',
            "--project=$ProjectId", '--filter=name=hw4-allow-http', '--format=value(name)'))) {
        Create-Resource -Arguments @('compute', 'firewall-rules', 'create', 'hw4-allow-http',
            "--project=$ProjectId", '--network=default', '--direction=INGRESS',
            '--allow=tcp:8080', '--source-ranges=0.0.0.0/0', '--target-tags=hw4-server')
    } else { Write-Host 'Existing firewall rule: hw4-allow-http' }

    foreach ($vm in @(
        @{ Name = 'hw4-server'; Source = 'service1'; Account = $ServerServiceAccount; Role = 'server' },
        @{ Name = 'hw4-reporter'; Source = 'service2'; Account = $ReporterServiceAccount; Role = 'reporter' }
    )) {
        if (Resource-Exists -Arguments @('compute', 'instances', 'list', "--project=$ProjectId",
                "--zones=$Zone", "--filter=name=$($vm.Name)", '--format=value(name)')) {
            Write-Host "Existing VM: $($vm.Name); skipping creation. Existing VMs are not updated."
            continue
        }
        $codePath = Join-Path $stageDir "$($vm.Source)-main.py"
        $reqPath = Join-Path $stageDir "$($vm.Source)-requirements.txt"
        $stagedFiles += @($codePath, $reqPath)
        Write-Utf8LF -Path $codePath -Content ([IO.File]::ReadAllText("$PSScriptRoot/$($vm.Source)/main.py"))
        Write-Utf8LF -Path $reqPath -Content ([IO.File]::ReadAllText("$PSScriptRoot/$($vm.Source)/requirements.txt"))
        $metadataFiles = "startup-script=$stageDir/startup.sh,app-code=$codePath,app-requirements=$reqPath,app-env=$stageDir/app.env"
        $createArgs = @('compute', 'instances', 'create', $vm.Name, "--project=$ProjectId",
            "--zone=$Zone", '--machine-type=f1-micro', '--network=default',
            '--image-family=debian-12', '--image-project=debian-cloud',
            '--boot-disk-type=pd-standard', '--boot-disk-size=10GB',
            "--service-account=$($vm.Account)", '--scopes=cloud-platform',
            "--labels=assignment=ec528-hw4,role=$($vm.Role)", "--metadata-from-file=$metadataFiles")
        if ($vm.Role -eq 'server') {
            $createArgs += @('--address=hw4-server-ip', '--tags=hw4-server')
        }
        Create-Resource -Arguments $createArgs
    }

    if (-not $Plan) {
        Invoke-Gcloud -Arguments @('compute', 'instances', 'list', "--project=$ProjectId",
            '--filter=labels.assignment=ec528-hw4',
            '--format=table(name,zone.basename(),status,networkInterfaces[0].accessConfigs[0].natIP)')
        $ip = Invoke-Gcloud -Arguments @('compute', 'addresses', 'describe', 'hw4-server-ip',
            "--project=$ProjectId", "--region=$Region", '--format=value(address)')
        Write-Host "Test URL: http://${ip}:8080/pages/0.html"
        Write-Host 'RUNNING means the VM is running; Python dependency installation may still be in progress.'
    }
    Write-Host "Finished (UTC): $([DateTime]::UtcNow.ToString('o'))"
} finally {
    Stop-Transcript | Out-Null
    # Delete only the explicitly created temporary files; no recursive deletion.
    foreach ($file in $stagedFiles) { Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $stageDir -ErrorAction SilentlyContinue
}
