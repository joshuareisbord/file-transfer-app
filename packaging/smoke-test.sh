#!/usr/bin/env sh
set -eu

executable="$1"

set +e
xvfb-run --auto-servernum timeout 3 "$executable"
status=$?
set -e

if [ "$status" -ne 124 ]; then
    echo "GUI smoke test failed with status $status" >&2
    exit "$status"
fi

echo "GUI smoke test passed"

