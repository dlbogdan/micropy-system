#!/usr/bin/env python3
"""Resolve a micropy-system device system-config.json.

Reads a base config (the project's local ``system-config.json``, or the
``system-config.example.json`` template), applies Wi-Fi credential overrides,
and populates the FIRMWARE (OTA) section from an update-source file:

    mode "local"   -> FIRMWARE.DIRECT_BASE_URL (local update server)
    mode "github"  -> FIRMWARE.GITHUB_REPO (+ optional token)
    no usable source -> FIRMWARE.UPDATE_ON_BOOT forced false (no 404 noise at boot)

The result is written to --out; the board reads /system-config.json at boot.
"""

import argparse
import json
import os
import subprocess
import sys


def framework_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_app_root(cli_value=None):
    """Project root: --app-root flag > MICROPY_APP_ROOT > git superproject > CWD."""
    if cli_value:
        return os.path.abspath(cli_value)
    env = os.environ.get("MICROPY_APP_ROOT")
    if env:
        return os.path.abspath(env)
    root = framework_root()
    try:
        proc = subprocess.run(
            ["git", "-C", root, "rev-parse", "--show-superproject-working-tree"],
            capture_output=True, text=True, timeout=10)
        if proc.returncode == 0 and proc.stdout.strip():
            return os.path.abspath(proc.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return os.getcwd()


def render(base, out, ssid="", passwd="", name="", update_source=None):
    """Render the base config with Wi-Fi/OTA overrides; return the rendered dict."""
    with open(base) as f:
        cfg = json.load(f)

    dev = cfg.setdefault("DEVICE", {})
    if (not dev.get("NAME") or dev.get("NAME") == "micropy-system-test") and name:
        dev["NAME"] = name

    w = cfg.setdefault("WIFI", {})
    if ssid:
        w["SSID"] = ssid
    if passwd:
        w["PASS"] = passwd
    if w.get("SSID") == "your-wifi-ssid":   # example placeholder -- clear it
        w["SSID"] = ""
        w["PASS"] = ""

    # Populate the FIRMWARE (OTA) section from the update-source file:
    # mode "local"   -> DIRECT_BASE_URL (update server, e.g. tools/serve_update.py)
    # mode "github"  -> GITHUB_REPO (+ optional token) for release-based OTA
    fw = cfg.setdefault("FIRMWARE", {})
    us = None
    if update_source and os.path.exists(update_source):
        with open(update_source) as f:
            us = json.load(f)
    source_ok = False
    if us:
        if us.get("mode") == "local":
            b = (us.get("local") or {}).get("base_url") or ""
            if b:
                fw["DIRECT_BASE_URL"] = b
                fw["GITHUB_REPO"] = None
                fw["GITHUB_TOKEN"] = ""
                source_ok = True
                print("    OTA source: local update server %s" % b)
        elif us.get("mode") == "github":
            gh = us.get("github") or {}
            if gh.get("repo"):
                fw["GITHUB_REPO"] = gh["repo"]
                fw["GITHUB_TOKEN"] = gh.get("token", "")
                fw["DIRECT_BASE_URL"] = None
                source_ok = True
                print("    OTA source: GitHub %s" % gh["repo"])
        if source_ok:
            fw["UPDATE_ON_BOOT"] = bool(us.get("update_on_boot", True))
    if not source_ok:
        fw["UPDATE_ON_BOOT"] = False
        print("    NOTE: no usable update source (update-source.json) --"
              " UPDATE_ON_BOOT disabled (no OTA check at boot).")

    with open(out, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    if not w.get("SSID"):
        print("    NOTE: WIFI.SSID is empty -- the board will boot offline.")
    return cfg


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Resolve a device system-config.json (Wi-Fi + OTA source).")
    p.add_argument("--out", required=True,
                   help="output path for the resolved config")
    p.add_argument("--base", default=None,
                   help="base config (default: <app-root>/system-config.json, "
                        "else <app-root>/system-config.example.json)")
    p.add_argument("--ssid", default="", help="WIFI.SSID override")
    p.add_argument("--pass", dest="passwd", default="", help="WIFI.PASS override")
    p.add_argument("--name", default="",
                   help="DEVICE.NAME (applied when the base has none or the template name)")
    p.add_argument("--update-source", default=None,
                   help="update-source.json (default: <app-root>/update-source.json)")
    p.add_argument("--app-root", default=None, help="application project root")
    args = p.parse_args(argv)

    app_root = resolve_app_root(args.app_root)
    if args.base:
        base = args.base
    else:
        base = os.path.join(app_root, "system-config.json")
        if not os.path.exists(base):
            base = os.path.join(app_root, "system-config.example.json")
    if not os.path.exists(base):
        sys.exit("Error: no base config found (looked for system-config.json / "
                 "system-config.example.json under %s)" % app_root)
    update_source = args.update_source or os.path.join(app_root, "update-source.json")
    render(base, args.out, ssid=args.ssid, passwd=args.passwd,
           name=args.name, update_source=update_source)
    print("Wrote %s" % args.out)


if __name__ == "__main__":
    main()
