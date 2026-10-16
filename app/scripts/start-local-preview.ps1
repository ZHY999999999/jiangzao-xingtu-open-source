$ErrorActionPreference = 'Stop'
$appDir = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$vitePath = Join-Path $appDir 'node_modules/vite/bin/vite.js'
$logDir = [IO.Path]::GetFullPath((Join-Path $appDir '../diagnostics/local-preview'))
[IO.Directory]::CreateDirectory($logDir) | Out-Null
$serviceLog = Join-Path $logDir 'service.log'
$mutex = New-Object Threading.Mutex($false, 'Local\ThinkPair.AStock.Preview.5181')
$ownsMutex = $false
$child = $null
function Write-ServiceLog([string]$message) {
    Add-Content -LiteralPath $serviceLog -Encoding UTF8 -Value ((Get-Date -Format o) + ' ' + $message)
}
try {
    try { $ownsMutex = $mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) { exit 0 }
    if (-not (Test-Path -LiteralPath $vitePath -PathType Leaf)) { throw 'Vite entry is missing.' }
    $listener = Get-NetTCPConnection -LocalPort 5181 -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        # Never terminate an unknown process to take over the port.
        Write-ServiceLog ('Port 5181 is already in use; leaving its owner untouched: ' + (($listener.OwningProcess | Select-Object -Unique) -join ','))
        exit 1
    }
    $nodePath = $env:ATLAS_NODE
    if (-not $nodePath) { $nodePath = (Get-Command node.exe -ErrorAction Stop).Source }
    $env:COMPANY_UPDATE_ON_START = '0'
    $env:MARKET_UPDATE_ON_START = '0'
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $stdout = Join-Path $logDir ($stamp + '.out.log')
    $stderr = Join-Path $logDir ($stamp + '.err.log')
    # The everyday preview serves the verified build. Use npm run dev separately
    # for editing; do not run dependency optimization on every preview restart.
    if (-not (Test-Path -LiteralPath (Join-Path $appDir 'dist/index.html') -PathType Leaf)) { throw 'Preview build is missing; use project.ps1 build, validate the candidate, then follow the preview promotion runbook.' }
    $arguments = '"' + $vitePath + '" preview --host 127.0.0.1 --port 5181 --strictPort'
    $child = Start-Process -FilePath $nodePath -ArgumentList $arguments -WorkingDirectory $appDir -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    [ordered]@{pid=$child.Id; supervisorPid=$PID; startedAt=(Get-Date -Format o); url='http://127.0.0.1:5181/'; appDir=$appDir; stdout=$stdout; stderr=$stderr} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logDir 'runtime.json') -Encoding UTF8
    Write-ServiceLog ('Started node PID ' + $child.Id)
    $child.WaitForExit()
    Write-ServiceLog ('Node exited with code ' + $child.ExitCode + '; Task Scheduler may retry.')
    # Any server exit ends availability, even if Vite returns zero.
    exit 1
} catch {
    Write-ServiceLog ('Startup failed: ' + $_.Exception.Message)
    exit 1
} finally {
    if ($child -and -not $child.HasExited) { $child.Kill() }
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
