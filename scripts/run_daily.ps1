# Daily evening update for local testing on a laptop (a server runs
# `python -m mbf scheduler` instead). Bootstraps automatically if data\ is empty.
# Logs to data\logs\update_<date>.log
# Register with Windows Task Scheduler (weekdays 18:30) — run once, yourself:
#   schtasks /Create /TN "MBF daily update" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 18:30 `
#     /TR "powershell -NoProfile -ExecutionPolicy Bypass -File D:\Investments\MBF\scripts\run_daily.ps1"
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root ("data\logs\update_{0:yyyy-MM-dd}.log" -f (Get-Date))
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
Set-Location $root
$py = "$root\.venv\Scripts\python.exe"
& $py -c "import sys; from mbf import jobs; sys.exit(1 if jobs.needs_bootstrap() else 0)" 2>$null
if ($LASTEXITCODE -ne 0) { & $py -u -m mbf bootstrap *>> $log }
& $py -u -m mbf update *>> $log
exit $LASTEXITCODE
