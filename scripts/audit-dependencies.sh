#!/usr/bin/env bash
set -euo pipefail

readonly target_architecture="amd64"
readonly script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly project_directory="$(cd "$script_directory/.." && pwd)"
readonly output_directory="${1:?Usage: $0 OUTPUT_DIRECTORY}"
readonly report_directory="$project_directory/dist/security"
readonly previous_report_directory="$project_directory/dist/security-previous"
readonly scanner_image="aquasec/trivy:latest"
readonly builder_image="file-transfer-builder:audit"
readonly runtime_image="file-transfer-runtime:audit"
readonly demo_image="file-transfer-demo-computer:local"
readonly temporary_directory="$(mktemp -d)"
readonly temporary_report_directory="$project_directory/dist/.security-next-$$"
readonly builder_policy_deadline="2026-12-01"
builder_container=""
runtime_container=""
demo_container=""
scanner_digest=""
builder_manifest_id=""
runtime_manifest_id=""
demo_manifest_id=""

cleanup() {
    if [[ -n "$builder_container" ]]; then
        docker rm --force "$builder_container" >/dev/null 2>&1 || true
    fi
    if [[ -n "$runtime_container" ]]; then
        docker rm --force "$runtime_container" >/dev/null 2>&1 || true
    fi
    if [[ -n "$demo_container" ]]; then
        docker rm --force "$demo_container" >/dev/null 2>&1 || true
    fi
    rm -rf -- "$temporary_directory"
    rm -rf -- "$temporary_report_directory"
}
trap cleanup EXIT

mkdir -p "$project_directory/dist"
if [[ -e "$report_directory" || -L "$report_directory" ]]; then
    rm -rf -- "$previous_report_directory"
    mv -- "$report_directory" "$previous_report_directory"
fi
mkdir -p \
    "$output_directory" \
    "$temporary_report_directory" \
    "$temporary_directory/trivy-cache"

if [[ "$(date -u +%F)" > "$builder_policy_deadline" ]]; then
    echo "The linux-libc-dev Trivy exception expired on $builder_policy_deadline." >&2
    exit 1
fi

# A release audit always resolves the current Ubuntu 24.04 image and stable apt
# packages. The exact resolved closures are recorded after the build.
docker build \
    --pull \
    --no-cache \
    --platform "linux/$target_architecture" \
    --file "$project_directory/packaging/Dockerfile" \
    --target runtime-check \
    --tag "$runtime_image" \
    "$project_directory"
docker build \
    --platform "linux/$target_architecture" \
    --file "$project_directory/packaging/Dockerfile" \
    --target builder \
    --tag "$builder_image" \
    "$project_directory"
docker build \
    --platform "linux/$target_architecture" \
    --file "$project_directory/packaging/Dockerfile" \
    --target demo \
    --tag "$demo_image" \
    "$project_directory"

builder_manifest_id="$(docker image inspect --format '{{.Id}}' "$builder_image")"
runtime_manifest_id="$(docker image inspect --format '{{.Id}}' "$runtime_image")"
demo_manifest_id="$(docker image inspect --format '{{.Id}}' "$demo_image")"
builder_container="$(
    docker create --platform "linux/$target_architecture" "$builder_manifest_id"
)"
runtime_container="$(
    docker create --platform "linux/$target_architecture" "$runtime_manifest_id"
)"
demo_container="$(
    docker create --platform "linux/$target_architecture" "$demo_manifest_id"
)"

docker pull "$scanner_image"
scanner_digest="$(
    docker image inspect --format '{{index .RepoDigests 0}}' "$scanner_image"
)"
docker save --output "$temporary_directory/builder.tar" "$builder_manifest_id"
docker save --output "$temporary_directory/runtime.tar" "$runtime_manifest_id"
docker save --output "$temporary_directory/demo.tar" "$demo_manifest_id"

run_trivy() {
    docker run --rm \
        --volume "$temporary_directory:/scan:ro" \
        --volume "$temporary_directory/trivy-cache:/root/.cache/trivy" \
        --volume "$temporary_report_directory:/reports" \
        --volume "$project_directory/security:/policy:ro" \
        "$scanner_digest" "$@"
}

# The builder gate suppresses only linux-libc-dev kernel-implementation CVE
# mappings under the expiring policy above. Every other High/Critical builder
# finding remains release-blocking and suppressed findings stay in the report.
run_trivy image \
    --input /scan/builder.tar \
    --scanners vuln \
    --severity HIGH,CRITICAL \
    --ignore-policy /policy/trivy-builder-ignore.rego \
    --show-suppressed \
    --exit-code 1 \
    --format json \
    --output /reports/builder-trivy.json
