#!/usr/bin/env python3
"""Push on-device test suites to a board and run them remotely over the shell.

The suites are plain ``unittest``-style Python that lives on the HOST (they
never ship inside a firmware release) and runs ON the device inside the live
application's uasyncio loop, driven by the framework's ``test`` shell command
(``lib.coresys.autotest``). Two stages:

    push HOST|auto     upload <app-root>/autotests/test_*.py plus the
                       framework unittest shim to /autotests (USB/mpremote;
                       the USB pass stops the app, so it ends with a reset)
    run  [PATTERN]     execute remotely over the network shell (no USB):
                       'test run [PATTERN]' + exit non-zero on any failure
    sync [PATTERN]     push then run (default)

Examples:
    tools/target/autotest.py sync                 # push + run everything
    tools/target/autotest.py run demand           # rerun a subset, no re-push
    tools/target/autotest.py push                 # push only (USB board)

The device IP for ``run`` comes from (in order) the argument, $OTC_IP,
$DEVICE_IP, or the --ip-file (default .otc-device-ip). ``push`` uses the USB
board (mpremote); per the framework's USB rules it finishes with a reset so
the app runs autonomously again.

Suites must be readable-only in their effects on production systems: they run
against a live board (e.g. read-only CCU3 polls). Treat write actuation in
tests as a bug -- the board-under-test may be plugged into the real house.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tooling import (find_serial_port, framework_root, project_python,
                     resolve_app_root)

DEVICE_DIR = "/autotests"
RESULT_PREFIX = "RESULT:"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", nargs="?", default="sync",
                        choices=("push", "run", "sync"))
    parser.add_argument("tokens", nargs="*",
                        help="device IP (an IPv4-looking token; push finds "
                             "the board over USB anyway) and/or a substring "
                             "PATTERN filter on module.Class.method")
    parser.add_argument("--app-root")
    parser.add_argument("--ip-file", default=".otc-device-ip")
    parser.add_argument("--shell-port", type=int, default=23)
    return parser.parse_args(argv)


def split_target_pattern(tokens):
    """An IPv4-looking token is the device IP; any other token is PATTERN."""
    target, pattern = None, ""
    for token in tokens:
        looks_like_ip = all(part.isdigit() for part in token.split(".")) \
            and len(token.split(".")) == 4
        if looks_like_ip and target is None:
            target = token
        elif not pattern:
            pattern = token
    return target, pattern


def suite_files(app_root):
    """(device_path, host_path) upload manifest.

    The runner module rides to ``/lib/coresys`` (provisioned framework code,
    not part of the A/B firmware package), the unittest shim plus the
    project's suites to ``/autotests`` (outside the slots: pushed test code
    never ships inside a release). ``telnet_service.py`` is refreshed too so
    a board predating the MicroPython-coroutine dispatch fix can drive the
    async ``test`` command (board-local framework code, like the runner).
    """
    framework = framework_root()
    files = [("/lib/coresys", framework / "src" / "lib" / "coresys"
              / "autotest.py"),
             ("/lib/coresys", framework / "src" / "lib" / "coresys"
              / "telnet_service.py"),
             (DEVICE_DIR, framework / "src" / "autotests" / "unittest.py")]
    suites_dir = Path(app_root) / "autotests"
    if suites_dir.is_dir():
        # test_*.py (collected) + helper modules they import (e.g. the
        # shared live-CCU3 session): push every top-level .py in the dir.
        files.extend((DEVICE_DIR, path)
                     for path in sorted(suites_dir.glob("*.py")))
    return files


def resolve_device_ip(app_root, explicit, ip_file):
    value = explicit or os.environ.get("OTC_IP") or os.environ.get("DEVICE_IP")
    if value:
        return value
    path = Path(ip_file)
    if not path.is_absolute():
        path = Path(app_root) / path
    if path.is_file():
        ip_address = path.read_text().strip()
        if ip_address:
            return ip_address
    raise SystemExit("no device IP: pass it, set OTC_IP/DEVICE_IP, or write %s"
                     % path)


def do_push(app_root):
    """Upload the shim + suites over USB, verify, then reset the app."""
    files = suite_files(app_root)
    if len(files) == 1:
        raise SystemExit("no suites found in %s/autotests" % app_root)
    venv_mpremote = app_root / ".venv" / "bin" / "mpremote"
    mpremote = str(venv_mpremote) if venv_mpremote.is_file() else "mpremote"
    port = find_serial_port()
    if not port:
        raise SystemExit("no USB board found for push (run works without USB)")

    def mp(*args, check=True):
        command = [mpremote, "connect", port, "resume"] + list(args)
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=90)
        out = (result.stdout + result.stderr).strip()
        if check and result.returncode != 0:
            raise SystemExit("mpremote %s failed: %s" % (" ".join(args), out))
        return out

    print("==> push to %s + /lib/coresys over %s" % (DEVICE_DIR, port))
    # NB: mpremote needs the ':' prefix for remote ABSOLUTE paths, or it
    # treats them as local (verified on-device).
    mp("fs", "mkdir", ":" + DEVICE_DIR, check=False)  # exists -> harmless
    for device_dir, path in files:
        mp("fs", "cp", str(path), ":%s/%s" % (device_dir, path.name))
    listed = (mp("fs", "ls", ":" + DEVICE_DIR) + "\n"
              + mp("fs", "ls", ":/lib/coresys"))
    missing = [path.name for _, path in files
               if path.name not in listed.split()]
    if missing:  # mpremote cp can exit 0 and still drop the file (AGENTS.md)
        raise SystemExit("push verification failed, missing: %s"
                         % ", ".join(missing))
    print("    pushed %d files and verified" % len(files))
    mp("reset")  # required: the USB pass stopped the running app
    print("==> board reset; app runs autonomously again")


def do_run(app_root, target, pattern, shell_port, ip_file):
    """Drive the shell's 'test run' over the network (no USB).

    A full suite can run for minutes inside the app's loop, so the shell's
    idle window (telnet.py's OTC_CMD_IDLE_TIMEOUT) is raised accordingly,
    and a board that is still booting (e.g. right after a USB push reset)
    gets a bounded retry before the run is declared unreachable. Output is
    streamed live (each device-side progress line as it arrives) while it
    is also collected for the RESULT verdict -- no silent multi-minute
    window that looks like a hang.
    """
    ip_address = resolve_device_ip(app_root, target, ip_file)
    telnet = framework_root() / "tools" / "target" / "telnet.py"
    base = [str(project_python(app_root, required=False)), str(telnet),
            ip_address, str(shell_port)]
    command = base + ["test", "run"]
    if pattern:
        command.append(pattern)

    # Wait (bounded) for the shell BEFORE starting the run: the run window
    # is huge (a suite may take minutes), so applying it to a banner read
    # on a mid-boot board would hang one attempt for that whole window.
    probe_env = os.environ.copy()
    probe_env["OTC_CMD_TIMEOUT"] = "10"
    deadline = time.monotonic() + 90
    while True:
        probe = subprocess.run(base + ["status"], capture_output=True,
                               text=True, timeout=30, env=probe_env)
        if '"version"' in probe.stdout or time.monotonic() >= deadline:
            break
        time.sleep(5)

    env = os.environ.copy()
    env.setdefault("OTC_CMD_IDLE_TIMEOUT", "900")
    proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env)
    lines = []
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        lines.append(line)
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("==> telnet client did not exit after the stream ended")
    output = "".join(lines).strip()
    for line in output.splitlines():
        if line.startswith(RESULT_PREFIX):
            if " 0 failed" in line:
                print("==> AUTOTEST OK (%s)" % line)
                return 0
            print("==> AUTOTEST FAILED (%s)" % line)
            return 1
    print("==> no RESULT line (shell down / board mid-boot / timeout?)")
    return 1


def _env_ip():
    return os.environ.get("OTC_IP") or os.environ.get("DEVICE_IP")


def main(argv=None):
    args = parse_args(argv)
    app_root = resolve_app_root(args.app_root)
    target, pattern = split_target_pattern(args.tokens)
    if args.stage in ("push", "sync"):
        do_push(app_root)
    if args.stage in ("run", "sync"):
        return do_run(app_root, target, pattern, args.shell_port,
                      args.ip_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
