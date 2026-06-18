param(
    [string]$TaskName = "WavePilot SDR Dev Auto Sync"
)

$ErrorActionPreference = "Stop"
$taskPath = "\WavePilot\"

if (Get-ScheduledTask -TaskName $TaskName -TaskPath $taskPath -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -TaskPath $taskPath -Confirm:$false
    Write-Host "[WavePilot] Removed scheduled task $taskPath$TaskName"
} else {
    Write-Host "[WavePilot] Scheduled task was not installed: $taskPath$TaskName"
}
