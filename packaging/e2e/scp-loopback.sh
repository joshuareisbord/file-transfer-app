#!/usr/bin/env bash
set -euo pipefail

test_executable="$1"
loopback_root=/tmp/work-transfer-scp-loopback
sshd_pid=""

cleanup() {
    if [ -n "$sshd_pid" ]; then
        kill "$sshd_pid" 2>/dev/null || true
        wait "$sshd_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT

install -d -m 755 "$loopback_root"
install -d -m 755 /run/sshd

if ! id work-transfer-e2e >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash work-transfer-e2e
fi
passwd --delete work-transfer-e2e

ssh-keygen -q -t ed25519 -N "" -f "$loopback_root/client_key"
install -d -m 700 -o work-transfer-e2e -g work-transfer-e2e \
    /home/work-transfer-e2e/.ssh
install -m 600 -o work-transfer-e2e -g work-transfer-e2e \
    "$loopback_root/client_key.pub" \
    /home/work-transfer-e2e/.ssh/authorized_keys
install -d -m 755 -o work-transfer-e2e -g work-transfer-e2e \
    "$loopback_root/received path;safe"
ssh-keygen -A

/usr/sbin/sshd -D -e \
    -p 2222 \
    -o ListenAddress=127.0.0.1 \
    -o PasswordAuthentication=no \
    -o PermitRootLogin=no \
    -o AllowUsers=work-transfer-e2e \
    -o PidFile="$loopback_root/sshd.pid" \
    >"$loopback_root/sshd.log" 2>&1 &
sshd_pid=$!

for _attempt in $(seq 1 50); do
    if ssh-keyscan -p 2222 127.0.0.1 \
        >"$loopback_root/known_hosts" 2>/dev/null; then
        break
    fi
    if ! kill -0 "$sshd_pid" 2>/dev/null; then
        cat "$loopback_root/sshd.log" >&2
        exit 1
    fi
    sleep 0.1
done
test -s "$loopback_root/known_hosts"

printf 'standalone C++ SCP loopback payload\n' >"$loopback_root/source.bin"
WORK_TRANSFER_RUN_SCP_LOOPBACK=1 "$test_executable"
