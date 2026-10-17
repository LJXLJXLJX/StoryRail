param(
    [string]$TaskName = "StoryRail Default Model Providers",
    [string]$ComfyTaskName = "StoryRail ComfyUI FL2VA Runtime",
    [ValidatePattern("^(?!0\.0\.0\.0$)\d{1,3}(\.\d{1,3}){3}$")]
    [string]$ListenAddress = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$RunScript = Join-Path $PSScriptRoot "run_server.ps1"
if (-not (Test-Path -LiteralPath $RunScript -PathType Leaf)) {
    throw "run_server.ps1 is missing."
}

$Python = "E:\Programs\Dev\MiniForge3\envs\comfyui\python.exe"
$ComfyRoot = "E:\Project\ComfyUI"
$SeedVRRoot = "E:\Project\seedvr2"
$SeedVRModelRoot = Join-Path $SeedVRRoot "models\SEEDVR2"
$SeedVRPython = "E:\Programs\Dev\MiniForge3\envs\storyrail-seedvr2\python.exe"
$FFprobe = "E:\Programs\Dev\MiniForge3\envs\storyrail-seedvr2\Library\bin\ffprobe.exe"
$IndexRoot = "E:\Project\index-tts"
$IndexModelRoot = Join-Path $IndexRoot "checkpoints"
$StateRoot = "E:\StoryRailModelProviders"
$TokenFile = Join-Path $StateRoot "service-token.txt"
$DefenderScript = Join-Path $PSScriptRoot "configure_h3_defender_exclusions.ps1"
$H3ModelRoot = Join-Path $ComfyRoot "models"
$Required = @(
    $Python,
    (Join-Path $ComfyRoot "nodes.py"),
    $SeedVRPython,
    $FFprobe,
    (Join-Path $SeedVRRoot "inference_cli.py"),
    (Join-Path $SeedVRModelRoot "seedvr2_ema_7b_sharp_fp8_e4m3fn.safetensors"),
    (Join-Path $SeedVRModelRoot "ema_vae_fp16.safetensors"),
    $DefenderScript,
    (Join-Path $IndexRoot "indextts\infer_v2_5.py"),
    (Join-Path $IndexModelRoot "config.yaml"),
    (Join-Path $IndexModelRoot "gpt.pth"),
    (Join-Path $IndexModelRoot "s2mel.pth"),
    (Join-Path $IndexModelRoot "codec.pth"),
    (Join-Path $IndexModelRoot "wav2vec2bert_stats.pt"),
    (Join-Path $IndexModelRoot "multilingual_zh_ja_yue_char_del.tiktoken")
)
foreach ($Path in $Required) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Deployment preflight failed; missing: $Path"
    }
}
& wsl.exe -d Ubuntu --exec /usr/bin/test -x /mnt/e/Project/index-tts/.venv/bin/python
if ($LASTEXITCODE -ne 0) {
    throw "Deployment preflight failed; IndexTTS2.5 WSL Python is missing."
}
$ExpectedComfyRevision = "a7169322"
$ActualComfyRevision = (& git -C $ComfyRoot rev-parse HEAD).Trim()
if (-not $ActualComfyRevision.StartsWith($ExpectedComfyRevision)) {
    throw "Deployment preflight failed; ComfyUI revision must start with $ExpectedComfyRevision."
}
# The only custom node the fixed H3 graph loads (SelfLiftH3Sampler).
$SelfLiftRoot = Join-Path $ComfyRoot "custom_nodes\comfyui-SelfLift"
$ExpectedSelfLiftRevision = "835c3cf7"
$ActualSelfLiftRevision = (& git -C $SelfLiftRoot rev-parse HEAD).Trim()
if (-not $ActualSelfLiftRevision.StartsWith($ExpectedSelfLiftRevision)) {
    throw "Deployment preflight failed; comfyui-SelfLift revision must start with $ExpectedSelfLiftRevision."
}
New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
& $DefenderScript -Action Add -ModelRoot $H3ModelRoot -StateRoot $StateRoot
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}
$ExistingComfyTask = Get-ScheduledTask -TaskName $ComfyTaskName -ErrorAction SilentlyContinue
if ($ExistingComfyTask) {
    Stop-ScheduledTask -TaskName $ComfyTaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $ComfyTaskName -Confirm:$false
}
$ExistingBreezeTask = Get-ScheduledTask -TaskName "StoryRail Breeze TTS 2" -ErrorAction SilentlyContinue
if ($ExistingBreezeTask) {
    Stop-ScheduledTask -TaskName "StoryRail Breeze TTS 2" -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName "StoryRail Breeze TTS 2" -Confirm:$false
}
# Older deployments started Breeze as an independent WSL service.  Stop only
# that exact fixed command before handing ownership to the exclusive scheduler.
& wsl.exe -d Ubuntu --exec /bin/pkill -TERM -f "breeze_infer.api /home/ljx/ai/models/Breeze-TTS-2" 2>$null
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
if (-not (Test-Path -LiteralPath $TokenFile -PathType Leaf)) {
    $Bytes = New-Object byte[] 32
    $Generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $Generator.GetBytes($Bytes)
    } finally {
        $Generator.Dispose()
    }
    $Token = [Convert]::ToBase64String($Bytes)
    [System.IO.File]::WriteAllText(
        $TokenFile,
        $Token,
        [System.Text.Encoding]::ASCII
    )
}

$PowerShell = (Get-Command powershell.exe).Source
$Identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$UserSid = $Identity.User.Value
$Arguments = (
    "-NoProfile -ExecutionPolicy Bypass -File `"$RunScript`" " +
    "-ListenAddress `"$ListenAddress`""
)
$Action = New-ScheduledTaskAction -Execute $PowerShell -Argument $Arguments
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal `
    -UserId $UserSid `
    -LogonType S4U `
    -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "StoryRail private H3, Breeze TTS 2, IndexTTS2.5 and SeedVR2 model services; Breeze is lazy and scheduler-owned." `
    -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Output "Installed and started scheduled task: $TaskName"
