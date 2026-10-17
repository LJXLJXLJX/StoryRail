param(
    [string]$TaskName = "StoryRail Default Model Providers",
    [string]$ComfyTaskName = "StoryRail ComfyUI FL2VA Runtime",
    [string]$BreezeTaskName = "StoryRail Breeze TTS 2",
    [int]$ListenPort = 8791
)

$ErrorActionPreference = "Stop"
$StateRoot = "E:\StoryRailModelProviders"

# Keep this file pure ASCII: Windows PowerShell 5.1 decodes .ps1 without a BOM as
# ANSI, so non-ASCII comments corrupt the script body.
function Stop-StoryRailTasks {
    foreach ($Name in @($TaskName, $ComfyTaskName, $BreezeTaskName)) {
        $Task = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
        if ($Task) {
            Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
        }
    }
}

# The scheduled task restarts on failure (once a minute, three times). Stopping
# the task first and killing the process afterwards makes the task look failed,
# so the restart policy immediately brings the service back. Stop the tasks
# again after the processes are gone to preempt that queued restart.
Stop-StoryRailTasks

function Stop-ManagedProcess {
    param(
        [string]$PidFile,
        [string]$ExpectedModule,
        [string]$Label
    )
    if (-not (Test-Path -LiteralPath $PidFile -PathType Leaf)) {
        return
    }
    $ManagedPid = 0
    if (-not [int]::TryParse(
        [System.IO.File]::ReadAllText($PidFile).Trim(),
        [ref]$ManagedPid
    )) {
        throw "$Label pid file is invalid; refusing to stop an unknown process."
    }
    $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $ManagedPid"
    if ($Process) {
        if (-not $Process.CommandLine -or -not $Process.CommandLine.Contains($ExpectedModule)) {
            throw "$Label pid file does not identify the managed StoryRail process."
        }
        Stop-Process -Id $ManagedPid -Force
        Wait-Process -Id $ManagedPid -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $PidFile -Force
}

Stop-ManagedProcess `
    (Join-Path $StateRoot "service.pid") `
    "default_model_providers_implement.server" `
    "StoryRail Model Provider"
Stop-ManagedProcess `
    (Join-Path $StateRoot "comfyui.pid") `
    "main.py --listen 127.0.0.1 --port 8188" `
    "StoryRail ComfyUI"

# Breeze is a managed WSL process without a Windows PID file. Match only the
# fixed deployment command, never all Python or WSL processes.
& wsl.exe -d Ubuntu --exec /bin/pkill -TERM -f `
    "breeze_infer.api /home/ljx/ai/models/Breeze-TTS-2" 2>$null

# A forced Windows supervisor stop must also release its exact WSL IndexTTS worker.
& wsl.exe -d Ubuntu --exec /bin/pkill -TERM -f `
    "/mnt/e/Project/StoryRail/default_model_providers_implement/indextts2_worker.py --serve" 2>$null

# The pid file can be missing or stale (stopping the task kills the wrapper
# powershell first and leaves python orphaned), so match the fixed server
# module on the command line as well.
function Stop-OrphanedServer {
    $Orphans = @(
        Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
            Where-Object { $_.CommandLine -and $_.CommandLine.Contains("default_model_providers_implement.server") }
    )
    foreach ($Orphan in $Orphans) {
        Stop-Process -Id $Orphan.ProcessId -Force
        Wait-Process -Id $Orphan.ProcessId -ErrorAction SilentlyContinue
    }
    return $Orphans.Count
}

$null = Stop-OrphanedServer

# Preempt the queued failure restart, then confirm the shutdown really happened:
# no managed process left and the fixed port released.
Start-Sleep -Seconds 2
Stop-StoryRailTasks

$Remaining = @(
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains("default_model_providers_implement.server") }
)
$Listening = @(
    Get-NetTCPConnection -State Listen -LocalPort $ListenPort -ErrorAction SilentlyContinue
)
if ($Remaining.Count -gt 0 -or $Listening.Count -gt 0) {
    throw "StoryRail Model Provider is still running (processes: $($Remaining.Count), listeners: $($Listening.Count))."
}

Write-Output "Stopped StoryRail Windows provider processes; scheduled tasks were preserved."
