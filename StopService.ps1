$ErrorActionPreference = 'Stop'
$hash = [Security.Cryptography.SHA256]::Create()
try {
    $bytes = [Text.Encoding]::UTF8.GetBytes($PSScriptRoot.ToLowerInvariant())
    $workspace = ([BitConverter]::ToString($hash.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant().Substring(0, 20)
} finally { $hash.Dispose() }
$stopped = $false
foreach ($port in 8765..8799) {
    $url = "http://127.0.0.1:$port"
    try { $identity = Invoke-RestMethod "$url/api/client" -TimeoutSec 1 } catch { continue }
    if ($identity.workspace -ne $workspace) { continue }
    $state = Invoke-RestMethod "$url/api/status" -TimeoutSec 2
    if ($state.active_jobs -gt 0 -or ($state.jobs | Where-Object { $_.status -in 'queued', 'running' })) {
        throw 'MusicScore still has active jobs. Wait for completion before stopping its local service.'
    }
    $service = Get-CimInstance Win32_Process -Filter "ProcessId = $($identity.pid)"
    if (!$service -or $service.CommandLine -notmatch 'app\.py') { throw 'Cannot verify MusicScore service process.' }
    Stop-Process -Id ([int]$identity.pid)
    $stopped = $true
}
if ($stopped) { Write-Output 'MusicScore local service stopped.' } else { Write-Output 'MusicScore local service is not running.' }
