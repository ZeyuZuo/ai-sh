#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    printf 'usage: %s PATH_TO_WHEEL\n' "$0" >&2
    exit 2
fi

wheel_path=$(realpath "$1")
smoke_dir=$(mktemp -d)
trap 'rm -rf "$smoke_dir"' EXIT

python -m venv "$smoke_dir/venv"
"$smoke_dir/venv/bin/pip" install --quiet "$wheel_path"

tmksh="$smoke_dir/venv/bin/tmksh"
"$tmksh" --help >/dev/null
"$tmksh" config --show >/dev/null
"$tmksh" ask --help >/dev/null
"$tmksh" suggest --help >/dev/null
"$tmksh" init bash >/dev/null
"$tmksh" init zsh >/dev/null
"$tmksh" init fish >/dev/null
