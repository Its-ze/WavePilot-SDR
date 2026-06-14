param(
    [int]$Port = 8795,
    [switch]$Public,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "Virtual environment not found. Run scripts\install-windows.ps1 first."
    exit 1
}

$args = @("-m", "wavepilot", "--port", "$Port")
if ($Public) { $args += "--public" }
if ($NoOpen) { $args += "--no-open" }

Set-Location -LiteralPath $root
& $python @args
