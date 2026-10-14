# Registers the two scheduled jobs for the current Windows user (no admin rights needed).
# Re-running it replaces them. Remove with:
#   Unregister-ScheduledTask -TaskName "MarketLens evening update","MarketLens weekly maintenance" -Confirm:$false
$script = Join-Path $PSScriptRoot "run_daily.ps1"
$ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

# Run when the laptop is on battery; start as soon as possible after a missed start; never two at once.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 4)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

$jobs = @(
    @{ Name = "MarketLens evening update"; Args = "";
       Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At "18:30";
       Desc = "MarketLens: fetch the day's PSX data, publish tonight's signals, update results (weekdays 18:30 PKT)" },
    @{ Name = "MarketLens weekly maintenance"; Args = " -Weekly";
       Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At "10:00";
       Desc = "MarketLens: full fundamentals refresh, holiday re-check, data-quality report (Saturday 10:00)" }
)
foreach ($j in $jobs) {
    $action = New-ScheduledTaskAction -Execute $ps `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`"$($j.Args)" `
        -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
    Register-ScheduledTask -TaskName $j.Name -Description $j.Desc -Action $action -Trigger $j.Trigger `
        -Settings $settings -Principal $principal -Force | Out-Null
    $info = Get-ScheduledTaskInfo -TaskName $j.Name
    "{0}: next run {1}" -f $j.Name, $info.NextRunTime
}
