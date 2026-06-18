param(
    [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "WavePilot SDR Dev Auto Sync",
    [int]$Minutes = 5,
    [ValidateSet("PullOnly", "PushCommitted", "AutoCommitAndPush")]
    [string]$Mode = "AutoCommitAndPush",
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"

if ($Minutes -lt 1) {
    throw "Minutes must be 1 or greater."
}

$RepoPath = (Resolve-Path -LiteralPath $RepoPath).Path
$SyncScript = Join-Path $RepoPath "scripts\sync-dev-from-github.ps1"
if (-not (Test-Path -LiteralPath $SyncScript)) {
    throw "Sync script not found: $SyncScript"
}

$taskPath = "\WavePilot\"
$escapedScript = $SyncScript.Replace('"', '\"')
$escapedRepo = $RepoPath.Replace('"', '\"')
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$escapedScript`" -RepoPath `"$escapedRepo`" -Mode $Mode"

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $Minutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -TaskPath $taskPath `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Safely syncs the WavePilot SDR dev repo with GitHub using mode $Mode." `
    -Force | Out-Null

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName -TaskPath $taskPath
}

Write-Host "[WavePilot] Installed scheduled task $taskPath$TaskName"
Write-Host "[WavePilot] Sync interval: every $Minutes minute(s)"
Write-Host "[WavePilot] Sync mode: $Mode"
Write-Host "[WavePilot] Repo: $RepoPath"
Write-Host "[WavePilot] Log: $env:LOCALAPPDATA\WavePilotSDR\dev-sync.log"
