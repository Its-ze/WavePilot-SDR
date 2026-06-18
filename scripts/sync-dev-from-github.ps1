param(
    [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$Remote = "origin",
    [string]$Branch = "main",
    [ValidateSet("PullOnly", "PushCommitted", "AutoCommitAndPush")]
    [string]$Mode = "PullOnly",
    [string]$CommitMessagePrefix = "Auto-sync WavePilot dev changes",
    [string]$LogPath = (Join-Path $env:LOCALAPPDATA "WavePilotSDR\dev-sync.log"),
    [string]$StatePath = (Join-Path $env:LOCALAPPDATA "WavePilotSDR\dev-sync-last.json")
)

$ErrorActionPreference = "Stop"
$BlockedPublishPatterns = @(
    '(^|/)\.env($|[.])',
    '(^|/).*\.pem$',
    '(^|/).*\.key$',
    '(^|/)id_rsa($|[.])',
    '(^|/).*secret.*',
    '(^|/).*token.*',
    '(^|/).*password.*',
    '(^|/)backups?/'
)

function Write-SyncLog {
    param([string]$Message)
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $dir = Split-Path -Parent $LogPath
    if ($dir) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    Add-Content -Path $LogPath -Value "[$stamp] $Message"
}

function Save-SyncState {
    param(
        [string]$Status,
        [string]$Message,
        [string]$Before = "",
        [string]$After = ""
    )
    $dir = Split-Path -Parent $StatePath
    if ($dir) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    [ordered]@{
        checked_at = (Get-Date).ToString("o")
        repo = $RepoPath
        remote = $Remote
        branch = $Branch
        mode = $Mode
        status = $Status
        message = $Message
        before = $Before
        after = $After
    } | ConvertTo-Json | Set-Content -Path $StatePath -Encoding UTF8
}

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    $output = & git @Args 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Args -join ' ') failed: $output"
    }
    return $output
}

function Get-StatusPaths {
    $lines = @(git status --porcelain --untracked-files=normal)
    if ($LASTEXITCODE -ne 0) {
        throw "git status failed."
    }
    $paths = New-Object System.Collections.Generic.List[string]
    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line.Length -lt 4) {
            continue
        }
        $rawPath = $line.Substring(3).Trim()
        foreach ($part in ($rawPath -split " -> ")) {
            $normalized = $part.Trim().Trim('"') -replace "\\", "/"
            if ($normalized) {
                $paths.Add($normalized)
            }
        }
    }
    return @($paths)
}

function Assert-PublishablePaths {
    param([string[]]$Paths)
    foreach ($path in $Paths) {
        foreach ($pattern in $BlockedPublishPatterns) {
            if ($path -match $pattern) {
                throw "Refusing to auto-publish blocked path: $path"
            }
        }
    }
}

try {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git is not available on PATH."
    }
    if (-not (Test-Path -LiteralPath $RepoPath)) {
        throw "Repo path not found: $RepoPath"
    }

    Push-Location -LiteralPath $RepoPath
    try {
        $currentBranch = (Invoke-Git rev-parse --abbrev-ref HEAD).Trim()
        if ($currentBranch -ne $Branch) {
            $message = "Skipped: current branch is $currentBranch, expected $Branch."
            Write-SyncLog $message
            Save-SyncState -Status "skipped" -Message $message
            exit 0
        }

        Invoke-Git fetch --prune $Remote | Out-Null
        $local = (Invoke-Git rev-parse HEAD).Trim()
        $upstream = (Invoke-Git rev-parse "$Remote/$Branch").Trim()
        $base = (Invoke-Git merge-base HEAD "$Remote/$Branch").Trim()
        $dirtyPaths = @(Get-StatusPaths)

        if ($dirtyPaths.Count -gt 0) {
            if ($Mode -ne "AutoCommitAndPush") {
                $message = "Skipped: local working tree has uncommitted changes."
                Write-SyncLog $message
                Save-SyncState -Status "skipped" -Message $message -Before $local -After $upstream
                exit 0
            }
            if ($local -ne $upstream) {
                $message = "Skipped: local edits exist and remote is not at the same commit."
                Write-SyncLog $message
                Save-SyncState -Status "skipped" -Message $message -Before $local -After $upstream
                exit 0
            }
            Assert-PublishablePaths -Paths $dirtyPaths
            Invoke-Git add -A | Out-Null
            $stagedPaths = @(git diff --cached --name-only)
            if ($LASTEXITCODE -ne 0) {
                throw "git diff --cached --name-only failed."
            }
            Assert-PublishablePaths -Paths $stagedPaths
            if ($stagedPaths.Count -eq 0) {
                $message = "Skipped: no publishable changes after staging."
                Write-SyncLog $message
                Save-SyncState -Status "skipped" -Message $message -Before $local -After $upstream
                exit 0
            }
            $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
            Invoke-Git commit -m "$CommitMessagePrefix ($stamp)" | Out-Null
            $local = (Invoke-Git rev-parse HEAD).Trim()
            Invoke-Git push $Remote $Branch | Out-Null
            $message = "Committed and pushed local edits to $local."
            Write-SyncLog $message
            Save-SyncState -Status "pushed" -Message $message -Before $upstream -After $local
            exit 0
        }

        if ($local -eq $upstream) {
            $message = "Already current at $local."
            Write-SyncLog $message
            Save-SyncState -Status "current" -Message $message -Before $local -After $local
            exit 0
        }

        if ($local -eq $base) {
            Invoke-Git pull --ff-only $Remote $Branch | Out-Null
            $after = (Invoke-Git rev-parse HEAD).Trim()
            $message = "Fast-forwarded from $local to $after."
            Write-SyncLog $message
            Save-SyncState -Status "updated" -Message $message -Before $local -After $after
            exit 0
        }

        if ($upstream -eq $base) {
            if ($Mode -eq "PushCommitted" -or $Mode -eq "AutoCommitAndPush") {
                Invoke-Git push $Remote $Branch | Out-Null
                $message = "Pushed existing local commits from $upstream to $local."
                Write-SyncLog $message
                Save-SyncState -Status "pushed" -Message $message -Before $upstream -After $local
                exit 0
            }
            $message = "Skipped: local branch is ahead of $Remote/$Branch."
        } else {
            $message = "Skipped: local and remote branches diverged."
        }
        Write-SyncLog $message
        Save-SyncState -Status "skipped" -Message $message -Before $local -After $upstream
        exit 0
    } finally {
        Pop-Location
    }
} catch {
    $message = "Error: $($_.Exception.Message)"
    Write-SyncLog $message
    Save-SyncState -Status "error" -Message $message
    exit 1
}
