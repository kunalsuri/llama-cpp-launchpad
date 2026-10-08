# Open the simple model setup page (browser UI) with one command.
#
#   scripts\win\dev-run-ui.ps1 [-Port 8765] [-NoBrowser]
#
# It finds Python (the project's .venv if dev-setup.ps1 made one, else the py launcher / PATH), starts the
# page on http://127.0.0.1:<port>/ (this computer only) and opens your browser. Ctrl+C stops it.
# If the port is busy it uses the next free one. Nothing to install: the page is Python standard library only.

[CmdletBinding()]
param([int]$Port = 8765, [switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$RootDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Script  = Join-Path $RootDir 'utils\model_setup.py'
$Page    = Join-Path $RootDir 'ui\setup\index.html'
$MinPy   = [version]'3.9'

try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$Tick = [string][char]0x2714; $Cross = [string][char]0x2718; $Dot = [string][char]0x25CF; $H = [string][char]0x2500
function Fail([string]$m) { Write-Host "  $Cross $m" -ForegroundColor Red; exit 1 }

Write-Host ''
Write-Host "  $H$H$H  llama.cpp launchpad  $Dot  setup page  $H$H$H" -ForegroundColor Cyan

if (-not (Test-Path $Script)) { Fail "Cannot find $Script. Run this from a full copy of the project." }
if (-not (Test-Path $Page))   { Fail "Cannot find $Page." }

# Python: .venv first, then the py launcher, then PATH. Accept the first one that is new enough.
$candidates = @()
$venvPy = Join-Path $RootDir '.venv\Scripts\python.exe'
if (Test-Path $venvPy) { $candidates += , @($venvPy) }
if (Get-Command py -ErrorAction SilentlyContinue)     { $candidates += , @('py', '-3') }
if (Get-Command python -ErrorAction SilentlyContinue) { $candidates += , @('python') }

$python = $null
foreach ($c in $candidates) {
    $exe = $c[0]; $pre = @($c | Select-Object -Skip 1)
    try {
        $v = (& $exe @pre -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null)
        if ($LASTEXITCODE -eq 0 -and [version]$v -ge $MinPy) { $python = @{ Exe = $exe; Pre = $pre; Version = $v }; break }
    } catch {}
}
if (-not $python) {
    Fail "Python $MinPy or newer was not found. Install it with:  winget install Python.Python.3.12  (then open a new terminal)"
}
Write-Host "  $Tick Python $($python.Version)" -ForegroundColor Green

$args2 = @($python.Pre) + @($Script, '--ui', '--port', $Port)
if ($NoBrowser) { $args2 += '--no-browser' }

$env:PYTHONUTF8 = '1'
Push-Location $RootDir
try {
    & $python.Exe @args2
    $code = $LASTEXITCODE
} finally { Pop-Location }
exit $code
