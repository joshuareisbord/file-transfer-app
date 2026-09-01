#!/usr/bin/env sh
set -eu

executable="$1"
temporary_directory="$(mktemp -d)"
trap 'rm -rf -- "$temporary_directory"' EXIT
logo="$temporary_directory/smoke-logo.svg"
raster_logo="$temporary_directory/smoke-logo.png"

printf '%s\n' \
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">' \
    '  <rect width="48" height="48" fill="#E7DBC4"/>' \
    '  <path d="M8 24h32" stroke="#1F3B64" stroke-width="6"/>' \
    '</svg>' \
    >"$logo"

printf '%s' \
    'iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAYAAAD0In+KAAAAEUlEQVR4nGOUt075z8DAwAAACfoBv7Asd/wAAAAASUVORK5CYII=' \
    | base64 --decode >"$raster_logo"

run_gui_smoke() {
    description="$1"
    shift

    set +e
    timeout 3 "$executable" "$@"
    status=$?
    set -e

    if [ "$status" -ne 124 ]; then
        echo "$description GUI smoke test failed with status $status" >&2
        exit "$status"
    fi
}

run_gui_smoke "Default"
run_gui_smoke "SVG logo" --logo "$logo"
run_gui_smoke "Raster logo" --logo "$raster_logo"

echo "GUI smoke test passed"
