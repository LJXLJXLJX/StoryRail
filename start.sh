#!/bin/bash

set -Eeuo pipefail

ROOT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 本机部署配置（Git 忽略）：可在其中设置下文的 SLATEHAND_* 变量，格式见 start.local.env.example。
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
DEBUG_PORT="${SLATEHAND_DEBUG_PORT:-}"

LOCAL_CONNECTION_DIRECTORY="$ROOT_DIRECTORY/var/local-connection"
local_connection=1
for argument in "$@"; do
    if [[ "$argument" == --access-policy-file* ]]; then local_connection=0; fi
done
core_arguments=(-m server)
if [[ "$local_connection" == 1 ]]; then
    core_arguments+=(--local-connection-directory "$LOCAL_CONNECTION_DIRECTORY")
fi
# Provider 目录：命令行 --provider-dir（相对当前目录，可重复）在前，start.local.env 的
# SLATEHAND_PROVIDER_DIRS（冒号分隔，相对本仓库）在后；顺序即同一能力的默认优先级。
provider_directories=()
passthrough_arguments=()
add_provider_directory() {
    local resolved
    resolved="$(cd "$1" 2>/dev/null && pwd)" || {
        printf '\n启动失败：Provider 目录不存在：%s\n' "$1" >&2
        exit 1
    }
    provider_directories+=("$resolved")
}
parse_arguments() {
    local directory
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --provider-dir)
                [[ $# -ge 2 ]] || { printf '用法：start.sh [--provider-dir DIR]... [Core 参数]\n' >&2; exit 2; }
                add_provider_directory "$2"
                shift 2
                ;;
            --provider-dir=*)
                add_provider_directory "${1#--provider-dir=}"
                shift
                ;;
            *)
                passthrough_arguments+=("$1")
                shift
                ;;
        esac
    done
    if [[ -n "${SLATEHAND_PROVIDER_DIRS:-}" ]]; then
        IFS=':' read -r -a configured_directories <<< "$SLATEHAND_PROVIDER_DIRS"
        for directory in "${configured_directories[@]}"; do
            [[ -n "$directory" ]] || continue
            [[ "$directory" == /* ]] || directory="$ROOT_DIRECTORY/$directory"
            add_provider_directory "$directory"
        done
    fi
}
parse_arguments "$@"
for directory in "${provider_directories[@]+"${provider_directories[@]}"}"; do
    core_arguments+=(--provider-dir "$directory")
done
core_arguments+=("${passthrough_arguments[@]+"${passthrough_arguments[@]}"}")

backend_pid=""
frontend_pid=""

say_error() {
    printf '\n启动失败：%s\n' "$1" >&2
    exit 1
}

cleanup() {
    local pid
    trap - EXIT
    # Core 收到 SIGTERM 后按逆序关闭 Provider 服务（可能经 SSH 停止远端节点），需等待它退出。
    for pid in "$frontend_pid" "$backend_pid"; do
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    for pid in "$frontend_pid" "$backend_pid"; do
        if [[ -n "$pid" ]]; then
            wait "$pid" 2>/dev/null || true
        fi
    done
}

port_is_in_use() {
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
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

[[ -x "$PYTHON_EXECUTABLE" ]] || say_error "未找到 .venv。请先创建 Python 虚拟环境并安装 Core（见 README 快速开始）。"
command -v npm >/dev/null 2>&1 || say_error "未找到 npm，请先安装 Node.js。"
command -v curl >/dev/null 2>&1 || say_error "未找到 curl。"
command -v lsof >/dev/null 2>&1 || say_error "未找到 lsof。"

if [[ "$local_connection" == 1 && -S "$LOCAL_CONNECTION_DIRECTORY/control.sock" ]] && port_is_in_use 8765 && port_is_in_use 5173; then
    "$PYTHON_EXECUTABLE" -m integrations.agent_launcher --socket "$LOCAL_CONNECTION_DIRECTORY/control.sock" --open-browser
    exit 0
fi

port_is_in_use 8765 && say_error "端口 8765 已被占用，可能已有 Slatehand Core 正在运行。"
port_is_in_use 5173 && say_error "端口 5173 已被占用，可能已有 Slatehand Web 正在运行。"

if [[ -n "$DEBUG_PORT" ]]; then
    [[ "$DEBUG_PORT" =~ ^[0-9]+$ ]] || say_error "SLATEHAND_DEBUG_PORT 必须是端口号。"
    (( 10#$DEBUG_PORT >= 1 && 10#$DEBUG_PORT <= 65535 )) || say_error "调试端口必须在 1 到 65535 之间。"
    port_is_in_use "$DEBUG_PORT" && say_error "调试端口 $DEBUG_PORT 已被占用。"
    "$PYTHON_EXECUTABLE" -c 'import debugpy' >/dev/null 2>&1 || \
        say_error "当前 .venv 未安装 debugpy，请运行 .venv/bin/pip install -e '.[dev]'。"
fi

if [[ ! -x "$VITE_EXECUTABLE" ]]; then
    printf '首次启动：正在安装 Web 依赖……\n'
    (cd "$WEB_DIRECTORY" && npm ci)
fi

printf '正在构建 Slatehand Web……\n'
(cd "$WEB_DIRECTORY" && npm run build)

if [[ ${#provider_directories[@]} -eq 0 ]]; then
    printf '未指定 Provider 目录：只有本机 ffmpeg 工具可用。用 --provider-dir 或 start.local.env 的 SLATEHAND_PROVIDER_DIRS 加载 Provider。\n'
fi

printf '正在启动 Slatehand Core……\n'
if [[ -n "$DEBUG_PORT" ]]; then
    printf 'Python 调试端口：127.0.0.1:%s（Core 不等待调试器，可随时 Attach）\n' "$DEBUG_PORT"
    "$PYTHON_EXECUTABLE" -Xfrozen_modules=off -m debugpy \
        --listen "127.0.0.1:$DEBUG_PORT" "${core_arguments[@]}" &
else
    "$PYTHON_EXECUTABLE" "${core_arguments[@]}" &
fi
backend_pid=$!
# Core 先绑定端口，再等待 Provider 服务就绪（可能经 SSH 拉起远端节点）后才开始响应。
if [[ "$local_connection" == 1 ]]; then
    wait_until_ready "Slatehand Core" "$API_URL/api/local-connection" "$backend_pid"
else
    # 受保护部署的 /api/projects 不提供匿名健康检查。
    for ((attempt = 1; attempt <= 60; attempt += 1)); do
        kill -0 "$backend_pid" 2>/dev/null || say_error "Slatehand Core 启动失败。"
        port_is_in_use 8765 && break
        sleep 0.5
    done
    port_is_in_use 8765 || say_error "等待 Slatehand Core 就绪超时。"
fi

printf '正在启动 Slatehand Web……\n'
(cd "$WEB_DIRECTORY" && exec "$VITE_EXECUTABLE" preview --host 127.0.0.1 --port 5173 --strictPort) &
frontend_pid=$!
wait_until_ready "Slatehand Web" "$WEB_URL" "$frontend_pid"

printf '\nSlatehand 已启动：%s\n' "$WEB_URL"
printf '在引用库页面选择 Pi，可复制当前项目的启动命令。\n'
printf '按 Ctrl+C 可同时停止 Core 和 Web。\n\n'

if [[ "${SLATEHAND_NO_BROWSER:-0}" != "1" ]]; then
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
    say_error "Slatehand Core 意外退出。"
fi

wait "$frontend_pid" || true
say_error "Slatehand Web 意外退出。"
