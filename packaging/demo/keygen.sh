#!/usr/bin/env bash
set -euo pipefail

readonly key_directory="/demo-keys"

install -d -m 700 "$key_directory"

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

# DEMO ONLY: both computers intentionally share this client identity so either
# side can send to the other. Removing the named volume rotates the identity.
ensure_keypair "$key_directory/client_ed25519" "file-transfer Docker demo client"

# Separate host identities keep strict known_hosts useful and remain stable
# when either computer service is recreated while the named volume survives.
ensure_keypair \
    "$key_directory/host_computer-a_ed25519" \
    "computer-a Docker demo host"
ensure_keypair \
    "$key_directory/host_computer-b_ed25519" \
    "computer-b Docker demo host"

echo "Demo SSH identities are ready."
