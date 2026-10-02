#!/bin/sh
# Update this framework's pinned submodule checkout in the consuming project.
# Generic: contains no project-specific content. Invoke from the project:
#
#   ./micropy-system/tools/update_framework.sh
#
# Resolves the superproject (git, else CWD) and the submodule path
# (.gitmodules, default "micropy-system"). Afterward, review and commit the
# submodule pointer in the project.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FRAMEWORK_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

APP_ROOT="${MICROPY_APP_ROOT:-}"
if [ -z "$APP_ROOT" ]; then
    APP_ROOT=$(git -C "$FRAMEWORK_ROOT" rev-parse --show-superproject-working-tree 2>/dev/null || true)
fi
if [ -z "$APP_ROOT" ]; then
    APP_ROOT=$(pwd)
fi
APP_ROOT=$(CDPATH= cd -- "$APP_ROOT" && pwd)

SUBMODULE="${MICROPY_SUBMODULE_PATH:-}"
if [ -z "$SUBMODULE" ] && [ -f "$APP_ROOT/.gitmodules" ]; then
    framework_physical=$(CDPATH= cd -- "$FRAMEWORK_ROOT" && pwd -P)
    for candidate in $(git -C "$APP_ROOT" config --file .gitmodules --get-regexp path 2>/dev/null | awk '{print $2}'); do
        candidate_root=$(CDPATH= cd -- "$APP_ROOT/$candidate" 2>/dev/null && pwd -P || true)
        if [ -n "$candidate_root" ] && [ "$candidate_root" = "$framework_physical" ]; then
            SUBMODULE=$candidate
            break
        fi
    done
fi
SUBMODULE="${SUBMODULE:-micropy-system}"

git -C "$APP_ROOT" submodule update --init "$SUBMODULE"
git -C "$APP_ROOT/$SUBMODULE" fetch origin main
git -C "$APP_ROOT/$SUBMODULE" checkout main
git -C "$APP_ROOT/$SUBMODULE" merge --ff-only origin/main
echo "Framework updated. Review and commit the submodule pointer:"
echo "  git add $SUBMODULE && git commit -m 'Update micropy-system framework'"
