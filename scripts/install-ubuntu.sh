#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "$script_directory/.." && pwd)"
artifact="${1:-$project_directory/dist/work-transfer-ubuntu-amd64}"
desktop_entry="$project_directory/packaging/work-transfer.desktop"

if [[ ! -f "$artifact" || -L "$artifact" ]]; then
    echo "Executable not found: $artifact" >&2
    exit 1
fi
if [[ ! -f "$desktop_entry" || -L "$desktop_entry" ]]; then
    echo "Desktop entry not found: $desktop_entry" >&2
    exit 1
fi

if [ "$(uname -m)" != "x86_64" ]; then
    echo "This executable requires Ubuntu on amd64 (x86_64)." >&2
    exit 1
fi

artifact_sha256="$(sha256sum -- "$artifact" | awk '{print $1}')"
desktop_sha256="$(sha256sum -- "$desktop_entry" | awk '{print $1}')"
artifact_size="$(stat --format='%s' -- "$artifact")"
desktop_size="$(stat --format='%s' -- "$desktop_entry")"
if ((artifact_size <= 0 || desktop_size <= 0)); then
    echo "Installation sources must be non-empty regular files." >&2
    exit 1
fi
staging_directory=""
staged_artifact=""
staged_desktop_entry=""

# The root-owned staging directory closes the validation-to-install race. The
# selected paths are never reopened after the staged bytes pass self-check.
cleanup_staging() {
    if [[ -n "$staged_artifact" && -n "$staged_desktop_entry" ]]; then
        sudo rm -f -- "$staged_artifact" "$staged_desktop_entry" || true
    fi
    if [[ -n "$staging_directory" ]]; then
        sudo rmdir -- "$staging_directory" || true
    fi
}
trap cleanup_staging EXIT

sudo -v
sudo install -d -m 755 /opt/work-transfer
staging_directory="$(sudo mktemp -d /opt/work-transfer/.install.XXXXXX)"
staged_artifact="$staging_directory/work-transfer"
staged_desktop_entry="$staging_directory/work-transfer.desktop"

stage_unprivileged_source() {
    local source_path="$1"
    local staged_path="$2"
    local staged_mode="$3"
    local expected_size="$4"

    sudo install -m 600 /dev/null "$staged_path"
    if ! head --bytes="$expected_size" -- "$source_path" \
        | sudo tee -- "$staged_path" >/dev/null; then
        echo "Unable to copy installation source: $source_path" >&2
        exit 1
    fi
    sudo chmod "$staged_mode" "$staged_path"
}

# head opens each selected path with the invoking user's authority and limits
# the stream to its validated initial size. The privileged half opens only the
# unpredictable root-owned staging path, so a swap cannot make root read an
# arbitrary object or write an unbounded stream.
stage_unprivileged_source "$artifact" "$staged_artifact" 755 "$artifact_size"
stage_unprivileged_source \
    "$desktop_entry" "$staged_desktop_entry" 644 "$desktop_size"

staged_artifact_sha256="$(
    sudo sha256sum -- "$staged_artifact" | awk '{print $1}'
)"
staged_desktop_sha256="$(
    sudo sha256sum -- "$staged_desktop_entry" | awk '{print $1}'
)"
if [[ "$staged_artifact_sha256" != "$artifact_sha256" || \
    "$staged_desktop_sha256" != "$desktop_sha256" ]]; then
    echo "Installation source changed while it was being staged." >&2
    exit 1
fi

sudo chmod 755 "$staging_directory"
"$staged_artifact" --self-check

# Recheck the immutable staged copy after executing its self-check, then install
# only from that root-owned directory.
if [[ "$(sudo sha256sum -- "$staged_artifact" | awk '{print $1}')" != \
    "$artifact_sha256" || \
    "$(sudo sha256sum -- "$staged_desktop_entry" | awk '{print $1}')" != \
    "$desktop_sha256" ]]; then
    echo "Staged installation files changed during self-check." >&2
    exit 1
fi

sudo install -D -m 755 "$staged_artifact" /opt/work-transfer/work-transfer
sudo install -D -m 644 "$staged_desktop_entry" \
    /usr/share/applications/work-transfer.desktop

echo "Installed Work Transfer. Launch it from the application menu."
