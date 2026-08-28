#!/usr/bin/env bash
set -euo pipefail

readonly demo_user="demo"
readonly demo_home="/home/$demo_user"
readonly key_directory="/demo-keys"
readonly side="${DEMO_SIDE:?DEMO_SIDE must identify this computer}"
readonly peer_host="${PEER_HOST:-}"
readonly peer_port="${PEER_PORT:-22}"

case "$side" in
    computer-a)
        if [[ "$peer_host" != "computer-b" ]]; then
            echo "Computer A requires PEER_HOST=computer-b" >&2
            exit 2
        fi
        ;;
    computer-b)
        if [[ -n "$peer_host" ]]; then
            echo "Computer B must not define an outbound peer" >&2
            exit 2
        fi
        ;;
    *)
        echo "DEMO_SIDE must be computer-a or computer-b" >&2
        exit 2
        ;;
esac

if [[ ! "$peer_port" =~ ^[0-9]+$ ]] || ((peer_port < 1 || peer_port > 65535)); then
    echo "PEER_PORT must be between 1 and 65535" >&2
    exit 2
fi

required_keys=("$key_directory/vnc_password")
if [[ "$side" == "computer-a" ]]; then
    required_keys+=(
        "$key_directory/client_ed25519"
        "$key_directory/client_ed25519.pub"
        "$key_directory/host_computer-b_ed25519.pub"
    )
else
    required_keys+=(
        "$key_directory/client_ed25519.pub"
        "$key_directory/host_computer-b_ed25519"
        "$key_directory/host_computer-b_ed25519.pub"
    )
fi
for required_key in "${required_keys[@]}"; do
    if [[ ! -s "$required_key" ]]; then
        echo "Required demo credential is missing: $required_key" >&2
        exit 1
    fi
done

install -d -m 700 -o "$demo_user" -g "$demo_user" \
    "$demo_home/.ssh" \
    "$demo_home/.vnc"
install -d -m 755 -o "$demo_user" -g "$demo_user" \
    "$demo_home/outgoing" \
    "$demo_home/library-updates" \
    "$demo_home/software-updates"
install -d -m 1777 /tmp/.X11-unix

vnc_password="$(<"$key_directory/vnc_password")"
if ((${#vnc_password} != 8)); then
    echo "The demo VNC password must contain exactly eight characters" >&2
    exit 1
fi
x11vnc -storepasswd "$vnc_password" "$demo_home/.vnc/passwd" >/dev/null
unset vnc_password
chown "$demo_user:$demo_user" "$demo_home/.vnc/passwd"
chmod 600 "$demo_home/.vnc/passwd"

if [[ "$side" == "computer-a" ]]; then
    install -m 600 -o "$demo_user" -g "$demo_user" \
        "$key_directory/client_ed25519" \
        "$demo_home/.ssh/demo_key"
    install -m 644 -o "$demo_user" -g "$demo_user" \
        "$key_directory/client_ed25519.pub" \
        "$demo_home/.ssh/demo_key.pub"

    printf '%s\n' \
        "This file started on computer-a." \
        "Send it with Library Update to computer-b." \
        >"$demo_home/outgoing/sample-from-computer-a.txt"
    chown "$demo_user:$demo_user" \
        "$demo_home/outgoing/sample-from-computer-a.txt"
    chmod 644 "$demo_home/outgoing/sample-from-computer-a.txt"
else
    temporary_authorized_keys="$(mktemp)"
    {
        printf 'restrict '
        cat "$key_directory/client_ed25519.pub"
    } >"$temporary_authorized_keys"
    install -m 600 -o "$demo_user" -g "$demo_user" \
        "$temporary_authorized_keys" \
        "$demo_home/.ssh/authorized_keys"
    rm -f -- "$temporary_authorized_keys"
fi

start_receiver_sshd() {
    install -m 600 "$key_directory/host_computer-b_ed25519" \
        /etc/ssh/ssh_host_ed25519_key
    install -m 644 "$key_directory/host_computer-b_ed25519.pub" \
        /etc/ssh/ssh_host_ed25519_key.pub
    install -d -m 755 /run/sshd

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
        'DisableForwarding yes' \
        'PermitTTY no' \
        'PermitTunnel no' \
        'X11Forwarding no' \
        'Subsystem sftp internal-sftp' \
        >/etc/ssh/sshd_config

    /usr/sbin/sshd -t
    /usr/sbin/sshd -D -e &
    sshd_pid=$!
}

write_peer_known_hosts() {
    local expected_public_key
    local scan_output
    local scanned_public_key
    local temporary_known_hosts

    expected_public_key="$(awk 'NR == 1 { print $2 }' \
        "$key_directory/host_computer-b_ed25519.pub")"
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

sshd_pid=""
if [[ "$side" == "computer-b" ]]; then
    start_receiver_sshd
    install -m 600 -o "$demo_user" -g "$demo_user" /dev/null \
        "$demo_home/.ssh/known_hosts"
else
    write_peer_known_hosts
fi

runuser --user "$demo_user" -- /usr/local/bin/demo-desktop "$side" &
desktop_pid=$!

# shellcheck disable=SC2329  # Invoked indirectly by the signal traps below.
cleanup() {
    local -a child_pids=("$desktop_pid")

    trap - EXIT INT TERM
    if [[ -n "$sshd_pid" ]]; then
        child_pids+=("$sshd_pid")
    fi
    kill "${child_pids[@]}" 2>/dev/null || true
    wait "${child_pids[@]}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

child_pids=("$desktop_pid")
if [[ -n "$sshd_pid" ]]; then
    child_pids+=("$sshd_pid")
fi
set +e
wait -n "${child_pids[@]}"
status=$?
set -e
if ((status == 0)); then
    status=1
fi
exit "$status"
