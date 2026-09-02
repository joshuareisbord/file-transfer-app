#!/usr/bin/env bash
set -euo pipefail

target_architecture="amd64"
if [ "${1:-amd64}" != "$target_architecture" ]; then
    echo "Usage: $0 [amd64]" >&2
    exit 2
fi

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "$script_directory/.." && pwd)"
temporary_output="$(mktemp -d)"
trap 'rm -rf "$temporary_output"' EXIT

mkdir -p "$project_directory/dist"

docker build \
    --pull \
    --platform "linux/$target_architecture" \
    --file "$project_directory/packaging/Dockerfile.build" \
    --target artifact \
    --output "type=local,dest=$temporary_output" \
    "$project_directory"

artifact="$project_directory/dist/work-transfer-ubuntu-$target_architecture"
install -m 755 \
    "$temporary_output/work-transfer-ubuntu-$target_architecture" \
    "$artifact"

if command -v sha256sum >/dev/null 2>&1; then
    artifact_sha256="$(sha256sum "$artifact" | awk '{print $1}')"
else
    artifact_sha256="$(shasum -a 256 "$artifact" | awk '{print $1}')"
fi
printf '%s  %s\n' \
    "$artifact_sha256" \
    "$(basename "$artifact")" \
    >"$artifact.sha256"
echo "Built $artifact"
