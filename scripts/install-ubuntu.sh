#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "$script_directory/.." && pwd)"
artifact="${1:-$project_directory/dist/work-transfer-ubuntu-amd64}"

if [ ! -f "$artifact" ]; then
    echo "Executable not found: $artifact" >&2
    exit 1
fi

sudo install -D -m 755 "$artifact" /opt/work-transfer/work-transfer
sudo install -D -m 644 \
    "$project_directory/packaging/work-transfer.desktop" \
    /usr/share/applications/work-transfer.desktop

echo "Installed Work Transfer. Launch it from the application menu."

