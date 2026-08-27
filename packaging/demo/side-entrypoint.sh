#!/usr/bin/env bash
set -euo pipefail

readonly demo_user="demo"
readonly demo_home="/home/$demo_user"
readonly key_directory="/demo-keys"
readonly side="${DEMO_SIDE:?DEMO_SIDE must identify this computer}"
readonly peer_host="${PEER_HOST:-}"
readonly peer_port="${PEER_PORT:-22}"

case "$side" in
    computer-a|computer-b) ;;
    *)
        echo "DEMO_SIDE must be computer-a or computer-b" >&2
        exit 2
        ;;
esac

if [[ -n "$peer_host" ]]; then
    case "$peer_host" in
        computer-a|computer-b) ;;
        *)
            echo "PEER_HOST must be computer-a or computer-b" >&2
            exit 2
            ;;
    esac
    if [[ "$peer_host" == "$side" ]]; then
        echo "PEER_HOST must identify the other demo computer" >&2
        exit 2
    fi
fi

if [[ ! "$peer_port" =~ ^[0-9]+$ ]] || ((peer_port < 1 || peer_port > 65535)); then
    echo "PEER_PORT must be between 1 and 65535" >&2
    exit 2
fi

for required_key in \
    "$key_directory/client_ed25519" \
    "$key_directory/client_ed25519.pub" \
    "$key_directory/host_${side}_ed25519" \
    "$key_directory/host_${side}_ed25519.pub"; do
    if [[ ! -s "$required_key" ]]; then
        echo "Required demo key is missing: $required_key" >&2
        exit 1
    fi
done

install -d -m 700 -o "$demo_user" -g "$demo_user" "$demo_home/.ssh"
install -d -m 755 -o "$demo_user" -g "$demo_user" \
    "$demo_home/outgoing" \
    "$demo_home/incoming"
install -d -m 1777 /tmp/.X11-unix
install -m 600 -o "$demo_user" -g "$demo_user" \
    "$key_directory/client_ed25519" \
    "$demo_home/.ssh/demo_key"
install -m 644 -o "$demo_user" -g "$demo_user" \
    "$key_directory/client_ed25519.pub" \
    "$demo_home/.ssh/demo_key.pub"
install -m 600 -o "$demo_user" -g "$demo_user" \
    "$key_directory/client_ed25519.pub" \
    "$demo_home/.ssh/authorized_keys"

printf '%s\n' \
    "This file started on ${side}." \
    "Send it to /home/demo/incoming on ${peer_host:-the peer computer}." \
    >"$demo_home/outgoing/sample-from-${side}.txt"
chown "$demo_user:$demo_user" "$demo_home/outgoing/sample-from-${side}.txt"
chmod 644 "$demo_home/outgoing/sample-from-${side}.txt"

install -m 600 "$key_directory/host_${side}_ed25519" \
    /etc/ssh/ssh_host_ed25519_key
install -m 644 "$key_directory/host_${side}_ed25519.pub" \
    /etc/ssh/ssh_host_ed25519_key.pub
install -d -m 755 /run/sshd

# DEMO ONLY: this server accepts only the generated shared key. VNC is likewise
# intended solely for the localhost-bound ports in compose.demo.yaml.
printf '%s\n' \
    'Port 22' \
    'ListenAddress 0.0.0.0' \
    'HostKey /etc/ssh/ssh_host_ed25519_key' \
    'PidFile /run/sshd.pid' \
    'AuthorizedKeysFile .ssh/authorized_keys' \
    'AuthenticationMethods publickey' \
    'PubkeyAuthentication yes' \
    'PasswordAuthentication no' \
    'KbdInteractiveAuthentication no' \
    'PermitEmptyPasswords no' \
    'PermitRootLogin no' \
    'AllowUsers demo' \
    'UsePAM no' \
    'UseDNS no' \
    'AllowTcpForwarding no' \
    'X11Forwarding no' \
    'Subsystem sftp internal-sftp' \
    >/etc/ssh/sshd_config

/usr/sbin/sshd -t
/usr/sbin/sshd -D -e &
sshd_pid=$!

write_peer_known_hosts() {
    local expected_public_key
    local scan_output
    local scanned_public_key
    local temporary_known_hosts

    expected_public_key="$(awk 'NR == 1 { print $2 }' \
        "$key_directory/host_${peer_host}_ed25519.pub")"
    temporary_known_hosts="$(mktemp)"

    for _attempt in $(seq 1 60); do
        if ((peer_port == 22)); then
            scan_output="$(
                ssh-keyscan -T 2 -t ed25519 "$peer_host" 2>/dev/null || true
            )"
        else
            scan_output="$(
                ssh-keyscan -T 2 -p "$peer_port" -t ed25519 \
                    "$peer_host" 2>/dev/null || true
            )"
        fi
        scanned_public_key="$(
            printf '%s\n' "$scan_output" \
                | awk '$2 == "ssh-ed25519" { print $3; exit }'
        )"
        if [[ -n "$scanned_public_key" && \
            "$scanned_public_key" == "$expected_public_key" ]]; then
            printf '%s\n' "$scan_output" >"$temporary_known_hosts"
            install -m 600 -o "$demo_user" -g "$demo_user" \
                "$temporary_known_hosts" \
                "$demo_home/.ssh/known_hosts"
            rm -f -- "$temporary_known_hosts"
            echo "${side}: verified ${peer_host} and wrote strict known_hosts."
            return 0
        fi
        sleep 1
    done

    rm -f -- "$temporary_known_hosts"
    echo "${side}: peer ${peer_host}:${peer_port} did not present the expected host key" >&2
    return 1
}

if [[ -n "$peer_host" ]]; then
    for peer_key_file in \
        "$key_directory/host_${peer_host}_ed25519" \
        "$key_directory/host_${peer_host}_ed25519.pub"; do
        if [[ ! -s "$peer_key_file" ]]; then
            echo "Required peer host key is missing: $peer_key_file" >&2
            kill "$sshd_pid" 2>/dev/null || true
            wait "$sshd_pid" 2>/dev/null || true
            exit 1
        fi
    done
    write_peer_known_hosts
else
    install -m 600 -o "$demo_user" -g "$demo_user" /dev/null \
        "$demo_home/.ssh/known_hosts"
fi

runuser --user "$demo_user" -- /usr/local/bin/demo-desktop &
desktop_pid=$!

# shellcheck disable=SC2329  # Invoked indirectly by the signal traps below.
cleanup() {
    trap - EXIT INT TERM
    kill "$desktop_pid" "$sshd_pid" 2>/dev/null || true
    wait "$desktop_pid" 2>/dev/null || true
    wait "$sshd_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

set +e
wait -n "$sshd_pid" "$desktop_pid"
status=$?
set -e
if ((status == 0)); then
    status=1
fi
exit "$status"
