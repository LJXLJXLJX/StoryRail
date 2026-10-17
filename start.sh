#!/bin/bash

set -Eeuo pipefail

ROOT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 本机部署配置（Git 忽略）：可在其中设置下文的 STORYRAIL_* 变量，格式见 start.local.env.example。
LOCAL_ENV_FILE="$ROOT_DIRECTORY/start.local.env"
if [[ -f "$LOCAL_ENV_FILE" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$LOCAL_ENV_FILE"
    set +a
fi
PYTHON_EXECUTABLE="$ROOT_DIRECTORY/.venv/bin/python"
WEB_DIRECTORY="$ROOT_DIRECTORY/web"
VITE_EXECUTABLE="$WEB_DIRECTORY/node_modules/.bin/vite"
API_URL="http://127.0.0.1:8765"
WEB_URL="http://127.0.0.1:5173"
DEBUG_PORT="${STORYRAIL_DEBUG_PORT:-}"
WINDOWS_MODEL_TOKEN_FILE="$ROOT_DIRECTORY/var/secrets/windows-model-service-token"
WINDOWS_RUNTIME_ENDPOINT="${STORYRAIL_WINDOWS_RUNTIME_ENDPOINT:-}"
WINDOWS_PROVIDER_AUTOSTART="${STORYRAIL_AUTOSTART_WINDOWS_PROVIDER:-1}"
WINDOWS_SSH_TARGET="${STORYRAIL_WINDOWS_SSH_TARGET:-}"
WINDOWS_REPOSITORY_ROOT="${STORYRAIL_WINDOWS_REPOSITORY_ROOT:-}"
WINDOWS_LISTEN_ADDRESS="${STORYRAIL_WINDOWS_LISTEN_ADDRESS:-}"
WINDOWS_STOP_SCRIPT="${WINDOWS_REPOSITORY_ROOT}\\default_model_providers_implement\\windows\\stop_services.ps1"
BREEZE_ENDPOINT="${STORYRAIL_BREEZE_ENDPOINT:-$WINDOWS_RUNTIME_ENDPOINT}"
MAC_PROVIDER_AUTOSTART="${STORYRAIL_AUTOSTART_MAC_PROVIDER:-1}"
MAC_PROVIDER_LABEL="com.storyrail.codex-image"
MAC_PROVIDER_INSTALL_SCRIPT="$ROOT_DIRECTORY/default_model_providers_implement/macos/install_launch_agent.sh"
MAC_PROVIDER_PORT="${STORYRAIL_MAC_PROVIDER_PORT:-8792}"
WHISPER_ENDPOINT="${STORYRAIL_WHISPER_ENDPOINT:-}"
WHISPER_MODEL="${STORYRAIL_WHISPER_MODEL:-$ROOT_DIRECTORY/var/whisper-asr/ggml-large-v3-turbo-q5_0.bin}"
WHISPER_SERVER_BIN="${STORYRAIL_WHISPER_SERVER:-}"
WHISPER_AUTOSTART=0

if [[ -z "$WHISPER_SERVER_BIN" ]] && command -v whisper-server >/dev/null 2>&1; then
    WHISPER_SERVER_BIN="$(command -v whisper-server)"
fi
if [[ -z "$WHISPER_ENDPOINT" && -x "$WHISPER_SERVER_BIN" && -f "$WHISPER_MODEL" ]]; then
    WHISPER_ENDPOINT="http://127.0.0.1:8793"
    WHISPER_AUTOSTART=1
fi

LOCAL_CONNECTION_DIRECTORY="$ROOT_DIRECTORY/var/local-connection"
local_connection=1
for argument in "$@"; do
    if [[ "$argument" == --access-policy-file* ]]; then local_connection=0; fi
done
core_arguments=(-m server)
if [[ "$local_connection" == 1 ]]; then
    core_arguments+=(--local-connection-directory "$LOCAL_CONNECTION_DIRECTORY")
fi
if [[ -f "$WINDOWS_MODEL_TOKEN_FILE" ]]; then
    core_arguments+=(--breeze-endpoint "$BREEZE_ENDPOINT")
    core_arguments+=(--windows-runtime-endpoint "$WINDOWS_RUNTIME_ENDPOINT" --windows-runtime-token-file "$WINDOWS_MODEL_TOKEN_FILE")
fi
if [[ -n "$WHISPER_ENDPOINT" ]]; then
    core_arguments+=(--whisper-endpoint "$WHISPER_ENDPOINT")
fi
core_arguments+=("$@")

backend_pid=""
frontend_pid=""
whisper_pid=""
mac_provider_started=0
windows_provider_started=0

stop_mac_provider() {
    if [[ "$mac_provider_started" == "1" ]]; then
        launchctl bootout "gui/$(id -u)/$MAC_PROVIDER_LABEL" 2>/dev/null || true
    fi
}

run_windows_provider_script() {
    local script_path="$1"
    local listen_address="${2:-}"
    local encoded_command

    encoded_command="$("$PYTHON_EXECUTABLE" -c '
import base64
import sys


def quote(value: str) -> str:
    return "\x27" + value.replace("\x27", "\x27\x27") + "\x27"


script_path = quote(sys.argv[1])
listen_address = sys.argv[2]
arguments = ""
if listen_address:
    arguments = " -ListenAddress " + quote(listen_address)
command = f"""
$ErrorActionPreference = \"Stop\"
$ProgressPreference = \"SilentlyContinue\"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
[System.Globalization.CultureInfo]::CurrentCulture = [System.Globalization.CultureInfo]::GetCultureInfo(\"en-US\")
[System.Globalization.CultureInfo]::CurrentUICulture = [System.Globalization.CultureInfo]::GetCultureInfo(\"en-US\")
try {{
    $scriptPath = {script_path}
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {{
        throw \"Windows Provider script not found: $scriptPath\"
    }}
    & $scriptPath{arguments}
    if (-not $?) {{ exit 1 }}
}} catch {{
    [Console]::Error.WriteLine(\"Windows Provider command failed: \" + $_.Exception.Message)
    exit 1
}}
"""
print(base64.b64encode(command.encode("utf-16le")).decode("ascii"))
' "$script_path" "$listen_address")"
    ssh -o BatchMode=yes -o ConnectTimeout=15 "$WINDOWS_SSH_TARGET" \
        powershell.exe -NoProfile -NonInteractive -OutputFormat Text -ExecutionPolicy Bypass \
        -EncodedCommand "$encoded_command"
}

stop_windows_provider() {
    if [[ "$windows_provider_started" == "1" ]]; then
        printf '正在通过 %s 关闭 Windows Model Provider……\n' "$WINDOWS_SSH_TARGET"
        run_windows_provider_script "$WINDOWS_STOP_SCRIPT" >/dev/null || \
            printf '警告：Windows Model Provider 未能通过 stop_services.ps1 确认关闭。\n' >&2
    fi
}

say_error() {
    printf '\n启动失败：%s\n' "$1" >&2
    exit 1
}

cleanup() {
    local pid
    trap - EXIT
    for pid in "$frontend_pid" "$backend_pid" "$whisper_pid"; do
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    for pid in "$frontend_pid" "$backend_pid" "$whisper_pid"; do
        if [[ -n "$pid" ]]; then
            wait "$pid" 2>/dev/null || true
        fi
    done
    stop_mac_provider
    stop_windows_provider
}

port_is_in_use() {
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

wait_until_reachable() {
    local name="$1"
    local url="$2"
    local attempts="${3:-120}"
    local attempt

    for ((attempt = 1; attempt <= attempts; attempt += 1)); do
        if curl --silent --show-error --max-time 3 "$url" >/dev/null 2>&1; then
            return
        fi
        sleep 0.5
    done
    say_error "等待 $name 可达超时：$url"
}

restart_windows_provider() {
    [[ "$WINDOWS_PROVIDER_AUTOSTART" == "1" ]] || return 0
    command -v ssh >/dev/null 2>&1 || say_error "未找到 ssh，无法重启 Windows Provider。"
    [[ -f "$WINDOWS_MODEL_TOKEN_FILE" ]] || \
        say_error "缺少 Windows Provider Token；无法启动完整服务。"
    [[ -n "$WINDOWS_SSH_TARGET" && -n "$WINDOWS_REPOSITORY_ROOT" && -n "$WINDOWS_LISTEN_ADDRESS" ]] || \
        say_error "自动重启 Windows Provider 需要在 start.local.env 设置 STORYRAIL_WINDOWS_SSH_TARGET、STORYRAIL_WINDOWS_REPOSITORY_ROOT 与 STORYRAIL_WINDOWS_LISTEN_ADDRESS；不需要自动重启时设 STORYRAIL_AUTOSTART_WINDOWS_PROVIDER=0。"
    printf '正在通过 %s 重启 Windows Model Provider……\n' "$WINDOWS_SSH_TARGET"
    run_windows_provider_script \
        "${WINDOWS_REPOSITORY_ROOT}\\default_model_providers_implement\\windows\\install_scheduled_task.ps1" \
        "$WINDOWS_LISTEN_ADDRESS" || \
        say_error "Windows Model Provider 重启失败。"
    windows_provider_started=1
    wait_until_reachable "Windows Model Provider" "$WINDOWS_RUNTIME_ENDPOINT/"
    wait_until_reachable "Windows Breeze TTS 2" "$BREEZE_ENDPOINT/"
}

restart_mac_provider() {
    [[ "$MAC_PROVIDER_AUTOSTART" == "1" ]] || return 0
    [[ -x "$MAC_PROVIDER_INSTALL_SCRIPT" ]] || \
        say_error "缺少 Mac Provider 启动脚本：$MAC_PROVIDER_INSTALL_SCRIPT"
    printf '正在重启本机 Mac Model Provider……\n'
    mac_provider_started=1
    "$MAC_PROVIDER_INSTALL_SCRIPT" >/dev/null
    wait_until_reachable "Mac Model Provider" "http://127.0.0.1:$MAC_PROVIDER_PORT/"
}

# $4 可选：就绪尝试次数（每次间隔 0.5s，缺省 60 次 = 30s）。
wait_until_ready() {
    local name="$1"
    local url="$2"
    local pid="$3"
    local attempts="${4:-60}"
    local attempt

    for ((attempt = 1; attempt <= attempts; attempt += 1)); do
        if ! kill -0 "$pid" 2>/dev/null; then
            wait "$pid" || true
            say_error "$name 在启动过程中退出。"
        fi
        if curl --fail --silent --show-error "$url" >/dev/null 2>&1; then
            return
        fi
        sleep 0.5
    done
    say_error "等待 $name 就绪超时。"
}

trap cleanup EXIT
trap 'exit 130' INT TERM HUP

cd "$ROOT_DIRECTORY"

[[ -x "$PYTHON_EXECUTABLE" ]] || say_error "未找到 .venv。请先创建 Python 虚拟环境并安装 storyrail[mcp]。"
command -v npm >/dev/null 2>&1 || say_error "未找到 npm，请先安装 Node.js。"
command -v curl >/dev/null 2>&1 || say_error "未找到 curl。"
command -v lsof >/dev/null 2>&1 || say_error "未找到 lsof。"

if [[ "$local_connection" == 1 && -S "$LOCAL_CONNECTION_DIRECTORY/control.sock" ]] && port_is_in_use 8765 && port_is_in_use 5173; then
    "$PYTHON_EXECUTABLE" -m integrations.agent_launcher --socket "$LOCAL_CONNECTION_DIRECTORY/control.sock" --open-browser
    exit 0
fi

port_is_in_use 8765 && say_error "端口 8765 已被占用，可能已有 StoryRail Core 正在运行。"
port_is_in_use 5173 && say_error "端口 5173 已被占用，可能已有 StoryRail Web 正在运行。"

if [[ -f "$WINDOWS_MODEL_TOKEN_FILE" ]]; then
    [[ -n "$WINDOWS_RUNTIME_ENDPOINT" ]] || \
        say_error "已有 Windows Provider Token，但未设置 STORYRAIL_WINDOWS_RUNTIME_ENDPOINT（写入 start.local.env）。"
fi

restart_windows_provider
restart_mac_provider

if [[ -n "$DEBUG_PORT" ]]; then
    [[ "$DEBUG_PORT" =~ ^[0-9]+$ ]] || say_error "STORYRAIL_DEBUG_PORT 必须是端口号。"
    (( 10#$DEBUG_PORT >= 1 && 10#$DEBUG_PORT <= 65535 )) || say_error "调试端口必须在 1 到 65535 之间。"
    port_is_in_use "$DEBUG_PORT" && say_error "调试端口 $DEBUG_PORT 已被占用。"
    "$PYTHON_EXECUTABLE" -c 'import debugpy' >/dev/null 2>&1 || \
        say_error "当前 .venv 未安装 debugpy，请运行 .venv/bin/pip install -e '.[dev]'。"
fi

if [[ ! -x "$VITE_EXECUTABLE" ]]; then
    printf '首次启动：正在安装 Web 依赖……\n'
    (cd "$WEB_DIRECTORY" && npm ci)
fi

if [[ "$WHISPER_AUTOSTART" == 1 ]]; then
    port_is_in_use 8793 && say_error "端口 8793 已被占用，无法启动本机 Whisper ASR。"
    printf '正在启动本机 Whisper ASR……\n'
    # 独立 session 避免终端 Ctrl+C 与 cleanup 向 Provider 重复发信号。
    "$PYTHON_EXECUTABLE" -c \
        'import os, sys; os.setsid(); os.execv(sys.argv[1], sys.argv[1:])' \
        "$WHISPER_SERVER_BIN" --host 127.0.0.1 --port 8793 \
        --model "$WHISPER_MODEL" --language auto --flash-attn &
    whisper_pid=$!
    # 574MB 模型首次加载可能明显慢于 30s 默认预算；给 240s，并提示可跳过。
    printf '首次加载 Whisper 模型可能较慢；如需跳过本机 Whisper，可设 STORYRAIL_WHISPER_ENDPOINT。\n'
    wait_until_ready "Whisper ASR" "$WHISPER_ENDPOINT/" "$whisper_pid" 480
elif [[ -z "$WHISPER_ENDPOINT" ]]; then
    printf '未发现本机 Whisper ASR 与模型；Breeze 参考文字仍可手工填写。\n'
fi

printf '正在构建 StoryRail Web……\n'
(cd "$WEB_DIRECTORY" && npm run build)

printf '正在启动 StoryRail Core……\n'
if [[ -n "$DEBUG_PORT" ]]; then
    printf 'Python 调试端口：127.0.0.1:%s（Core 不等待调试器，可随时 Attach）\n' "$DEBUG_PORT"
    "$PYTHON_EXECUTABLE" -Xfrozen_modules=off -m debugpy \
        --listen "127.0.0.1:$DEBUG_PORT" "${core_arguments[@]}" &
else
    "$PYTHON_EXECUTABLE" "${core_arguments[@]}" &
fi
backend_pid=$!
if [[ "$local_connection" == 1 ]]; then
    wait_until_ready "StoryRail Core" "$API_URL/api/local-connection" "$backend_pid"
else
    # 受保护部署的 /api/projects 不提供匿名健康检查。
    for ((attempt = 1; attempt <= 60; attempt += 1)); do
        kill -0 "$backend_pid" 2>/dev/null || say_error "StoryRail Core 启动失败。"
        port_is_in_use 8765 && break
        sleep 0.5
    done
    port_is_in_use 8765 || say_error "等待 StoryRail Core 就绪超时。"
fi

printf '正在启动 StoryRail Web……\n'
(cd "$WEB_DIRECTORY" && exec "$VITE_EXECUTABLE" preview --host 127.0.0.1 --port 5173 --strictPort) &
frontend_pid=$!
wait_until_ready "StoryRail Web" "$WEB_URL" "$frontend_pid"

printf '\nStoryRail 已启动：%s\n' "$WEB_URL"
printf '在引用库页面选择 Pi，可复制当前项目的启动命令。\n'
printf '按 Ctrl+C 可同时停止 Core 和 Web。\n\n'

if [[ "${STORYRAIL_NO_BROWSER:-0}" != "1" ]]; then
    if [[ "$local_connection" == 1 ]]; then
        "$PYTHON_EXECUTABLE" -m integrations.agent_launcher --socket "$LOCAL_CONNECTION_DIRECTORY/control.sock" --open-browser
    elif command -v open >/dev/null 2>&1; then
        open "$WEB_URL"
    fi
fi

while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
    sleep 1
done

if ! kill -0 "$backend_pid" 2>/dev/null; then
    wait "$backend_pid" || true
    say_error "StoryRail Core 意外退出。"
fi

wait "$frontend_pid" || true
say_error "StoryRail Web 意外退出。"
