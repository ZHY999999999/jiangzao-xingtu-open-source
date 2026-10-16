$ErrorActionPreference = 'Stop'
$url = 'http://127.0.0.1:5181/#kind=concept'
try {
    Start-ScheduledTask -TaskName 'ThinkPair-AStock-LocalPreview'
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri 'http://127.0.0.1:5181/' -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200 -and $response.Content -match 'A股知识库') {
                Start-Process $url
                exit 0
            }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw '预览未能启动，请检查 diagnostics/local-preview 内的启动日志。'
} catch {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($_.Exception.Message, 'A股知识库本地预览') | Out-Null
    exit 1
}
