#!/usr/bin/env bash
set -euo pipefail

readonly computer_a_keys="/computer-a-keys"
readonly computer_b_keys="/computer-b-keys"

install -d -m 700 "$computer_a_keys" "$computer_b_keys"

# Remove credentials from older key-authenticated demo volumes.
rm -f -- \
    "$computer_a_keys/client_ed25519" \
    "$computer_a_keys/client_ed25519.pub" \
    "$computer_b_keys/client_ed25519" \
    "$computer_b_keys/client_ed25519.pub"

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

# Only B accepts SSH, so its private host identity never enters A's bundle.
ensure_keypair \
    "$computer_b_keys/host_computer-b_ed25519" \
    "computer-b Docker demo host"
install -m 644 \
    "$computer_b_keys/host_computer-b_ed25519.pub" \
    "$computer_a_keys/host_computer-b_ed25519.pub"

echo "Directional demo SSH host identity is ready."
