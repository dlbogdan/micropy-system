#!/usr/bin/env python3
"""Host-side client for a micropy-system device shell."""

import argparse
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tooling import framework_root, project_python, resolve_app_root


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root")
    parser.add_argument("command", nargs="?", default="help",
                        choices=("status", "log", "selftest", "reboot", "update",
                                 "console", "discover", "help"))
    parser.add_argument("arguments", nargs="*")
    return parser.parse_args(argv)


def resolve_ip(value=None):
    ip_address = value or os.environ.get("OTC_IP") or os.environ.get("DEVICE_IP")
    if not ip_address:
        raise ValueError(
            "no device IP; pass it as an argument or set OTC_IP/DEVICE_IP")
    return ip_address


def exec_python(python, script, *arguments):
    os.execv(str(python), [str(python), str(script), *map(str, arguments)])


def main(argv=None):
    args = parse_args(argv)
    if args.command == "help":
        parse_args(["--help"])
        return 0
    root = framework_root()
    app_root = resolve_app_root(args.app_root)
    python = project_python(app_root, required=False)
    shell_port = int(os.environ.get("OTC_SHELL_PORT",
                                    os.environ.get("SHELL_PORT", "23")))
    telnet = root / "tools" / "target" / "telnet.py"

    if args.command == "discover":
        port = args.arguments[0] if args.arguments else shell_port
        exec_python(python, root / "tools" / "target" / "discover.py", port)
    if args.command == "log":
        first = args.arguments[0] if args.arguments else None
        if first and first.isdigit():
            ip_address = resolve_ip()
            count = first
        else:
            ip_address = resolve_ip(first)
            count = args.arguments[1] if len(args.arguments) > 1 else "40"
        exec_python(python, telnet, ip_address, shell_port, "log", count)

    ip_address = resolve_ip(args.arguments[0] if args.arguments else None)
    if args.command in ("reboot", "update"):
        print("Requesting reboot of %s (boot-time OTA check enabled)..." % ip_address)
        result = subprocess.call(
            [str(python), str(telnet), ip_address, str(shell_port), "reboot"])
        if result == 0:
            print("Device is rebooting; re-check status in a few seconds.")
        return result
    if args.command == "console":
        exec_python(python, telnet, ip_address, shell_port)
    exec_python(python, telnet, ip_address, shell_port, args.command)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError) as error:
        raise SystemExit("Error: %s" % error)
