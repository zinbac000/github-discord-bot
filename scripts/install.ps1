# Install github-discord-bot as a scheduled task on Windows.
#   scripts\install.ps1              install, start at logon
#   scripts\install.ps1 -Uninstall   stop and remove
param(
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$TaskName = 'github-discord-bot'
$Repo = Split-Path -Parent $PSScriptRoot
$Log = Join-Path $Repo 'bot.log'

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed $TaskName."
    } else {
        Write-Host "$TaskName is not installed."
    }
    return
}

$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { throw 'uv not found. Install it: https://docs.astral.sh/uv/' }
if (-not (Test-Path (Join-Path $Repo '.env'))) {
    throw "Missing $Repo\.env. Copy .env.example and fill it in."
}

Push-Location $Repo
try { & $uv sync --frozen; if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' } } finally { Pop-Location }

$action = New-ScheduledTaskAction -Execute 'cmd.exe' `
    -Argument "/c `"`"$uv`" run --frozen github-discord-bot >> `"$Log`" 2>&1`"" `
    -WorkingDirectory $Repo
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

$user = "$env:USERDOMAIN\$env:USERNAME"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed and started $TaskName (starts at logon)."
Write-Host "  Logs:    Get-Content '$Log' -Wait"
Write-Host "  Status:  Get-ScheduledTask $TaskName | Get-ScheduledTaskInfo"
Write-Host "  Remove:  scripts\install.ps1 -Uninstall"
