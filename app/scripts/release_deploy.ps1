[CmdletBinding()]
param(
    [ValidateSet('Plan', 'Stage', 'Inspect', 'SelfTest', 'Activate', 'Verify', 'Rollback')]
    [string]$Action = 'Plan',
    [Parameter(Mandatory = $true)][string]$Report,
    [string]$Server = $env:ATLAS_DEPLOY_SERVER,
    [string]$IdentityFile = $env:ATLAS_DEPLOY_IDENTITY,
    [ValidateRange(1073741824, 1099511627776)][long]$ReserveBytes = 1073741824,
    [ValidateRange(1073741824, 1099511627776)][long]$OperationalBytes = 6442450944,
    [ValidateRange(1, 2147483647)][int]$InodeReserve = 1024,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
if ($OperationalBytes -lt $ReserveBytes) { throw 'OperationalBytes must be >= ReserveBytes' }
$reportPath = (Resolve-Path -LiteralPath $Report).Path
$metadata = Get-Content -LiteralPath $reportPath -Raw -Encoding utf8 | ConvertFrom-Json
$releaseId = [string]$metadata.releaseId
if ($releaseId -notmatch '^[0-9]{8}T[0-9]{12}Z-[a-f0-9]{12}$') { throw 'Invalid release id' }
if ($Server -notmatch '^[a-zA-Z0-9.-]+$') { throw 'Invalid SSH host' }
$digest = [string]$metadata.archiveSha256
if ($digest -notmatch '^[a-f0-9]{64}$') { throw 'Invalid archive hash' }
$archivePath = (Resolve-Path -LiteralPath $metadata.archive).Path
# Use .NET directly so this also works in minimal Windows PowerShell hosts.
$archiveStream = [IO.File]::OpenRead($archivePath)
$archiveHasher = [Security.Cryptography.SHA256]::Create()
try { $localArchiveHash = [BitConverter]::ToString($archiveHasher.ComputeHash($archiveStream)).Replace('-', '').ToLowerInvariant() }
finally { $archiveStream.Dispose(); $archiveHasher.Dispose() }
if ($localArchiveHash -ne $digest) { throw 'Local archive differs from report' }
$destination = 'root@' + $Server
$remoteDir = '/var/tmp/a-share-atlas-release/' + $releaseId
$remoteArchive = $remoteDir + '/' + $releaseId + '.tar.gz'
$remoteScript = $remoteDir + '/release_remote.py'
$sshOptions = @('-i', $IdentityFile, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15')

function Invoke-SiteSsh([string]$Command) {
    & ssh @sshOptions $destination $Command
    if ($LASTEXITCODE -ne 0) { throw "SSH command failed ($LASTEXITCODE): $Command" }
}

if ($Action -eq 'Plan') {
    [pscustomobject]@{
        action = 'Plan only; no network connection'
        releaseId = $releaseId
        archive = $archivePath
        archiveSha256 = $digest
        companies = $metadata.companyCount
        reserveBytes = $ReserveBytes
        operationalWarningBytes = $OperationalBytes
        inodeReserve = $InodeReserve
        uploadDirectory = $remoteDir
        stageCommand = "python3 $remoteScript stage --archive $remoteArchive --sha256 $digest --release-id $releaseId --reserve-bytes $ReserveBytes --operational-bytes $OperationalBytes --inode-reserve $InodeReserve"
        activateCommand = "python3 $remoteScript activate --release-id $releaseId"
        rollbackCommand = "python3 $remoteScript rollback --release-id $releaseId"
    } | ConvertTo-Json
    exit 0
}
if ($Action -eq 'Stage') {
    $capacityScript = Join-Path $PSScriptRoot 'release_capacity.py'
    $requirementsJson = & $Python $capacityScript $archivePath
    if ($LASTEXITCODE -ne 0) { throw 'Local archive capacity inventory failed' }
    $requirements = $requirementsJson | ConvertFrom-Json
    # Send the read-only helper as command text: no remote upload/mkdir precedes this check.
    # Only base64 and validated numeric fields enter the remote shell command.
    $capacityBase64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($capacityScript))
    $archiveBytes = [long]$requirements.archiveBytes
    $payloadBytes = [long]$requirements.payloadBytes
    $fileCount = [long]$requirements.fileCount
    $directoryCount = [long]$requirements.directoryCount
    $capacityCommand = "import base64,json;scope={'__name__':'release_capacity_check'};exec(base64.b64decode('$capacityBase64'),scope);print(json.dumps(scope['upload_preflight']($archiveBytes,$payloadBytes,$fileCount,$directoryCount,$ReserveBytes,$OperationalBytes,$InodeReserve)))"
    Invoke-SiteSsh ('python3 -c "' + $capacityCommand + '"')
    # Only a unique task-owned incoming directory is created. No site data changes.
    Invoke-SiteSsh "umask 022 && mkdir -p /var/tmp/a-share-atlas-release && mkdir $remoteDir"
    $uploads = @($archivePath, (Join-Path $PSScriptRoot 'release_remote.py'), (Join-Path $PSScriptRoot 'release_common.py'), $capacityScript)
    foreach ($upload in $uploads) {
        & scp @sshOptions $upload ($destination + ':' + $remoteDir + '/')
        if ($LASTEXITCODE -ne 0) { throw "Upload failed ($LASTEXITCODE): $upload" }
    }
    Invoke-SiteSsh "python3 $remoteScript stage --archive $remoteArchive --sha256 $digest --release-id $releaseId --reserve-bytes $ReserveBytes --operational-bytes $OperationalBytes --inode-reserve $InodeReserve"
} elseif ($Action -eq 'Inspect' -or $Action -eq 'SelfTest') {
    $remoteAction = $Action.ToLowerInvariant()
    Invoke-SiteSsh "python3 $remoteScript $remoteAction"
} else {
    $remoteAction = $Action.ToLowerInvariant()
    Invoke-SiteSsh "python3 $remoteScript $remoteAction --release-id $releaseId"
}
