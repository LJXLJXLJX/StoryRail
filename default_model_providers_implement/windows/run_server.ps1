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
& $Python -m default_model_providers_implement.server `
    --host $ListenAddress `
    --port 8791 `
    --state-root "E:\StoryRailModelProviders" `
    --services "mock,h3_fl2va,h3_ref2va,breeze_tts_2,indextts2,seedvr2_7b_sharp_fp8,stable_audio_3,qwen_image" `
    --resource-name "exclusive_gpu" `
    --auth-token-env "STORYRAIL_MODEL_SERVICE_TOKEN" `
    --controller-lease-timeout-seconds 20
