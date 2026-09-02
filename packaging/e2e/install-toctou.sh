#!/usr/bin/env bash
set -euo pipefail

readonly installer="${1:?Path to install-ubuntu.sh is required}"
readonly test_root="$(mktemp -d)"
trap 'rm -rf -- "$test_root"' EXIT

readonly fake_bin="$test_root/bin"
readonly selected_artifact="$test_root/work-transfer"
readonly replacement_artifact="$test_root/replacement"
readonly self_check_started="$test_root/self-check-started"
readonly replacement_complete="$test_root/replacement-complete"
readonly install_root="$test_root/installed"

mkdir -p "$fake_bin" "$install_root"

# The wrapper preserves every sudo operation except the two final destinations,
# which are redirected into the disposable test tree.
cat >"$fake_bin/sudo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "-v" ]]; then
    if [[ -n "${TEST_SUDO_STARTED:-}" ]]; then
        touch "$TEST_SUDO_STARTED"
    fi
    exit 0
fi

if [[ "${1:-}" == "mktemp" ]]; then
    arguments=("$@")
    template_index=$((${#arguments[@]} - 1))
    if [[ "${arguments[$template_index]}" == \
        /opt/work-transfer/.install.XXXXXX ]]; then
        arguments[$template_index]="$TEST_INSTALL_ROOT/opt/work-transfer/.install.XXXXXX"
    fi
    exec "${arguments[@]}"
fi

if [[ "${1:-}" == "install" ]]; then
    arguments=("$@")
    for argument in "${arguments[@]}"; do
        if [[ "$argument" == "$TEST_UNTRUSTED_ARTIFACT" || \
            "$argument" == "$TEST_UNTRUSTED_DESKTOP" ]]; then
            echo "sudo attempted to open an untrusted source path: $argument" >&2
            exit 97
        fi
    done
    destination_index=$((${#arguments[@]} - 1))
    case "${arguments[$destination_index]}" in
        /opt/work-transfer)
            arguments[$destination_index]="$TEST_INSTALL_ROOT/opt/work-transfer"
            ;;
        /opt/work-transfer/work-transfer)
            arguments[$destination_index]="$TEST_INSTALL_ROOT/opt/work-transfer/work-transfer"
            ;;
        /usr/share/applications/work-transfer.desktop)
            arguments[$destination_index]="$TEST_INSTALL_ROOT/usr/share/applications/work-transfer.desktop"
            ;;
    esac
    exec "${arguments[@]}"
fi

exec "$@"
EOF
chmod 755 "$fake_bin/sudo"

cat >"$selected_artifact" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ "\${1:-}" == "--self-check" ]]; then
    touch "$self_check_started"
    for _attempt in \$(seq 1 100); do
        [[ -e "$replacement_complete" ]] && exit 0
        sleep 0.01
    done
    echo "Timed out waiting for the pathname replacement" >&2
    exit 1
fi
printf '%s\n' trusted
EOF
chmod 755 "$selected_artifact"

cat >"$replacement_artifact" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--self-check" ]]; then
    exit 0
fi
printf '%s\n' swapped
EOF
chmod 755 "$replacement_artifact"

(
    while [[ ! -e "$self_check_started" ]]; do
        sleep 0.01
    done
    mv -- "$replacement_artifact" "$selected_artifact"
    touch "$replacement_complete"
) &
replacement_pid=$!

PATH="$fake_bin:$PATH" \
TEST_INSTALL_ROOT="$install_root" \
TEST_UNTRUSTED_ARTIFACT="$selected_artifact" \
TEST_UNTRUSTED_DESKTOP="$(
    cd "$(dirname "$installer")/.." && pwd
)/packaging/work-transfer.desktop" \
    "$installer" "$selected_artifact"
wait "$replacement_pid"

installed_artifact="$install_root/opt/work-transfer/work-transfer"
if [[ ! -x "$installed_artifact" ]]; then
    echo "Installer did not create the executable" >&2
    exit 1
fi
if [[ "$($installed_artifact)" != "trusted" ]]; then
    echo "Installer reopened the selected pathname after validation" >&2
    exit 1
fi

echo "Installer used the validated staged bytes."

# A replacement with an infinite source must be bounded by the size captured
# before sudo starts, then rejected by the staged hash comparison.
bounded_artifact="$test_root/work-transfer-bounded"
sudo_started="$test_root/sudo-started"
cat >"$bounded_artifact" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod 755 "$bounded_artifact"
(
    while [[ ! -e "$sudo_started" ]]; do
        sleep 0.01
    done
    rm -f -- "$bounded_artifact"
    ln -s /dev/zero "$bounded_artifact"
) &
replacement_pid=$!

set +e
PATH="$fake_bin:$PATH" \
TEST_INSTALL_ROOT="$install_root" \
TEST_UNTRUSTED_ARTIFACT="$bounded_artifact" \
TEST_UNTRUSTED_DESKTOP="$(
    cd "$(dirname "$installer")/.." && pwd
)/packaging/work-transfer.desktop" \
TEST_SUDO_STARTED="$sudo_started" \
    timeout 5 "$installer" "$bounded_artifact"
bounded_status=$?
set -e
wait "$replacement_pid"
if [[ "$bounded_status" -eq 0 || "$bounded_status" -eq 124 ]]; then
    echo "Installer did not reject a bounded infinite-source replacement" >&2
    exit 1
fi

echo "Installer bounded and rejected an infinite-source replacement."
