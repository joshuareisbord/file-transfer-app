#!/usr/bin/env bash
set -euo pipefail

readonly computer_a_keys="/computer-a-keys"
readonly computer_b_keys="/computer-b-keys"

install -d -m 700 "$computer_a_keys" "$computer_b_keys"

ensure_keypair() {
    local key_path="$1"
    local comment="$2"

    if [[ -s "$key_path" ]]; then
        # Rebuild a missing public half without changing the stable private key.
        if [[ ! -s "$key_path.pub" ]]; then
            ssh-keygen -y -f "$key_path" >"$key_path.pub"
        fi
    else
        rm -f -- "$key_path.pub"
        ssh-keygen -q -t ed25519 -N "" -C "$comment" -f "$key_path"
    fi

    chmod 600 "$key_path"
    chmod 644 "$key_path.pub"
}

ensure_vnc_password() {
    local password_path="$1"
    local password

    if [[ ! -s "$password_path" ]]; then
        # Six random bytes encode to the eight characters supported by VNC auth.
        password="$(head -c 6 /dev/urandom | base64)"
        printf '%s\n' "$password" >"$password_path"
    fi
    chmod 600 "$password_path"
}

# A owns the only client private key. B receives only the public half.
ensure_keypair \
    "$computer_a_keys/client_ed25519" \
    "file-transfer Docker demo A-to-B sender"
install -m 644 \
    "$computer_a_keys/client_ed25519.pub" \
    "$computer_b_keys/client_ed25519.pub"

# Only B accepts SSH, so its private host identity never enters A's bundle.
ensure_keypair \
    "$computer_b_keys/host_computer-b_ed25519" \
    "computer-b Docker demo host"
install -m 644 \
    "$computer_b_keys/host_computer-b_ed25519.pub" \
    "$computer_a_keys/host_computer-b_ed25519.pub"

ensure_vnc_password "$computer_a_keys/vnc_password"
ensure_vnc_password "$computer_b_keys/vnc_password"

echo "Directional demo SSH identities and desktop passwords are ready."
