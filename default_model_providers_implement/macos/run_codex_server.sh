#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repository_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
python="$repository_root/.venv/bin/python"

if [ ! -x "$python" ]; then
    echo "缺少 StoryRail .venv；请先安装 codex optional dependency。" >&2
    exit 2
fi

export PYTHONPATH="$repository_root"
export STORYRAIL_CODEX_OUTPUT_ROOT="${STORYRAIL_CODEX_OUTPUT_ROOT:-$HOME/.codex/generated_images}"
export STORYRAIL_AGY_OUTPUT_ROOT="${STORYRAIL_AGY_OUTPUT_ROOT:-$HOME/.gemini/antigravity-cli/brain}"
# launchd 不继承交互式 shell 的 PATH；最终装配 worker 需要发现 Homebrew 的
# ffmpeg/ffprobe。Intel 与 Apple Silicon 的常见安装位置都显式列出。
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
export STORYRAIL_FFPROBE="${STORYRAIL_FFPROBE:-/opt/homebrew/bin/ffprobe}"
export STORYRAIL_DEMUCS_PYTHON="${STORYRAIL_DEMUCS_PYTHON:-$repository_root/.demucs-venv/bin/python}"

exec "$python" -m default_model_providers_implement.server \
    --host 127.0.0.1 \
    --port 8792 \
    --state-root "$repository_root/var/codex-image-provider" \
    --services codex_image_generate,codex_image_edit,agy_image_generate,agy_image_edit,ffmpeg_final_assembly,ffmpeg_animatic,ffmpeg_video_frame,ffmpeg_pano_view,demucs_audio_separation,ffmpeg_audio_remix \
    --lane network_image:4:codex_image_generate,codex_image_edit,agy_image_generate,agy_image_edit \
    --lane mac_heavy:1:demucs_audio_separation,ffmpeg_audio_remix,ffmpeg_animatic,ffmpeg_final_assembly \
    --lane mac_light:1:ffmpeg_video_frame,ffmpeg_pano_view
