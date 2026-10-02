#!/bin/sh
# End-to-end firmware deploy (canonical: micropy-system).
#
# bump version -> build -> serve -> OTA over Wi-Fi -> wait for slot promotion
# -> run the on-device self-test.
#
# Network-native by default: the board is rebooted over HTTP (its boot-time
# OTA check then installs the update), promotion is polled via GET /status,
# and the self-test runs over HTTP. The USB cable is never touched and the
# app is never interrupted, so no final reset is needed.
#
# Usage: tools/deploy.sh [VERSION] [flags]
#   VERSION          default: auto-bump the patch of the version file
#   --usb            legacy path: board on USB, mpremote reset + USB
#                    self-test + final reset
#   --app-root PATH  project root (default: auto-detect)
#   --version-file P version file (default: <app-root>/app/version.txt)
#   --port N         update-server port (default 8000; $PORT also honored)
#   --http-port N    device HTTP port (default 8080; $OTC_HTTP_PORT honored)
#   --ip-file P      remembered device IP file (default .micropy-device-ip)
#
# Device IP resolution: $DEVICE_IP / $OTC_IP -> remembered file (if it still
# answers) -> local-subnet scan (tools/discover.py).
#
# Requires: tools/setup_build_env.sh run once, and the board's
# FIRMWARE.DIRECT_BASE_URL pointing at this machine:port (network mode).
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FRAMEWORK_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

USB_MODE=0
VERSION_ARG=""
APP_ROOT=""
VERSION_FILE=""
PORT="${PORT:-8000}"
HTTP_PORT="${OTC_HTTP_PORT:-8080}"
IP_FILE=""
PENDING=""
for arg in "$@"; do
    if [ -n "$PENDING" ]; then
        case "$PENDING" in
            approot)    APP_ROOT="$arg" ;;
            versionfile) VERSION_FILE="$arg" ;;
            port)       PORT="$arg" ;;
            httpport)   HTTP_PORT="$arg" ;;
            ipfile)     IP_FILE="$arg" ;;
        esac
        PENDING=""
        continue
    fi
    case "$arg" in
        --usb)          USB_MODE=1 ;;
        --app-root)     PENDING=approot ;;
        --version-file) PENDING=versionfile ;;
        --port)         PENDING=port ;;
        --http-port)    PENDING=httpport ;;
        --ip-file)      PENDING=ipfile ;;
        -h|--help)      sed -n '2,/^set -eu$/p' "$0" | sed '$d'; exit 0 ;;
        -*)             echo "Error: unknown argument '$arg' (try --help)" >&2; exit 2 ;;
        *)              VERSION_ARG="$arg" ;;
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
cd "$APP_ROOT"

PYTHON="$APP_ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "Error: build environment is missing. Run the framework tools/setup_build_env.sh" >&2
    exit 2
fi
[ -z "$VERSION_FILE" ] && VERSION_FILE="app/version.txt"
[ -z "$IP_FILE" ] && IP_FILE=".micropy-device-ip"
BUILD_LOG="${TMPDIR:-/tmp}/msy-deploy-build.log"
SERVE_LOG="${TMPDIR:-/tmp}/msy-deploy-serve.log"

# --- 1. Determine the version to deploy ----------------------------------------
if [ -n "$VERSION_ARG" ]; then
    VERSION="$VERSION_ARG"
