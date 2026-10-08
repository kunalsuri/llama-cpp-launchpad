# llama-cpp-launchpad dev setup for Windows (PowerShell 5.1+ or PowerShell 7).
#
#   1. finds Python (py launcher + PATH) and picks the newest 3.10+
#   2. creates <project>\.venv if missing, installs requirements.txt into it
#   3. detects llama.cpp, Ollama and LM Studio
#   4. audits the project's imports against requirements.txt
#   5. writes everything it found to <project>\.system.env
#
# Usage:  scripts\win\dev-setup.ps1 [-Fix] [-Recreate] [-SkipInstall]
#   -Fix          append third-party imports missing from requirements.txt
#   -Recreate     delete and rebuild .venv
#   -SkipInstall  do not run pip

[CmdletBinding()]
param([switch]$Fix, [switch]$Recreate, [switch]$SkipInstall)

$ErrorActionPreference = 'Stop'
$RootDir  = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$VenvDir  = Join-Path $RootDir '.venv'
$VenvPy   = Join-Path $VenvDir 'Scripts\python.exe'
$ReqFile  = Join-Path $RootDir 'requirements.txt'
$EnvFile  = Join-Path $RootDir '.system.env'
$MinPy    = [version]'3.10'          # pytest 9.x requires Python >= 3.10

try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

# --- Look & feel (glyphs built from code points so the file stays pure ASCII) -------------------
$Tick = [string][char]0x2714; $Cross = [string][char]0x2718; $Dot = [string][char]0x25CF
$Arrow = [string][char]0x276F; $H = [string][char]0x2500
function Step([string]$t) { Write-Host ''; Write-Host "  $Arrow " -ForegroundColor Magenta -NoNewline; Write-Host $t -ForegroundColor White }
function Ok([string]$k, [string]$v)   { Write-Host "    $Tick " -ForegroundColor Green -NoNewline;  Write-Host ($k.PadRight(11)) -NoNewline; Write-Host $v -ForegroundColor DarkGray }
function Miss([string]$k, [string]$v) { Write-Host "    $Dot " -ForegroundColor DarkYellow -NoNewline; Write-Host ($k.PadRight(11)) -NoNewline; Write-Host $v -ForegroundColor DarkGray }
function Fail([string]$m) { Write-Host "    $Cross $m" -ForegroundColor Red }

Write-Host ''
Write-Host "  $H$H$H  llama.cpp launchpad  $Dot  dev setup  $H$H$H" -ForegroundColor Cyan
Write-Host "  $RootDir" -ForegroundColor DarkGray

# Run a native command, merge stderr into stdout (llama-server prints --version on stderr), never throw.
function Invoke-Native([string]$Exe, [string[]]$Arguments) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { return (& $Exe @Arguments 2>&1 | ForEach-Object { "$_" }) } catch { return @() } finally { $ErrorActionPreference = $prev }
}
function First-Line($lines) { ($lines | Where-Object { $_ -and $_.Trim() } | Select-Object -First 1) }

# --- 1. Python ------------------------------------------------------------------------------------
Step 'Python'
$pythons = @{}   # exe path -> version
function Add-Python([string]$exe) {
    if (-not $exe -or -not (Test-Path -LiteralPath $exe) -or $pythons.ContainsKey($exe)) { return }
    $out = First-Line (Invoke-Native $exe @('--version'))
    if ($out -match '^Python (\d+\.\d+\.\d+)') { $pythons[$exe] = [version]$Matches[1] }   # skips the Microsoft Store stub
}
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($l in (Invoke-Native 'py' @('-0p'))) { if ($l -match '^\s*-V:\S+\s+\*?\s*(.+?)\s*$') { Add-Python $Matches[1] } }
}
foreach ($c in (Get-Command python, python3 -All -ErrorAction SilentlyContinue)) { if ($c.CommandType -eq 'Application') { Add-Python $c.Source } }

