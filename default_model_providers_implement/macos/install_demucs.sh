#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repository_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
runtime="$repository_root/.demucs-venv"

python3 -m venv "$runtime"
"$runtime/bin/python" -m pip install --upgrade pip
"$runtime/bin/python" -m pip install "demucs==4.0.1"
"$runtime/bin/python" -m demucs --help >/dev/null
echo "Demucs runtime 已安装：$runtime"
