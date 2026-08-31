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

Xvfb "$DISPLAY" -screen 0 1280x800x24 -nolisten tcp -ac &
xvfb_pid=$!

for _attempt in $(seq 1 100); do
    if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
        break
    fi
    sleep 0.1
done
if ! xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
    echo "The virtual X display did not start" >&2
    kill "$xvfb_pid" 2>/dev/null || true
    wait "$xvfb_pid" 2>/dev/null || true
    exit 1
fi

openbox &
window_manager_pid=$!
if [[ "$side" == "computer-a" ]]; then
    /usr/local/bin/work-transfer \
        --logo /usr/local/share/work-transfer/work-transfer-mark.svg &
else
    pcmanfm --no-desktop "$HOME/library-updates" &
fi
application_pid=$!

# DEMO ONLY: noVNC is passwordless. Compose publishes the proxy only on host
# loopback, and the raw VNC port is never exposed.
x11vnc \
    -display "$DISPLAY" \
    -rfbport 5900 \
    -forever \
    -shared \
    -nopw \
    -localhost \
    -noxdamage &
vnc_pid=$!

websockify --web=/usr/share/novnc 6080 127.0.0.1:5900 &
web_proxy_pid=$!

# shellcheck disable=SC2329  # Invoked indirectly by the signal traps below.
cleanup() {
    trap - EXIT INT TERM
    kill \
        "$web_proxy_pid" \
        "$vnc_pid" \
        "$application_pid" \
        "$window_manager_pid" \
        "$xvfb_pid" \
        2>/dev/null || true
    wait "$web_proxy_pid" 2>/dev/null || true
    wait "$vnc_pid" 2>/dev/null || true
    wait "$application_pid" 2>/dev/null || true
    wait "$window_manager_pid" 2>/dev/null || true
    wait "$xvfb_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

set +e
wait -n \
    "$xvfb_pid" \
    "$window_manager_pid" \
    "$application_pid" \
    "$vnc_pid" \
    "$web_proxy_pid"
status=$?
set -e
if ((status == 0)); then
    status=1
fi
exit "$status"