else
    CUR=$(tr -d '[:space:]' < "$VERSION_FILE")
    MAJOR=${CUR%%.*}; REST=${CUR#*.}
    MINOR=${REST%%.*}; PATCH=${REST#*.}
    PATCH=$((PATCH + 1))
    VERSION="${MAJOR}.${MINOR}.${PATCH}"
    printf '%s\n' "$VERSION" > "$VERSION_FILE"
fi
case "$VERSION" in
    *[!0-9.]*|*.*.*.*|.*|*.) echo "Error: version must be MAJOR.MINOR.PATCH" >&2; exit 2;;
esac
echo "==> Deploying version $VERSION"

# --- 2. Build ------------------------------------------------------------------
"$FRAMEWORK_ROOT/tools/build_firmware.sh" --app-root "$APP_ROOT" "$VERSION" \
    >"$BUILD_LOG" 2>&1 || { echo "Build failed:"; tail -30 "$BUILD_LOG"; exit 1; }
echo "==> Build OK"

# --- 3. Ensure the update server is up on $PORT --------------------------------
if ! curl -sf "http://127.0.0.1:$PORT/metadata.json" >/dev/null 2>&1; then
    echo "==> Starting update server on :$PORT"
    nohup "$FRAMEWORK_ROOT/tools/serve_update.sh" "$PORT" --app-root "$APP_ROOT" \
        >"$SERVE_LOG" 2>&1 &
    SERVE_PID=$!
    for _ in $(seq 1 30); do
        curl -sf "http://127.0.0.1:$PORT/metadata.json" >/dev/null 2>&1 && break
        sleep 0.5
    done
else
    echo "==> Update server already running on :$PORT"
fi
curl -sf "http://127.0.0.1:$PORT/metadata.json" >/dev/null 2>&1 \
    || { echo "Error: update server not reachable on :$PORT" >&2; exit 1; }

# --- 4+5. Trigger OTA and wait for promotion -----------------------------------
if [ "$USB_MODE" = 1 ]; then
    # --- USB fallback: mpremote reset, poll /ota-state.json over serial --------
    echo "==> Resetting board via USB (triggers OTA check)"
    "$FRAMEWORK_ROOT/tools/device.py" reset || true

    echo "==> Waiting for OTA install + slot promotion (timeout 240s)..."
    DEADLINE=$(( $(date +%s) + 240 ))
    OK=0
    while [ "$(date +%s)" -lt "$DEADLINE" ]; do
        # The board may be mid-OTA (USB REPL busy / port re-enumerating); only a
        # well-formed "MAJ.MIN.PAT|slot|rejected" line is a real answer.
        OUT=$("$FRAMEWORK_ROOT/tools/device.py" exec \
            "import ujson as j; s=j.load(open('/ota-state.json')); v=open('/version.txt').read().strip(); print(v+'|'+str(s.get('active'))+'|'+str(s.get('rejected_version')))" \
            2>/dev/null | tail -1 | tr -d '[:space:]')
        case "$OUT" in
            [0-9]*.[0-9]*.[0-9]*\|*\|*) ;;          # well-formed: parse below
            *) echo "    board busy/unreachable (${OUT:0:60}); retrying..."; sleep 4; continue ;;
        esac
        V=${OUT%%|*}; REST=${OUT#*|}; ACTIVE=${REST%%|*}; REJ=${REST#*|}
        if [ "$V" = "$VERSION" ] && [ "$REJ" = "None" ]; then
            OK=1; break
        fi
        if [ "$REJ" != "None" ]; then
            echo "    candidate rejected (rejected_version=$REJ); stopping early."
            break
        fi
        sleep 4
    done

    if [ "$OK" -ne 1 ]; then
        echo "ERROR: board did not promote to $VERSION (last state: ${OUT:-unreachable})" >&2
        exit 1
    fi
    echo "==> Promoted: version=$V active_slot=$ACTIVE"

    # --- 6. Verify with the on-device self-test (USB) ---------------------------
    echo "==> Running on-device self-test (USB)"
    "$FRAMEWORK_ROOT/tools/device.py" selftest

    # Entering raw REPL for the self-test interrupts the running application.
    # Reset once more so deploy always leaves the device in normal autonomous
    # operation.
    echo "==> Restarting application after USB self-test"
    "$FRAMEWORK_ROOT/tools/device.py" reset || true
    echo "==> DEPLOY OK: $VERSION is active, tested, and restarting."
    exit 0
fi

# --- Network path (default) -----------------------------------------------------
# IP resolution order: $DEVICE_IP / $OTC_IP env -> remembered IP (if it still
# answers) -> local-subnet scan. The remembered file matters when the device
# is on a different subnet than the host (reachable by route, invisible to
# the /24 scan).
echo "==> Resolving device IP"
IP=""
if [ -n "${DEVICE_IP:-${OTC_IP:-}}" ]; then
    IP="${DEVICE_IP:-${OTC_IP:-}}"
elif [ -f "$IP_FILE" ]; then
    CAND=$(tr -d '[:space:]' < "$IP_FILE")
    if [ -n "$CAND" ] && curl -sf --max-time 3 "http://$CAND:$HTTP_PORT/status" >/dev/null 2>&1; then
        IP="$CAND"
        echo "    using remembered IP $CAND"
    fi
fi
if [ -z "$IP" ]; then
    IP=$("$FRAMEWORK_ROOT/tools/discover.py" | sed -n 's/^Found device: \([0-9.]*\).*/\1/p')
fi
if [ -n "$IP" ]; then
    printf '%s\n' "$IP" > "$IP_FILE"
fi
if [ -z "$IP" ]; then
    echo "Error: device not found on the LAN. Set OTC_IP=<ip> to skip discovery." >&2
    exit 1
fi
BASE="http://$IP:$HTTP_PORT"
echo "==> Target: $BASE"
curl -sf --max-time 5 "$BASE/status" >/dev/null \
    || { echo "Error: $BASE/status unreachable. Check Wi-Fi / same subnet." >&2; exit 1; }

echo "==> Rebooting board over HTTP (triggers boot-time OTA check)"
curl -sf --max-time 5 -X POST "$BASE/reboot" >/dev/null 2>&1 || true
# The board is now down: the boot-time OTA check runs before its HTTP service
# comes back, so expect a gap of several seconds (longer mid-install).

echo "==> Waiting for OTA install + slot promotion (timeout 240s)..."
DEADLINE=$(( $(date +%s) + 240 ))
OK=0
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    RAW=$(curl -sf --max-time 4 "$BASE/status" 2>/dev/null) || RAW=""
    if [ -n "$RAW" ]; then
        STATE=$(printf '%s' "$RAW" | "$PYTHON" -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
except ValueError:
    sys.exit(3)
s = d.get("slot") or {}
print("%s|%s|%s" % (d.get("version"), s.get("active"), s.get("rejected")))
' 2>/dev/null) || STATE=""
        if [ -n "$STATE" ]; then
            V=${STATE%%|*}; REST=${STATE#*|}; ACTIVE=${REST%%|*}; REJ=${REST#*|}
            if [ "$V" = "$VERSION" ] && [ "$REJ" = "None" ]; then
                OK=1; break
            fi
            if [ "$REJ" != "None" ]; then
                echo "    candidate rejected (rejected_version=$REJ); stopping early."
                break
            fi
            echo "    up as $V (want $VERSION); waiting for OTA install..."
            sleep 4
            continue
        fi
    fi
    echo "    board down/unreachable; retrying..."
    sleep 4
done

if [ "$OK" -ne 1 ]; then
    echo "ERROR: board did not promote to $VERSION (last state: ${STATE:-unreachable})" >&2
    echo "Hint: curl '$BASE/log?n=40' for the board's view of the boot/OTA." >&2
    exit 1
fi
echo "==> Promoted: version=$V active_slot=$ACTIVE"

# --- 6. Verify with the on-device self-test (HTTP) ------------------------------
echo "==> Running on-device self-test (HTTP)"
RESP=$(curl -sf --max-time 120 -X POST "$BASE/selftest" 2>/dev/null) \
    || { echo "ERROR: self-test request to $BASE/selftest failed" >&2; exit 1; }
PASS=$(printf '%s' "$RESP" | "$PYTHON" -c '
import json, sys
try:
    print("1" if json.loads(sys.stdin.read()).get("pass") else "0")
except ValueError:
    print("0")
')
printf '%s' "$RESP" | "$PYTHON" -c '
import json, sys
try:
    print(json.loads(sys.stdin.read()).get("output", "").strip())
except ValueError:
    print("(unparseable self-test response)")
'
if [ "$PASS" != "1" ]; then
    echo "ERROR: on-device self-test FAILED" >&2
    exit 1
fi

# The app was never interrupted (no USB REPL), so no final reset is needed.
echo "==> DEPLOY OK: $VERSION is active, self-tested, and left running."
