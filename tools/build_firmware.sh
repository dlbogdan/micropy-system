#!/bin/sh
# Build the firmware package (canonical: micropy-system).
#
# Assembles the device tree (tools/assemble.py), compiles the .mpy modules
# and packages the OTA update (framework local_builder.py) into the output
# directory: <package>.tar.zlib + metadata.json + image-info.json.
#
# Usage: tools/build_firmware.sh [VERSION] [MODEL] [flags]
#   VERSION   default: the project's app/version.txt
#   MODEL     default: pico2-w-rp2350
#   --app-root PATH     project root (default: auto-detect)
#   --source-dir DIR    application source dir (default: app)
#   --output-dir DIR    build output dir (default: build)
#
# Requires: tools/setup_build_env.sh run once (mpy-cross in the venv).
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FRAMEWORK_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

VERSION_ARG=""
MODEL_ARG=""
APP_ROOT=""
SOURCE_DIR="app"
OUTPUT_DIR="build"
PENDING=""
for arg in "$@"; do
    if [ -n "$PENDING" ]; then
        case "$PENDING" in
            approot)   APP_ROOT="$arg" ;;
            sourcedir) SOURCE_DIR="$arg" ;;
            outputdir) OUTPUT_DIR="$arg" ;;
        esac
        PENDING=""
        continue
    fi
    case "$arg" in
        --app-root)   PENDING=approot ;;
        --source-dir) PENDING=sourcedir ;;
        --output-dir) PENDING=outputdir ;;
        -h|--help)    sed -n '2,/^set -eu$/p' "$0" | sed '$d'; exit 0 ;;
        -*)           echo "Error: unknown argument '$arg' (try --help)" >&2; exit 2 ;;
        *)
            if [ -z "$VERSION_ARG" ]; then
                VERSION_ARG="$arg"
            elif [ -z "$MODEL_ARG" ]; then
                MODEL_ARG="$arg"
            else
                echo "Error: too many positional arguments (got '$arg')" >&2
                exit 2
            fi
            ;;
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

VERSION="${VERSION_ARG:-$(tr -d '[:space:]' < "$APP_ROOT/app/version.txt")}"
MODEL="${MODEL_ARG:-pico2-w-rp2350}"

case "$VERSION" in
    *[!0-9.]*|*.*.*.*|.*|*.)
        echo "Error: version must have the form MAJOR.MINOR.PATCH" >&2
        exit 2
        ;;
esac
if [ "$(printf '%s' "$VERSION" | awk -F. '{print NF}')" -ne 3 ]; then
    echo "Error: version must have the form MAJOR.MINOR.PATCH" >&2
    exit 2
fi

echo "==> Assembling device tree"
"$PYTHON" "$FRAMEWORK_ROOT/tools/assemble.py" --app-root "$APP_ROOT"

echo "==> Building firmware $VERSION for $MODEL"
PATH="$APP_ROOT/.venv/bin:$PATH" "$PYTHON" "$FRAMEWORK_ROOT/local_builder.py" \
    --source-dir "$APP_ROOT/$SOURCE_DIR" \
    --output-dir "$APP_ROOT/$OUTPUT_DIR" \
    --model "$MODEL" \
    --version "$VERSION"

echo "==> Build complete: $APP_ROOT/$OUTPUT_DIR"
