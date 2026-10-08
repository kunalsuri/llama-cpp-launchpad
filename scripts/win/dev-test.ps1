# Run the whole test suite (tests\) with pytest inside the project's .venv.
# Usage:  scripts\win\dev-test.ps1 [extra pytest args]     e.g.  scripts\win\dev-test.ps1 -k audit -x
# Needs scripts\win\dev-setup.ps1 to have been run once.

$RootDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$VenvPy  = Join-Path $RootDir '.venv\Scripts\python.exe'

if (-not (Test-Path $VenvPy)) {
    Write-Host '  .venv not found. Run scripts\win\dev-setup.ps1 first.' -ForegroundColor Red
    exit 1
}
& $VenvPy -c 'import pytest' 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '  pytest is not installed in .venv. Run scripts\win\dev-setup.ps1.' -ForegroundColor Red
    exit 1
}

$env:PYTHONUTF8 = '1'
Push-Location $RootDir
try {
    & $VenvPy -m pytest tests @args
    $code = $LASTEXITCODE
} finally { Pop-Location }

$color = if ($code -eq 0) { 'Green' } else { 'Red' }
Write-Host ("  " + $(if ($code -eq 0) { [char]0x2714 + ' all tests passed' } else { [char]0x2718 + " tests failed (exit $code)" })) -ForegroundColor $color
exit $code
