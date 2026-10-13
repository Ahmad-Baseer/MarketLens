# Daily evening update for local testing. Logs to data\logs\update_<date>.log
# Register with Windows Task Scheduler (weekdays 18:30) — run once, yourself:
#   schtasks /Create /TN "MBF daily update" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 18:30 `
#     /TR "powershell -NoProfile -ExecutionPolicy Bypass -File D:\Investments\MBF\scripts\run_daily.ps1"
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root ("data\logs\update_{0:yyyy-MM-dd}.log" -f (Get-Date))
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
Set-Location $root
& "$root\.venv\Scripts\python.exe" -u -m mbf update *>> $log
exit $LASTEXITCODE
