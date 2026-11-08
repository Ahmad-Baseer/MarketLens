# One-step setup of MarketLens on a Windows PC: also the repair after moving the folder.
# Safe to re-run: every step skips or updates what is already there.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [-Startup | -NoStartup] [-DataFrom <folder>]
#
#   -Startup     start the tray icon when you log in to Windows
#   -NoStartup   don't (neither switch: you're asked)
#   -DataFrom    an existing PC's data folder (e.g. a copy of D:\...\data). Copies the live
#                signal record and the whole history, so this PC works exactly like that one
#                at once. Without it, the first run downloads everything from PSX (4-5 hours).
#
# Needs Python 3.11+ and Node.js 20.9+ (Next.js 16) installed, and an internet connection.
# What it does: Python environment and packages, website packages and production build,
# the three scheduled jobs, the tray icon (started now, and at logon if chosen), and the
# first data download if there is no data yet.
param([switch]$Startup, [switch]$NoStartup, [string]$DataFrom)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$venvPy = Join-Path $root ".venv\Scripts\python.exe"

function Step([string]$m) { Write-Host "`n== $m" -ForegroundColor Cyan }
function Check([string]$what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

if ($Startup -and $NoStartup) { throw "Use -Startup or -NoStartup, not both." }
if (-not ($Startup -or $NoStartup)) {
    $answer = Read-Host "Start the MarketLens tray icon when you log in to Windows? [Y/n]"
    $Startup = [switch]($answer -notmatch '^\s*(n|no)\s*$')
}

Step "Checking Python and Node.js"
$python = $null
foreach ($cand in @(@{ Exe = "py"; Args = @("-3") }, @{ Exe = "python"; Args = @() })) {
    if (-not (Get-Command $cand.Exe -ErrorAction SilentlyContinue)) { continue }
    # (the Microsoft Store's "python" stub prints an error instead of running: skip it)
    try { $v = & $cand.Exe @($cand.Args) -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null }
    catch { $v = $null }
    if ($LASTEXITCODE -eq 0 -and $v -and [version]$v -ge [version]"3.11") { $python = $cand; break }
}
if (-not $python) { throw "Python 3.11 or newer is needed: https://www.python.org/downloads/ (tick 'Add python.exe to PATH')" }
$nodeV = if (Get-Command node -ErrorAction SilentlyContinue) { (node --version).TrimStart("v") } else { $null }
if (-not $nodeV -or [version]$nodeV -lt [version]"20.9") { throw "Node.js 20.9 or newer is needed: https://nodejs.org/ (LTS)" }
Write-Host "Python $v, Node.js $nodeV"

Step "Python environment and packages"
if (-not (Test-Path $venvPy)) { & $python.Exe @($python.Args) -m venv .venv; Check "creating .venv" }
& $venvPy -m pip install --disable-pip-version-check -q -e "backend[dev,tray]"; Check "pip install"

Step "Data"
if ($DataFrom) {
    if (-not (Test-Path (Join-Path $DataFrom "prices")) -and -not (Test-Path (Join-Path $DataFrom "ledger"))) {
        throw "$DataFrom doesn't look like a MarketLens data folder (no prices\ or ledger\ in it)"
    }
    # newer files already here are kept (/XO), so re-running never rolls data back
    robocopy $DataFrom (Join-Path $root "data") /E /XO /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "copying the data folder failed (robocopy exit $LASTEXITCODE)" }
    Write-Host "Copied $DataFrom -> data\"
}
& $venvPy -c "import sys; from mbf import jobs; sys.exit(1 if jobs.needs_bootstrap() else 0)"
$needsData = $LASTEXITCODE -ne 0
if ($needsData) {
    Write-Host "No data yet: the first run downloads it from PSX once setup is done."
    if (-not (Test-Path (Join-Path $root "legacy\akd_data\mbf_statements.csv"))) {
        Write-Host ("Note: without legacy\akd_data (or -DataFrom), the dividend history starts in " +
                    "Nov 2024, the start of PSX's payout feed, and the live record starts empty.") -ForegroundColor Yellow
    }
} else { Write-Host "Data store present." }

Step "Website packages and production build"
Push-Location (Join-Path $root "web")
try {
    npm install --no-fund --no-audit; Check "npm install"
    npm run build; Check "npm run build"
} finally { Pop-Location }

Step "Scheduled jobs"
& (Join-Path $PSScriptRoot "register_tasks.ps1")

Step "Tray icon"
& $venvPy -m mbf.tray --startup $(if ($Startup) { "on" } else { "off" }); Check "tray startup setting"
Start-Process (Join-Path $root ".venv\Scripts\pythonw.exe") -ArgumentList "-m", "mbf.tray" -WorkingDirectory $root
Write-Host "Tray icon started (look for the MarketLens icon by the clock; it may be under the ^ arrow)."

if ($needsData) {
    Step "First data download"
    Start-ScheduledTask -TaskName "MarketLens catch-up check"
    Write-Host ("Started in the background: 4-5 hours for 26 years of PSX prices, fundamentals and " +
                "announcements. The tray icon is blue while it runs; if the PC sleeps or restarts " +
                "it carries on where it stopped. Progress: data\logs\weekly_<date>.log")
}

Step "Done"
$url = & $venvPy -c "from mbf import tray; print(tray.web_url())"
Write-Host "Open the site from the tray icon (left-click), or run: npm --prefix web run start  ->  $url"
