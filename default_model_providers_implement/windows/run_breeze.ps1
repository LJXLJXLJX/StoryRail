param(
    [ValidateSet("127.0.0.1", "0.0.0.0")]
    [string]$ListenAddress = "127.0.0.1",
    [int]$Port = 7860
)

$ErrorActionPreference = "Stop"

# Breeze is an existing WSL deployment. This launcher deliberately does not
# clone the repository, create a venv, install packages, or enable flash-attn.
$Distribution = "Ubuntu"
$Repository = "/home/ljx/ai/breeze-tts"
$Python = "$Repository/.venv/bin/python"
$Model = "/home/ljx/ai/models/Breeze-TTS-2"

$Probe = "test -x '$Python' && test -d '$Model' && test -f '$Repository/breeze_infer/api.py'"
& wsl.exe -d $Distribution -- /bin/bash -lc $Probe
if ($LASTEXITCODE -ne 0) {
    throw "Breeze WSL deployment preflight failed: $Repository or $Model is unavailable."
}

$Command = "cd '$Repository' && exec '$Python' -m breeze_infer.api '$Model' --host '$ListenAddress' --port $Port --fast-all"
& wsl.exe -d $Distribution -- /bin/bash -lc $Command
if ($LASTEXITCODE -ne 0) {
    throw "Breeze TTS 2 API exited with code $LASTEXITCODE."
}