run_trivy image \
    --input /scan/builder.tar \
    --scanners vuln \
    --format cyclonedx \
    --output /reports/builder-sbom.cdx.json

for image_name in runtime demo; do
    run_trivy image \
        --input "/scan/$image_name.tar" \
        --scanners vuln \
        --severity HIGH,CRITICAL \
        --exit-code 1 \
        --format json \
        --output "/reports/$image_name-trivy.json"
    run_trivy image \
        --input "/scan/$image_name.tar" \
        --scanners vuln \
        --format cyclonedx \
        --output "/reports/$image_name-sbom.cdx.json"
done

docker run --rm \
    --volume "$temporary_directory/trivy-cache:/root/.cache/trivy" \
    --volume "$project_directory:/source:ro" \
    --volume "$temporary_report_directory:/reports" \
    "$scanner_digest" config \
    --severity HIGH,CRITICAL \
    --exit-code 1 \
    --format json \
    --output /reports/dockerfile-trivy.json \
    /source/packaging/Dockerfile

docker run --rm \
    --volume "$temporary_directory/trivy-cache:/root/.cache/trivy" \
    --volume "$project_directory:/source:ro" \
    --volume "$temporary_report_directory:/reports" \
    "$scanner_digest" fs \
    --scanners secret \
    --severity HIGH,CRITICAL \
    --exit-code 1 \
    --skip-dirs /source/.git \
    --skip-dirs /source/.venv \
    --skip-dirs /source/build \
    --skip-dirs /source/dist \
    --format json \
    --output /reports/source-secrets-trivy.json \
    /source

docker run --rm \
    --volume "$temporary_directory/trivy-cache:/root/.cache/trivy" \
    "$scanner_digest" version --format json \
    >"$temporary_report_directory/trivy-version.json"

docker cp "$runtime_container:/work-transfer" "$output_directory/work-transfer"
docker cp "$runtime_container:/builder-packages.tsv" \
    "$output_directory/builder-packages.tsv"
docker cp "$runtime_container:/runtime-packages.tsv" \
    "$output_directory/runtime-packages.tsv"
docker cp "$runtime_container:/work-transfer-ldd.txt" \
    "$output_directory/work-transfer-ldd.txt"
docker cp "$demo_container:/demo-packages.tsv" \
    "$output_directory/demo-packages.tsv"
chmod 755 "$output_directory/work-transfer"

file_sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

artifact_sha256="$(file_sha256 "$output_directory/work-transfer")"

{
    printf 'audited_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'scanner_image=%s\n' "$scanner_image"
    printf 'scanner_digest=%s\n' "$scanner_digest"
    printf 'ubuntu_base_digest=%s\n' "$(
        docker image inspect --format '{{join .RepoDigests ","}}' ubuntu:24.04
    )"
    printf 'builder_manifest_id=%s\n' "$builder_manifest_id"
    printf 'runtime_manifest_id=%s\n' "$runtime_manifest_id"
    printf 'demo_manifest_id=%s\n' "$demo_manifest_id"
    printf 'builder_archive_sha256=%s\n' "$(
        file_sha256 "$temporary_directory/builder.tar"
    )"
    printf 'runtime_archive_sha256=%s\n' "$(
        file_sha256 "$temporary_directory/runtime.tar"
    )"
    printf 'demo_archive_sha256=%s\n' "$(
        file_sha256 "$temporary_directory/demo.tar"
    )"
    printf 'artifact_sha256=%s\n' "$artifact_sha256"
    printf 'builder_sbom_sha256=%s\n' "$(
        file_sha256 "$temporary_report_directory/builder-sbom.cdx.json"
    )"
    printf 'runtime_sbom_sha256=%s\n' "$(
        file_sha256 "$temporary_report_directory/runtime-sbom.cdx.json"
    )"
    printf 'demo_sbom_sha256=%s\n' "$(
        file_sha256 "$temporary_report_directory/demo-sbom.cdx.json"
    )"
    printf 'builder_policy_deadline=%s\n' "$builder_policy_deadline"
} >"$temporary_report_directory/scan-metadata.txt"

# The old report set was moved out of the current path before scanning. Rename
# the complete same-filesystem staging directory only after every gate passes,
# so readers can never observe a mixed or stale current generation.
mv -- "$temporary_report_directory" "$report_directory"
rm -rf -- "$previous_report_directory"

echo "Dependency audit passed. Reports: $report_directory"
