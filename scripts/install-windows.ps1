param(
    [string]$InstallDir = "$env:LOCALAPPDATA\WavePilotSDR",
    [string]$Repository = "Its-ze/WavePilot-SDR",
    [switch]$Yes,
    [switch]$InstallDriver,
    [switch]$SkipDriverDlls,
    [switch]$SkipZadig,
    [switch]$NoShortcut
)

$ErrorActionPreference = "Stop"

function Say($Message) {
    Write-Host "[WavePilot] $Message"
}

function Confirm-Step($Question) {
    if ($Yes) { return $true }
    $answer = Read-Host "$Question [y/N]"
    return $answer -match '^(y|yes)$'
}

function Invoke-Download($Uri, $OutFile) {
    Say "Downloading $Uri"
    Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing
}

function Get-GitHubAssetUrl($Repo, $Pattern) {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ "User-Agent" = "WavePilot-SDR-Installer" }
    $asset = $release.assets | Where-Object { $_.name -match $Pattern } | Select-Object -First 1
    if (-not $asset) {
        throw "Could not find release asset matching '$Pattern' in $Repo"
    }
    return $asset.browser_download_url
}

function Get-SourceDir {
    $scriptRoot = Split-Path -Parent $PSScriptRoot
    if (Test-Path -LiteralPath (Join-Path $scriptRoot "wavepilot\server.py")) {
        return $scriptRoot
    }

    $temp = Join-Path ([IO.Path]::GetTempPath()) ("wavepilot-src-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $temp | Out-Null
    $zip = Join-Path $temp "source.zip"
    Invoke-Download "https://github.com/$Repository/archive/refs/heads/main.zip" $zip
    Expand-Archive -LiteralPath $zip -DestinationPath $temp -Force
    $root = Get-ChildItem -LiteralPath $temp -Directory | Select-Object -First 1
    if (-not $root) { throw "Could not unpack source archive" }
    return $root.FullName
}

function Copy-Source($SourceDir, $DestDir) {
    New-Item -ItemType Directory -Force -Path $DestDir | Out-Null
    robocopy $SourceDir $DestDir /E /XD .git .venv .runtime __pycache__ /XF *.pyc *.log | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed with code $LASTEXITCODE"
    }
}

function Install-PythonDeps($DestDir) {
    $python = (Get-Command python -ErrorAction Stop).Source
    Say "Using Python at $python"
    & $python -m venv (Join-Path $DestDir ".venv")
    $venvPython = Join-Path $DestDir ".venv\Scripts\python.exe"
    & $venvPython -m pip install --upgrade pip wheel
    & $venvPython -m pip install -r (Join-Path $DestDir "requirements.txt")
}

function Install-DriverDlls($DestDir) {
    if ($SkipDriverDlls) { return }
    if (-not (Confirm-Step "Download public RTL-SDR driver DLLs from rtlsdrblog/rtl-sdr-blog?")) {
        Say "Skipped RTL-SDR DLL download."
        return
    }

    $runtimeBin = Join-Path $DestDir ".runtime\bin"
    New-Item -ItemType Directory -Force -Path $runtimeBin | Out-Null
    $temp = Join-Path ([IO.Path]::GetTempPath()) ("wavepilot-drivers-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $temp | Out-Null
    $zip = Join-Path $temp "rtl-sdr-blog-release.zip"
    $assetUrl = Get-GitHubAssetUrl "rtlsdrblog/rtl-sdr-blog" "(?i)release.*\.zip$"
    Invoke-Download $assetUrl $zip
    Expand-Archive -LiteralPath $zip -DestinationPath $temp -Force

    $x64 = Get-ChildItem -LiteralPath $temp -Recurse -Directory | Where-Object { $_.Name -eq "x64" } | Select-Object -First 1
    $searchRoot = if ($x64) { $x64.FullName } else { $temp }
    $needed = @("rtlsdr.dll", "libusb-1.0.dll", "pthreadVC2.dll", "msvcr100.dll")
    foreach ($name in $needed) {
        $file = Get-ChildItem -LiteralPath $searchRoot -Recurse -File -Filter $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($file) {
            Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $runtimeBin $name) -Force
        }
    }

    if (-not (Test-Path -LiteralPath (Join-Path $runtimeBin "rtlsdr.dll"))) {
        throw "Downloaded driver archive did not contain rtlsdr.dll"
    }
    Say "Installed RTL-SDR runtime DLLs in $runtimeBin"
}

function Install-Zadig {
    if ($SkipZadig) {
        Say "Skipped Zadig driver step."
        return
    }
    if (-not $InstallDriver -and -not (Confirm-Step "Launch Zadig to install/replace the RTL-SDR WinUSB driver?")) {
        Say "Skipped Zadig driver step."
        return
    }

    $toolDir = Join-Path $InstallDir ".runtime\tools"
    New-Item -ItemType Directory -Force -Path $toolDir | Out-Null
    $zadig = Join-Path $toolDir "zadig.exe"
    try {
        $assetUrl = Get-GitHubAssetUrl "pbatard/libwdi" "(?i)zadig-.*\.exe$"
    } catch {
        $assetUrl = "https://zadig.akeo.ie/downloads/zadig-2.9.exe"
    }
    Invoke-Download $assetUrl $zadig

    Say "Zadig will ask for administrator permission."
    Say "Select the RTL2838 / Bulk-In Interface 0 device and choose WinUSB."
    Start-Process -FilePath $zadig -Verb RunAs
}

function Write-Launcher($DestDir) {
    $launcher = Join-Path $DestDir "Start-WavePilot.ps1"
    $content = @"
`$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "$DestDir"
`$pythonw = "$DestDir\.venv\Scripts\pythonw.exe"
if (Test-Path -LiteralPath `$pythonw) {
    Start-Process -FilePath `$pythonw -ArgumentList @("-m", "wavepilot") -WorkingDirectory "$DestDir"
} else {
    & "$DestDir\.venv\Scripts\python.exe" -m wavepilot
}
"@
    Set-Content -LiteralPath $launcher -Value $content -Encoding UTF8
    return $launcher
}

function Install-Shortcuts($Launcher) {
    if ($NoShortcut) { return }
    $target = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $args = "-NoProfile -ExecutionPolicy Bypass -File `"$Launcher`""
    $shell = New-Object -ComObject WScript.Shell

    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcut = $shell.CreateShortcut((Join-Path $desktop "WavePilot SDR.lnk"))
    $shortcut.TargetPath = $target
    $shortcut.Arguments = $args
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.Save()

    $programs = Join-Path ([Environment]::GetFolderPath("Programs")) "WavePilot SDR"
    New-Item -ItemType Directory -Force -Path $programs | Out-Null
    $menu = $shell.CreateShortcut((Join-Path $programs "WavePilot SDR.lnk"))
    $menu.TargetPath = $target
    $menu.Arguments = $args
    $menu.WorkingDirectory = $InstallDir
    $menu.Save()
}

$source = Get-SourceDir
Say "Installing from $source"
Copy-Source $source $InstallDir
Install-PythonDeps $InstallDir
Install-DriverDlls $InstallDir
Install-Zadig
$launcherPath = Write-Launcher $InstallDir
Install-Shortcuts $launcherPath

Say "Installed to $InstallDir"
Say "Start with: powershell -ExecutionPolicy Bypass -File `"$launcherPath`""
