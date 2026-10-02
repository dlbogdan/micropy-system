#!/bin/sh
# Host-side client for a micropy-system device shell (no USB).
#
# The device runs one telnet-style line command server on the standard
# telnet port (23): built-in commands status / log / heap / reboot / help,
# optional repl, plus app extensions (e.g. selftest). Stock `telnet` and `nc` work:
#     telnet 10.9.30.76
#
# Set the device address once:  export OTC_IP=10.9.30.76  (DEVICE_IP works too)
# or pass it as the first argument to any command.
#
#   tools/net.sh status [IP]             # device status JSON
#   tools/net.sh log [IP] [N]            # last N log lines (default 40)
#   tools/net.sh selftest [IP]           # run the device self-test remotely
#   tools/net.sh reboot [IP]             # clean reboot (also triggers boot OTA)
#   tools/net.sh console [IP]            # interactive command shell
#   tools/net.sh discover [PORT]         # scan the local /24 for the device
#
# Shell port can be overridden:  OTC_SHELL_PORT=23 tools/net.sh status
# (SHELL_PORT works too; the OTA server's $PORT is a different thing.)
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FRAMEWORK_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
SHELL_PORT="${OTC_SHELL_PORT:-${SHELL_PORT:-23}}"

# Strip --app-root [PATH] from anywhere in argv; the remaining words (the
# command and its arguments) are dispatched below, so they must be kept as-is.
APP_ROOT=""
NEW_ARGS=""
PENDING=""
for arg in "$@"; do
    if [ -n "$PENDING" ]; then
        APP_ROOT="$arg"
        PENDING=""
        continue
    fi
    case "$arg" in
        --app-root) PENDING=1 ;;
        -h|--help)  sed -n '2,18p' "$0"; exit 0 ;;
        *)          NEW_ARGS="$NEW_ARGS $arg" ;;
    esac
done
set -- ${NEW_ARGS}
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

# Prefer the project venv Python (has pyserial etc.); fall back to python3.
PY="$APP_ROOT/.venv/bin/python"
[ -x "$PY" ] || PY=python3

# Resolve the target IP: per-command arg, else OTC_IP, else DEVICE_IP.
resolve_ip() {
    if [ "$#" -ge 1 ] && [ -n "${1:-}" ]; then
        echo "$1"; return
    fi
    if [ -n "${OTC_IP:-}" ]; then
        echo "$OTC_IP"; return
    fi
    if [ -n "${DEVICE_IP:-}" ]; then
        echo "$DEVICE_IP"; return
    fi
    echo "Error: no device IP. Pass it as an argument or set OTC_IP (see: tools/net.sh discover)." >&2
    exit 2
}

cmd=${1:-help}; shift || true

case "$cmd" in
    status)
        IP=$(resolve_ip ${1:-})
        exec "$PY" "$FRAMEWORK_ROOT/tools/telnet.py" "$IP" "$SHELL_PORT" status ;;
    log)
        # first arg is the IP unless it is a plain number (line count, IP from env)
        LIP=""; N=${2:-40}
        case ${1:-} in
            ''|*[!0-9]*) LIP=${1:-} ;;
            *) N=${1} ;;
        esac
        IP=$(resolve_ip ${LIP:-})
        exec "$PY" "$FRAMEWORK_ROOT/tools/telnet.py" "$IP" "$SHELL_PORT" log "$N" ;;
    selftest)
        IP=$(resolve_ip ${1:-})
        exec "$PY" "$FRAMEWORK_ROOT/tools/telnet.py" "$IP" "$SHELL_PORT" selftest ;;
    reboot|update)
        IP=$(resolve_ip ${1:-})
        echo "Requesting reboot of $IP (boot-time OTA check will install any newer served build)..."
        "$PY" "$FRAMEWORK_ROOT/tools/telnet.py" "$IP" "$SHELL_PORT" reboot
        echo "Device is rebooting. Re-check in a few seconds:  tools/net.sh status $IP" ;;
    console)
        IP=$(resolve_ip ${1:-})
        exec "$PY" "$FRAMEWORK_ROOT/tools/telnet.py" "$IP" "$SHELL_PORT" ;;
    discover)
        exec "$PY" "$FRAMEWORK_ROOT/tools/discover.py" "${1:-$SHELL_PORT}" ;;
    help|--help|-h)
        sed -n '2,/^set -eu$/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//' ;;
    *)
        echo "Error: unknown command '$cmd' (try: tools/net.sh help)" >&2
        exit 2
        ;;
esac
