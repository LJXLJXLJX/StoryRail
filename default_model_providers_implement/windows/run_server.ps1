param(
    [ValidatePattern("^(?!0\.0\.0\.0$)\d{1,3}(\.\d{1,3}){3}$")]
    [string]$ListenAddress = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = $RepositoryRoot
$env:STORYRAIL_COMFYUI_ROOT = "E:\Project\ComfyUI"
$env:STORYRAIL_H3_MODEL_ROOT = "E:\Project\ComfyUI\models"
$env:STORYRAIL_H3_PYTHON = "E:\Programs\Dev\MiniForge3\envs\comfyui\python.exe"
$env:STORYRAIL_H3_CPU_THREADS = "4"
$env:STORYRAIL_WSL_DISTRIBUTION = "Ubuntu"
$env:STORYRAIL_SEEDVR2_ROOT = "E:\Project\seedvr2"
$env:STORYRAIL_SEEDVR2_MODEL_ROOT = "E:\Project\seedvr2\models\SEEDVR2"
$env:STORYRAIL_SEEDVR2_PYTHON = "E:\Programs\Dev\MiniForge3\envs\storyrail-seedvr2\python.exe"
$env:STORYRAIL_FFPROBE = "E:\Programs\Dev\MiniForge3\envs\storyrail-seedvr2\Library\bin\ffprobe.exe"
$env:STORYRAIL_STABLE_AUDIO_PYTHON = "/home/ljx/ai/stable-audio-3/.venv/bin/python"
$env:STORYRAIL_STABLE_AUDIO_PYTHONPATH = "/mnt/e/Project/StoryRail"
$env:STORYRAIL_INDEXTTS2_ROOT = "E:\Project\index-tts"
$env:STORYRAIL_INDEXTTS2_MODEL_ROOT = "E:\Project\index-tts\checkpoints"
$env:STORYRAIL_INDEXTTS2_PYTHON = "/mnt/e/Project/index-tts/.venv/bin/python"
$TokenFile = "E:\StoryRailModelProviders\service-token.txt"
if (-not (Test-Path -LiteralPath $TokenFile -PathType Leaf)) {
    throw "Service token is missing. Run install_scheduled_task.ps1 first."
}
$env:STORYRAIL_MODEL_SERVICE_TOKEN = [System.IO.File]::ReadAllText($TokenFile).Trim()

$Python = $env:STORYRAIL_H3_PYTHON
$StateRoot = "E:\StoryRailModelProviders"
$env:PYTHONUNBUFFERED = "1"
# Keep this file pure ASCII (PowerShell 5.1 reads BOM-less .ps1 as ANSI).
# Task Scheduler's RestartCount only covers a task that fails to launch, not a
# server that exits later, so this wrapper restarts the server itself: wait 10
# seconds after a non-zero exit, give up after 5 restarts within 10 minutes.
# stop_services.ps1 and install_scheduled_task.ps1 stop the task (this wrapper)
# before killing the server, so a deliberate stop is never restarted here.
# Each start rotates the logs, keeping the previous (possibly crashed) run as
# .prev.log. Start-Process writes stderr to a file instead of turning it into
# terminating PowerShell errors.
$OutLog = Join-Path $StateRoot "server.out.log"
$ErrLog = Join-Path $StateRoot "server.err.log"
$Restarts = @()
while ($true) {
    foreach ($Log in @($OutLog, $ErrLog)) {
        if (Test-Path -LiteralPath $Log -PathType Leaf) {
            Move-Item -LiteralPath $Log -Destination ($Log -replace "\.log$", ".prev.log") -Force
        }
    }
    $Server = Start-Process -FilePath $Python -NoNewWindow -PassThru `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -ArgumentList @(
            "-m", "default_model_providers_implement.server",
            "--host", $ListenAddress,
            "--port", "8791",
            "--state-root", $StateRoot,
            "--services", "mock,h3_fl2va,h3_ref2va,breeze_tts_2,indextts2,seedvr2_7b_sharp_fp8,stable_audio_3,qwen_image",
            "--resource-name", "exclusive_gpu",
            "--auth-token-env", "STORYRAIL_MODEL_SERVICE_TOKEN",
            "--controller-lease-timeout-seconds", "20"
        )
    # Cache the handle before waiting: Windows PowerShell 5.1 otherwise may report
    # a null ExitCode, and Start-Process -Wait would also wait for child runtimes.
    $null = $Server.Handle
    $Server.WaitForExit()
    $ExitCode = $Server.ExitCode
    if ($null -eq $ExitCode) {
        $ExitCode = 1
    }
    if ($ExitCode -eq 0) {
        exit 0
    }
    $Now = Get-Date
    $Restarts = @($Restarts | Where-Object { $_ -gt $Now.AddMinutes(-10) }) + @($Now)
    if ($Restarts.Count -gt 5) {
        exit $ExitCode
    }
    Start-Sleep -Seconds 10
}
