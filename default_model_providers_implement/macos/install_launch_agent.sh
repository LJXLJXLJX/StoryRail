#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repository_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
label="com.storyrail.codex-image"
agents_dir="$HOME/Library/LaunchAgents"
plist="$agents_dir/$label.plist"
log_dir="$repository_root/var/codex-image-provider"

mkdir -p "$agents_dir" "$log_dir"
sed \
    -e "s|__RUN_SCRIPT__|$script_dir/run_codex_server.sh|g" \
    -e "s|__LOG_DIR__|$log_dir|g" \
    "$script_dir/launch-agent.plist.template" > "$plist"

launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
attempt=0
while launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 50 ]; then
        echo "等待旧 LaunchAgent 退出超时。" >&2
        exit 3
    fi
    sleep 0.1
done
sleep 0.5
attempt=0
until launchctl bootstrap "gui/$(id -u)" "$plist"; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 5 ]; then
        echo "LaunchAgent bootstrap 连续失败。" >&2
        exit 4
    fi
    sleep 1
done
launchctl kickstart -k "gui/$(id -u)/$label"
echo "已安装并启动 LaunchAgent：$label"