if ($pythons.Count -eq 0) {
    Fail 'No Python found.  Install one:  winget install Python.Python.3.13'
    exit 1
}
$pythons.GetEnumerator() | Sort-Object Value -Descending | ForEach-Object { Ok "v$($_.Value)" $_.Key }
$best = $pythons.GetEnumerator() | Where-Object { $_.Value -ge $MinPy } | Sort-Object Value -Descending | Select-Object -First 1
if (-not $best) { Fail "Need Python $MinPy or newer.  Install one:  winget install Python.Python.3.13"; exit 1 }
$SysPy = $best.Key; $SysPyVer = $best.Value

# --- 2. Virtual environment -----------------------------------------------------------------------
Step '.venv'
if ($Recreate -and (Test-Path $VenvDir)) { Remove-Item -Recurse -Force $VenvDir; Miss 'removed' $VenvDir }
if (-not (Test-Path $VenvPy)) {
    Invoke-Native $SysPy @('-m', 'venv', $VenvDir) | Out-Null
    if (-not (Test-Path $VenvPy)) { Fail "Could not create $VenvDir"; exit 1 }
    Ok 'created' "$VenvDir  (Python $SysPyVer)"
} else {
    Ok 'exists' "$VenvDir  ($(First-Line (Invoke-Native $VenvPy @('--version'))))"
}

if (-not $SkipInstall -and (Test-Path $ReqFile)) {
    Write-Host "    installing requirements.txt ..." -ForegroundColor DarkGray
    $pipOut = Invoke-Native $VenvPy @('-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', '--quiet', '-r', $ReqFile)
    if ($LASTEXITCODE -ne 0) { $pipOut | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }; Fail 'pip install failed'; exit 1 }
    Ok 'packages' 'up to date'
}

# --- 3. Local AI runtimes -------------------------------------------------------------------------
Step 'Local runtimes'
function Find-Exe([string]$name, [string[]]$extra) {
    $c = Get-Command $name -ErrorAction SilentlyContinue | Where-Object CommandType -eq 'Application' | Select-Object -First 1
    if ($c) { return $c.Source }
    foreach ($p in $extra) { if ($p -and (Test-Path -LiteralPath $p)) { return $p } }
    return $null
}
$LlamaServer = if ($env:LLAMA_SERVER -and (Test-Path -LiteralPath $env:LLAMA_SERVER)) { $env:LLAMA_SERVER } else {
    Find-Exe 'llama-server' @((Join-Path $RootDir 'bin\llama-server.exe')) }
$LlamaVer = $null
if ($LlamaServer) { $LlamaVer = (First-Line (Invoke-Native $LlamaServer @('--version') | Where-Object { $_ -match '^version:' })) -replace '^version:\s*', '' }
if ($LlamaServer) { Ok 'llama.cpp' "$LlamaServer  $LlamaVer" } else { Miss 'llama.cpp' 'not found   (winget install llama.cpp)' }

