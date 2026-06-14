param(
    [int]$Port = 8795,
    [switch]$Public,
    [switch]$NoOpen,
    [switch]$Web
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "Virtual environment not found. Run scripts\install-windows.ps1 first."
    exit 1
}

$module = "wavepilot"
$args = @("-m", $module)
if ($Web) {
    $args = @("-m", "wavepilot.server", "--port", "$Port")
    if ($Public) { $args += "--public" }
    if ($NoOpen) { $args += "--no-open" }
}

Set-Location -LiteralPath $root
if ($Web) {
    & $python @args
} else {
    $pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
    if (Test-Path -LiteralPath $pythonw) {
        Start-Process -FilePath $pythonw -ArgumentList $args -WorkingDirectory $root
    } else {
        & $python @args
    }
}
