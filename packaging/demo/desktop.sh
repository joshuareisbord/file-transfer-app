#!/usr/bin/env bash
set -euo pipefail

export DISPLAY=:99
export HOME=/home/demo
export LOGNAME=demo
export USER=demo
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_RUNTIME_DIR=/tmp/work-transfer-demo-runtime
readonly side="${1:?Demo side is required}"

case "$side" in
    computer-a|computer-b) ;;
    *)
        echo "Demo side must be computer-a or computer-b" >&2
        exit 2
        ;;
esac

install -d -m 700 "$XDG_CONFIG_HOME" "$XDG_RUNTIME_DIR"

# Xtigervnc is both the virtual X server and the VNC framebuffer. Keeping those
# roles in one supported Ubuntu package avoids scraper-specific capture failures
# when the amd64 demo image runs under emulation on an arm Docker host.
Xtigervnc \
    -geometry 1280x800 \
    -depth 24 \
    -rfbport 5900 \
    -SecurityTypes None \
    -localhost \
    -AlwaysShared \
    -nolisten tcp \
    -ac \
    "$DISPLAY" &
x_server_pid=$!

for _attempt in $(seq 1 100); do
    if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
        break
    fi
    sleep 0.1
done
if ! xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
    echo "The virtual X display did not start" >&2
    kill "$x_server_pid" 2>/dev/null || true
    wait "$x_server_pid" 2>/dev/null || true
    exit 1
fi

openbox &
window_manager_pid=$!

# Wait for Openbox to own the root window before starting the fast FLTK app.
# Otherwise its initial map request can be lost under amd64 emulation.
window_manager_ready=false
for _attempt in $(seq 1 100); do
    if xprop -display "$DISPLAY" -root _NET_SUPPORTING_WM_CHECK \
        2>/dev/null \
        | grep -Eq 'window id # 0x[1-9A-Fa-f][0-9A-Fa-f]*'; then
        window_manager_ready=true
        break
    fi
    if ! kill -0 "$window_manager_pid" 2>/dev/null; then
        break
    fi
    sleep 0.1
done
if [[ "$window_manager_ready" != true ]]; then
    echo "The window manager did not become ready" >&2
    kill "$window_manager_pid" "$x_server_pid" 2>/dev/null || true
    wait "$window_manager_pid" 2>/dev/null || true
    wait "$x_server_pid" 2>/dev/null || true
    exit 1
fi

if [[ "$side" == "computer-a" ]]; then
    /usr/local/bin/work-transfer \
        --logo /usr/local/share/work-transfer/work-transfer-mark.svg &
else
    pcmanfm --no-desktop "$HOME" &
fi
application_pid=$!

websockify --web=/usr/share/novnc 6080 127.0.0.1:5900 &
web_proxy_pid=$!

# shellcheck disable=SC2329  # Invoked indirectly by the signal traps below.
cleanup() {
    trap - EXIT INT TERM
    kill \
        "$web_proxy_pid" \
        "$application_pid" \
        "$window_manager_pid" \
        "$x_server_pid" \
        2>/dev/null || true
    wait "$web_proxy_pid" 2>/dev/null || true
    wait "$application_pid" 2>/dev/null || true
    wait "$window_manager_pid" 2>/dev/null || true
    wait "$x_server_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

set +e
wait -n \
    "$x_server_pid" \
    "$window_manager_pid" \
    "$application_pid" \
    "$web_proxy_pid"
status=$?
set -e
if ((status == 0)); then
    status=1
fi
exit "$status"
