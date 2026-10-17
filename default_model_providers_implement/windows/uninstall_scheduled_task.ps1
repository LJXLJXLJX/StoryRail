param(
    [string]$TaskName = "StoryRail Default Model Providers",
    [string]$ComfyTaskName = "StoryRail ComfyUI FL2VA Runtime"
)

$ErrorActionPreference = "Stop"
$StateRoot = "E:\StoryRailModelProviders"
$DefenderScript = Join-Path $PSScriptRoot "configure_h3_defender_exclusions.ps1"
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed scheduled task: $TaskName"
} else {
    Write-Output "Scheduled task does not exist: $TaskName"
}
$ComfyTask = Get-ScheduledTask -TaskName $ComfyTaskName -ErrorAction SilentlyContinue
if ($ComfyTask) {
    Stop-ScheduledTask -TaskName $ComfyTaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $ComfyTaskName -Confirm:$false
    Write-Output "Removed scheduled task: $ComfyTaskName"
} else {
    Write-Output "Scheduled task does not exist: $ComfyTaskName"
}
$PidFile = Join-Path $StateRoot "service.pid"
if (Test-Path -LiteralPath $PidFile -PathType Leaf) {
    $ServicePid = 0
    if (-not [int]::TryParse(
        [System.IO.File]::ReadAllText($PidFile).Trim(),
        [ref]$ServicePid
    )) {
        throw "StoryRail service.pid is invalid; refusing to stop an unknown process."
    }
    $ServiceProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $ServicePid"
    if ($ServiceProcess) {
        $ExpectedModule = "default_model_providers_implement.server"
        if (-not $ServiceProcess.CommandLine -or -not $ServiceProcess.CommandLine.Contains($ExpectedModule)) {
            throw "service.pid does not identify the StoryRail model server."
        }
        Stop-Process -Id $ServicePid -Force
        Wait-Process -Id $ServicePid -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $PidFile -Force
}
$ComfyPidFile = Join-Path $StateRoot "comfyui.pid"
if (Test-Path -LiteralPath $ComfyPidFile -PathType Leaf) {
    $ComfyPid = 0
    if (-not [int]::TryParse(
        [System.IO.File]::ReadAllText($ComfyPidFile).Trim(),
        [ref]$ComfyPid
    )) {
        throw "StoryRail comfyui.pid is invalid; refusing to stop an unknown process."
    }
    $ComfyProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $ComfyPid"
    if ($ComfyProcess) {
        $ExpectedPython = "E:\Programs\Dev\MiniForge3\envs\comfyui\python.exe"
        $ExpectedArguments = "main.py --listen 127.0.0.1 --port 8188"
        if (
            $ComfyProcess.ExecutablePath -ne $ExpectedPython -or
            -not $ComfyProcess.CommandLine -or
            -not $ComfyProcess.CommandLine.Contains($ExpectedArguments)
        ) {
            throw "comfyui.pid does not identify the managed ComfyUI service."
        }
        Stop-Process -Id $ComfyPid -Force
        Wait-Process -Id $ComfyPid -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $ComfyPidFile -Force
}
if (Test-Path -LiteralPath $DefenderScript -PathType Leaf) {
    & $DefenderScript -Action Remove -StateRoot $StateRoot
}
Write-Output "Code and E:\StoryRailModelProviders state were preserved."
