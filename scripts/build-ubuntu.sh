#!/usr/bin/env bash
set -euo pipefail

architecture="${1:-amd64}"
case "$architecture" in
    amd64|arm64) ;;
    *)
        echo "Usage: $0 [amd64|arm64]" >&2
        exit 2
        ;;
esac

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "$script_directory/.." && pwd)"
temporary_output="$(mktemp -d)"
trap 'rm -rf "$temporary_output"' EXIT

mkdir -p "$project_directory/dist"

docker build \
    --platform "linux/$architecture" \
    --file "$project_directory/packaging/Dockerfile" \
    --output "type=local,dest=$temporary_output" \
    "$project_directory"

artifact="$project_directory/dist/work-transfer-ubuntu-$architecture"
install -m 755 "$temporary_output/work-transfer" "$artifact"
echo "Built $artifact"