$Ollama = Find-Exe 'ollama' @((Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'))
$OllamaVer = $null
if ($Ollama) {
    $m = [regex]::Match(((Invoke-Native $Ollama @('--version')) -join ' '), 'version is (\d+\.\d+\.\d+\S*)')
    if ($m.Success) { $OllamaVer = $m.Groups[1].Value }
}
if ($Ollama) { Ok 'Ollama' "$Ollama  $OllamaVer" } else { Miss 'Ollama' 'not found   (winget install Ollama.Ollama)' }

$LmsCli = Find-Exe 'lms' @((Join-Path $env:USERPROFILE '.lmstudio\bin\lms.exe'))
$LmApp  = Find-Exe 'LM Studio' @((Join-Path $env:LOCALAPPDATA 'Programs\LM Studio\LM Studio.exe'), (Join-Path $env:ProgramFiles 'LM Studio\LM Studio.exe'))
if (-not $LmApp) {   # fall back to the per-user uninstall entry
    $reg = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
           Where-Object { $_.DisplayName -like 'LM Studio*' } | Select-Object -First 1
    if ($reg -and $reg.InstallLocation) { $cand = Join-Path $reg.InstallLocation 'LM Studio.exe'; if (Test-Path $cand) { $LmApp = $cand } }
}
$LmFound = [bool]($LmApp -or $LmCli)
if ($LmFound) { Ok 'LM Studio' ((@($LmApp, $LmCli) | Where-Object { $_ }) -join '  +  ') } else { Miss 'LM Studio' 'not found   (winget install ElementLabs.LMStudio)' }

# --- Hardware report (detection lives in utils\hardware.py) -------------------------------------
Step 'Hardware'
$HwFile = Join-Path $RootDir '.hardware.env'
$hwOut  = Invoke-Native $VenvPy @((Join-Path $RootDir 'utils\hardware.py'), '--out', $HwFile)
if ($LASTEXITCODE -eq 0 -and (Test-Path $HwFile)) {
    $hw = @{}
    foreach ($l in (Get-Content $HwFile)) { if ($l -match '^(HW_\w+)="(.*)"$') { $hw[$Matches[1]] = $Matches[2] } }
    Ok 'CPU'    "$($hw.HW_CPU_NAME)  ($($hw.HW_CPU_THREADS) threads)"
    Ok 'RAM'    ("{0:N1} GB" -f ([int]$hw.HW_RAM_MB / 1024))
    if ($hw.HW_GPU_KIND -eq 'none') { Miss 'GPU' 'none detected (CPU mode)' }
    else { Ok 'GPU' "$($hw.HW_GPU_NAME)  $([math]::Round([int]$hw.HW_VRAM_MB / 1024)) GB VRAM  -> $($hw.HW_RECOMMENDED_MODE) mode" }
    if ($hw.HW_GPU_KIND -ne 'none' -and $hw.HW_GPU_USABLE_BY_LLAMACPP -ne 'true') { Miss 'note' 'your llama.cpp build does not use this GPU (CPU-only build?)' }
    Ok 'written' $HwFile
} else {
    $hwOut | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
    Fail 'Hardware detection failed (could not read RAM)'
}

# --- 4. Dependency audit --------------------------------------------------------------------------
Step 'Dependencies'
$audit = @'
import ast, importlib.metadata as md, json, re, sys
from pathlib import Path
root = Path(sys.argv[1])
TOOLING = {"pytest"}                      # used by dev-test.ps1 although no file imports it
dirs = [d for d in ("scripts", "tests", "utils") if (root / d).is_dir()]
files = [f for d in dirs for f in (root / d).rglob("*.py")]
local = {f.stem for f in files} | {p.name for d in dirs for p in (root / d).iterdir() if p.is_dir()}
dists = md.packages_distributions()
norm = lambda n: re.sub(r"[-_.]+", "-", n).lower()
used = set()
for f in files:
    for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
        mods = [a.name for a in n.names] if isinstance(n, ast.Import) else \
               [n.module] if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module else []
        for m in mods:
            top = m.split(".")[0]
            if top not in sys.stdlib_module_names and top not in local:
                used.add(norm(dists[top][0] if top in dists else top))
used |= TOOLING
req = root / "requirements.txt"
declared = {norm(m.group()) for l in (req.read_text(encoding="utf-8").splitlines() if req.exists() else [])
            if (m := re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", l.strip()))}
print(json.dumps({"used": sorted(used), "declared": sorted(declared), "missing": sorted(used - declared)}))
'@
$result = $null
$json = ($audit | & $VenvPy - $RootDir) -join ''
try { $result = $json | ConvertFrom-Json } catch { Fail "Dependency audit failed: $json"; exit 1 }
Ok 'required' ((@($result.used) -join ', '))
Ok 'declared' ((@($result.declared) -join ', '))
$missing = @($result.missing)
if ($missing.Count -eq 0) {
    Ok 'status' 'every required package is in requirements.txt'
} elseif ($Fix) {
    $add = ($missing | ForEach-Object { "$_" }) -join [Environment]::NewLine
    [IO.File]::AppendAllText($ReqFile, $add + [Environment]::NewLine)
    Ok 'fixed' "appended to requirements.txt: $($missing -join ', ')  (pin a version, then re-run)"
} else {
    Miss 'MISSING' "$($missing -join ', ')   -> re-run with -Fix to append"
}

# --- 5. .system.env -------------------------------------------------------------------------------
Step '.system.env'
function Q($v) { if ($null -eq $v) { '""' } else { '"' + ("$v" -replace '"', '\"') + '"' } }
function YN([bool]$b) { if ($b) { 'true' } else { 'false' } }
$lines = @(
    '# Generated by scripts\win\dev-setup.ps1 - do not edit, do not commit.'
    "GENERATED_AT=$(Q ([DateTime]::UtcNow.ToString('o')))"
    "OS=$(Q ((Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue).Caption))"
    "OS_BUILD=$(Q ([Environment]::OSVersion.Version))"
    "POWERSHELL=$(Q $PSVersionTable.PSVersion)"
    "PROJECT_ROOT=$(Q $RootDir)"
    ''
    "PYTHON_SYSTEM=$(Q $SysPy)"
    "PYTHON_SYSTEM_VERSION=$(Q $SysPyVer)"
    "PYTHON_ALL=$(Q (($pythons.GetEnumerator() | Sort-Object Value -Descending | ForEach-Object { "$($_.Value)=$($_.Key)" }) -join ';'))"
    "VENV_PATH=$(Q $VenvDir)"
    "VENV_PYTHON=$(Q $VenvPy)"
    "VENV_PYTHON_VERSION=$(Q ((First-Line (Invoke-Native $VenvPy @('--version'))) -replace '^Python ', ''))"
    ''
    "LLAMACPP_INSTALLED=$(YN ([bool]$LlamaServer))"
    "LLAMACPP_SERVER=$(Q $LlamaServer)"
    "LLAMACPP_VERSION=$(Q $LlamaVer)"
    "OLLAMA_INSTALLED=$(YN ([bool]$Ollama))"
    "OLLAMA_PATH=$(Q $Ollama)"
    "OLLAMA_VERSION=$(Q $OllamaVer)"
    "LMSTUDIO_INSTALLED=$(YN $LmFound)"
    "LMSTUDIO_APP=$(Q $LmApp)"
    "LMSTUDIO_CLI=$(Q $LmsCli)"
    ''
    "REQUIRED_PACKAGES=$(Q (@($result.used) -join ','))"
    "MISSING_FROM_REQUIREMENTS=$(Q ($missing -join ','))"
)
[IO.File]::WriteAllText($EnvFile, ($lines -join [Environment]::NewLine) + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
Ok 'written' $EnvFile

# --- Next steps, in plain language ----------------------------------------------------------------
function Hint([string]$text, [string]$cmd) {
    Write-Host "    $text" -ForegroundColor Gray
    if ($cmd) { Write-Host "        $cmd" -ForegroundColor Yellow }
}
$stillMissing = $missing.Count -gt 0 -and -not $Fix
Write-Host ''
if ($stillMissing) { Write-Host "  $Dot almost ready - one thing left" -ForegroundColor DarkYellow }
else               { Write-Host "  $Tick ready" -ForegroundColor Green }
Write-Host ''
Write-Host "  What to do next" -ForegroundColor White
$n = 1
if ($stillMissing) {
    Hint "$n. Your code uses packages that are not listed in requirements.txt. Add them with:" "scripts\win\dev-setup.ps1 -Fix"
    Hint "   (or install them by hand:  .\.venv\Scripts\python.exe -m pip install $($missing -join ' '))" $null
    $n++
}
Hint "$n. Turn on the project's Python environment in this terminal (do this once per terminal window):" ".\.venv\Scripts\Activate.ps1"
Hint "   You will see (.venv) at the start of your prompt. If Windows blocks it, run this once, then try again:" "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned"
$n++
Hint "$n. Install a Python package into the project (always with the environment on):" "pip install <package-name>"
Hint "   Then record it so others get it too: add a line with its name to requirements.txt." $null
$n++
Hint "$n. Re-install everything listed in requirements.txt at any time:" "pip install -r requirements.txt"
$n++
Hint "$n. Run the tests:" "scripts\win\dev-test.ps1"
if (-not $LlamaServer) { $n++; Hint "$n. llama.cpp is missing. Install it, then open a NEW terminal and run this script again:" "winget install llama.cpp" }
Write-Host ''
if ($stillMissing) { exit 2 }
