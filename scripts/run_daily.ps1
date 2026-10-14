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
"=== $(Get-Date -Format s) $kind start" | Out-File -Append -Encoding utf8 $log
& $py -c "import sys; from mbf import jobs; sys.exit(1 if jobs.needs_bootstrap() else 0)" 2>$null
if ($LASTEXITCODE -ne 0) { & $py -u -m mbf bootstrap *>> $log }
# 3 retries, 30 minutes apart: the network is often not back yet right after the laptop wakes
if ($Weekly) { & $py -u -m mbf weekly --retries 3 *>> $log }
else { & $py -u -m mbf update --retries 3 *>> $log }
$code = $LASTEXITCODE
"=== $(Get-Date -Format s) $kind exit $code" | Out-File -Append -Encoding utf8 $log
exit $code
