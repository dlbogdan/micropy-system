#!/usr/bin/env python3
"""Build, serve and deploy an application update over the network or USB."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tooling import framework_root, project_python, resolve_app_root


SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?")
    parser.add_argument("--usb", action="store_true")
    parser.add_argument("--app-root")
    parser.add_argument("--version-file", default="app/version.txt")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--shell-port", type=int,
                        default=int(os.environ.get("OTC_SHELL_PORT", "23")))
    parser.add_argument("--ip-file", default=".micropy-device-ip")
    return parser.parse_args(argv)


def next_patch(version):
    if not SEMVER.fullmatch(version.strip()):
        raise ValueError("version must be MAJOR.MINOR.PATCH")
    major, minor, patch = (int(part) for part in version.strip().split("."))
    return "%d.%d.%d" % (major, minor, patch + 1)


def run(command, **kwargs):
    return subprocess.run([str(part) for part in command], check=True, **kwargs)


def metadata_available(port):
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/metadata.json" % port,
                timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def telnet(python, root, ip_address, port, command, timeout=10):
    environment = os.environ.copy()
    environment["OTC_CMD_TIMEOUT"] = str(timeout)
    try:
        result = subprocess.run(
            [str(python), str(root / "tools" / "target" / "telnet.py"), ip_address,
             str(port), *command], capture_output=True, text=True,
            timeout=timeout + 2, env=environment, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def parse_status(payload):
    try:
        data = json.loads(payload)
        slot = data.get("slot") or {}
        return data.get("version"), slot.get("active"), slot.get("rejected")
    except (TypeError, ValueError, AttributeError):
        return None


def wait_for_network_promotion(python, root, ip_address, shell_port,
                               version, timeout=240):
    started = time.monotonic()
    last_state = None
    while time.monotonic() - started < timeout:
        elapsed = int(time.monotonic() - started)
        raw = telnet(python, root, ip_address, shell_port, ["status"], timeout=6)
        if raw and raw.startswith("busy"):
            print("    [t=%ds] shell busy; retrying..." % elapsed)
        elif raw:
            state = parse_status(raw)
            if state:
                last_state = state
                current, active, rejected = state
                if current == version and rejected is None:
                    return active, elapsed
                if rejected is not None:
                    raise RuntimeError(
                        "candidate rejected (rejected_version=%s)" % rejected)
                print("    [t=%ds] up as %s (want %s); waiting..." %
                      (elapsed, current, version))
            else:
                print("    [t=%ds] unexpected reply; retrying..." % elapsed)
        else:
            print("    [t=%ds] board down (expected mid-OTA); retrying..." %
                  elapsed)
        time.sleep(2)
    raise RuntimeError("board did not promote to %s (last state: %s)" %
                       (version, last_state or "unreachable"))


def wait_for_usb_promotion(root, version, timeout=240):
    started = time.monotonic()
    code = ("import ujson as j; s=j.load(open('/ota-state.json')); "
            "v=open('/version.txt').read().strip(); "
            "print(v+'|'+str(s.get('active'))+'|'+"
            "str(s.get('rejected_version')))")
    last = "unreachable"
    while time.monotonic() - started < timeout:
        elapsed = int(time.monotonic() - started)
        result = subprocess.run(
            [str(root / "tools" / "target" / "device.py"), "exec", code],
            capture_output=True, text=True, check=False)
        lines = (result.stdout + result.stderr).splitlines()
        last = lines[-1].strip() if lines else ""
        parts = last.split("|")
        if len(parts) == 3 and SEMVER.fullmatch(parts[0]):
            current, active, rejected = parts
            if current == version and rejected == "None":
                return active
            if rejected != "None":
                raise RuntimeError(
                    "candidate rejected (rejected_version=%s)" % rejected)
        else:
            print("    [t=%ds] board busy/unreachable; retrying..." % elapsed)
        time.sleep(4)
    raise RuntimeError("board did not promote to %s (last state: %s)" %
                       (version, last))


def resolve_device_ip(args, python, root, app_root):
    explicit = os.environ.get("DEVICE_IP") or os.environ.get("OTC_IP")
    if explicit:
        return explicit
    ip_file = Path(args.ip_file)
    if not ip_file.is_absolute():
        ip_file = app_root / ip_file
    if ip_file.is_file():
        candidate = ip_file.read_text().strip()
        if candidate and telnet(
                python, root, candidate, args.shell_port, ["status"]):
            print("    using remembered IP %s" % candidate)
            return candidate
    result = subprocess.run(
        [str(python), str(root / "tools" / "target" / "discover.py"),
         str(args.shell_port)], capture_output=True, text=True, check=False)
    match = re.search(r"Found device: ([0-9.]+)", result.stdout)
    return match.group(1) if match else None


def deploy(args):
    root = framework_root()
    app_root = resolve_app_root(args.app_root)
    python = project_python(app_root)
    version_file = Path(args.version_file)
    if not version_file.is_absolute():
        version_file = app_root / version_file

    if args.version:
        version = args.version
    else:
        version = next_patch(version_file.read_text())
        version_file.write_text(version + "\n")
    if not SEMVER.fullmatch(version):
        raise ValueError("version must be MAJOR.MINOR.PATCH")
    print("==> Deploying version %s" % version)

    build_log = Path(tempfile.gettempdir()) / "msy-deploy-build.log"
    print("==> Building (log: %s)..." % build_log)
    started = time.monotonic()
    with build_log.open("w") as output:
        result = subprocess.run(
            [str(root / "tools" / "build" / "build_firmware.py"), "--app-root",
             str(app_root), version], stdout=output, stderr=subprocess.STDOUT,
            check=False)
    if result.returncode != 0:
        tail = build_log.read_text(errors="replace").splitlines()[-30:]
        raise RuntimeError("build failed:\n" + "\n".join(tail))
    print("==> Build OK (%ds)" % int(time.monotonic() - started))

    if not metadata_available(args.port):
        serve_log = Path(tempfile.gettempdir()) / "msy-deploy-serve.log"
        print("==> Starting update server on :%d" % args.port)
        output = serve_log.open("a")
        subprocess.Popen(
            [str(root / "tools" / "target" / "serve_update.py"), str(args.port),
             "--app-root", str(app_root)], stdout=output,
            stderr=subprocess.STDOUT, start_new_session=True)
        for _ in range(30):
            if metadata_available(args.port):
                break
            time.sleep(0.5)
    else:
        print("==> Update server already running on :%d" % args.port)
    if not metadata_available(args.port):
        raise RuntimeError("update server not reachable on :%d" % args.port)

    if args.usb:
        print("==> Resetting board via USB (triggers OTA check)")
        subprocess.run([str(root / "tools" / "target" / "device.py"), "reset"],
                       check=False)
        print("==> Waiting for OTA install + slot promotion...")
        active = wait_for_usb_promotion(root, version)
        print("==> Promoted: version=%s active_slot=%s" % (version, active))
        print("==> Running on-device self-test (USB)")
        run([root / "tools" / "target" / "device.py", "selftest"])
        print("==> Restarting application after USB self-test")
        subprocess.run([str(root / "tools" / "target" / "device.py"), "reset"],
                       check=False)
        print("==> DEPLOY OK: %s is active, tested, and restarting." % version)
        return 0

    print("==> Resolving device IP")
    ip_address = resolve_device_ip(args, python, root, app_root)
    if not ip_address:
        raise RuntimeError(
            "device not found on the LAN; set OTC_IP=<ip> to skip discovery")
    ip_file = Path(args.ip_file)
    if not ip_file.is_absolute():
        ip_file = app_root / ip_file
    ip_file.write_text(ip_address + "\n")
    print("==> Target: shell %s:%d" % (ip_address, args.shell_port))
    if not telnet(python, root, ip_address, args.shell_port, ["status"]):
        raise RuntimeError("device shell is unreachable")

    print("==> Rebooting board over its shell (triggers boot-time OTA check)")
    telnet(python, root, ip_address, args.shell_port, ["reboot"])
    print("==> Waiting for OTA install + slot promotion...")
    active, elapsed = wait_for_network_promotion(
        python, root, ip_address, args.shell_port, version)
    print("==> Promoted: version=%s active_slot=%s (board down ~%ds)" %
          (version, active, elapsed))

    print("==> Running on-device self-test (shell)")
    response = telnet(
        python, root, ip_address, args.shell_port, ["selftest"], timeout=30)
    if response is None:
        raise RuntimeError("self-test request failed")
    print(response)
    if not response.startswith("PASS"):
        raise RuntimeError("on-device self-test failed")
    print("==> DEPLOY OK: %s is active, self-tested, and left running." % version)
    return 0


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    args = parse_args(argv)
    try:
        return deploy(args)
    except (FileNotFoundError, RuntimeError, ValueError,
            subprocess.CalledProcessError) as error:
        print("Error: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
