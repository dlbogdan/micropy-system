#!/bin/sh
# Serve a built firmware package for direct-server OTA (canonical: micropy-system).
#
# Runs the framework's firmware_server.py over the build directory. The
# board's FIRMWARE.DIRECT_BASE_URL (from update-source.json at provision
# time) must point at this machine:PORT; then the `reboot` shell command
# (or a power cycle) makes it fetch metadata.json and the package.
#
# Usage: tools/serve_update.sh [PORT] [--app-root PATH] [--directory DIR]
#   PORT      default 8000
#   directory default <app-root>/build (must contain metadata.json)
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FRAMEWORK_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

PORT="8000"
APP_ROOT=""
DIR_ARG=""
PENDING=""
for arg in "$@"; do
    if [ -n "$PENDING" ]; then
        case "$PENDING" in
            approot)   APP_ROOT="$arg" ;;
            directory) DIR_ARG="$arg" ;;
        esac
        PENDING=""
        continue
    fi
    case "$arg" in
        --app-root)  PENDING=approot ;;
        --directory) PENDING=directory ;;
        -h|--help)   sed -n '2,/^set -eu$/p' "$0" | sed '$d'; exit 0 ;;
        -*)          echo "Error: unknown argument '$arg' (try --help)" >&2; exit 2 ;;
        *)           PORT="$arg" ;;
    esac
done

if [ -z "$APP_ROOT" ]; then
    APP_ROOT="${MICROPY_APP_ROOT:-}"
fi
if [ -z "$APP_ROOT" ]; then
    APP_ROOT=$(git -C "$FRAMEWORK_ROOT" rev-parse --show-superproject-working-tree 2>/dev/null || true)
fi
if [ -z "$APP_ROOT" ]; then
    APP_ROOT=$(pwd)
fi
APP_ROOT=$(CDPATH= cd -- "$APP_ROOT" && pwd)

PYTHON="$APP_ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "Error: build environment is missing. Run the framework tools/setup_build_env.sh" >&2
    exit 2
fi
DIRECTORY="$DIR_ARG"
if [ -z "$DIRECTORY" ]; then
    DIRECTORY="$APP_ROOT/build"
fi
if [ ! -f "$DIRECTORY/metadata.json" ]; then
    echo "Error: no direct-server build found at $DIRECTORY. Run tools/build_firmware.sh first." >&2
    exit 2
fi

exec "$PYTHON" "$FRAMEWORK_ROOT/firmware_server.py" \
    --directory "$DIRECTORY" --port "$PORT"
