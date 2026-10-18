# Evening update (and Saturday maintenance) for running on a laptop until the app is
# deployed; a server runs `python -m mbf scheduler` instead. Bootstraps automatically if
# data\ is empty. Logs to data\logs\update_<date>.log or weekly_<date>.log.
#
# Registered in Windows Task Scheduler by scripts\register_tasks.ps1:
#   "MarketLens evening update"       Mon-Fri 18:30  ->  run_daily.ps1
#   "MarketLens weekly maintenance"   Sat 10:00      ->  run_daily.ps1 -Weekly
# Both run as soon as possible after a missed start (laptop asleep or off).
param([switch]$Weekly)

$root = Split-Path -Parent $PSScriptRoot
$kind = if ($Weekly) { "weekly" } else { "update" }
$log = Join-Path $root ("data\logs\{0}_{1:yyyy-MM-dd}.log" -f $kind, (Get-Date))
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
Set-Location $root
$py = "$root\.venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
# Everything goes to the log as UTF-8 text (PowerShell's own *>> would write UTF-16 and
# mix encodings in one file). Python logs to stderr, so 2>&1 and stringify each line.
function Run([string[]]$a) {
    & $py -u -m mbf @a 2>&1 | ForEach-Object { "$_" } | Out-File -Append -Encoding utf8 $log
    return $LASTEXITCODE
}
# One job at a time. If both catch-ups start together (laptop off Friday evening and
# Saturday), the second waits here instead of writing the same data files at once.
# A Windows mutex is released automatically if the holder dies.
$mutex = New-Object System.Threading.Mutex($false, "Local\MarketLensDataJob")
$owned = $false
try { $owned = $mutex.WaitOne([TimeSpan]::FromHours(3)) }
catch [System.Threading.AbandonedMutexException] { $owned = $true }
if (-not $owned) {
    "=== $(Get-Date -Format s) $kind skipped: another MarketLens job held the lock for 3 hours" |
        Out-File -Append -Encoding utf8 $log
    exit 3
}
try {
    "=== $(Get-Date -Format s) $kind start" | Out-File -Append -Encoding utf8 $log
    & $py -c "import sys; from mbf import jobs; sys.exit(1 if jobs.needs_bootstrap() else 0)" 2>$null
    if ($LASTEXITCODE -ne 0) { $null = Run @("bootstrap") }
    # 3 retries, 30 minutes apart: the network is often not back yet right after the laptop wakes
    $code = if ($Weekly) { Run @("weekly", "--retries", "3") } else { Run @("update", "--retries", "3") }
    "=== $(Get-Date -Format s) $kind exit $code" | Out-File -Append -Encoding utf8 $log
}
finally { $mutex.ReleaseMutex() }
exit $code
