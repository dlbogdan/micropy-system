#!/usr/bin/env python3
"""Provision a Pico W/Pico 2 W completely over USB on macOS or Linux.

The operation flashes pinned MicroPython, formats LittleFS, uploads the
framework/application tree and resolved configuration, then performs one final
USB reset before validating autonomous operation over the network shell.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from tooling import (eject_volume, find_or_mount_boot_volume, find_serial_port,
                     framework_root, project_executable, project_python,
                     resolve_app_root)


UF2_FILES = {
    "pico2-w": "RPI_PICO2_W-20260824-v1.29.0.uf2",
    "pico-w": "RPI_PICO_W-20260824-v1.29.0.uf2",
}
UF2_BASE_URL = "https://micropython.org/resources/firmware/"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", choices=sorted(UF2_FILES), default="pico2-w")
    parser.add_argument("--ssid", default="")
    parser.add_argument("--pass", dest="password", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--base")
    parser.add_argument("--update-source")
    parser.add_argument("--boot-marker", default="entering main loop")
    parser.add_argument("--ip-file", default=".micropy-device-ip")
    parser.add_argument("--shell-port", type=int, default=23)
    parser.add_argument("--skip-shell", action="store_true")
    parser.add_argument("--app-root")
    return parser.parse_args(argv)


def run(command, **kwargs):
    return subprocess.run([str(part) for part in command], check=True, **kwargs)


def wait_until(check, timeout, interval=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(interval)
    return None


def choose_config(app_root, explicit=None):
    candidates = ([Path(explicit)] if explicit else [
        app_root / "system-config.json",
        app_root / "system-config.example.json",
    ])
    for candidate in candidates:
        path = candidate if candidate.is_absolute() else app_root / candidate
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError(
        "no base config found (--base, system-config.json, or "
        "system-config.example.json)")


def download_uf2(path, url):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size >= 200000:
        return
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=300) as response, \
                temporary.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        if temporary.stat().st_size < 200000:
            raise RuntimeError("downloaded UF2 is unexpectedly small")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def copy_uf2(source, volume):
    """Plain byte copy avoids macOS extended-attribute failures on FAT."""
    target = volume / source.name
    target.unlink(missing_ok=True)
    time.sleep(1)
    with source.open("rb") as incoming, target.open("wb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if hasattr(os, "sync"):
        os.sync()


def stage_device_tree(source, destination):
    def ignore(_directory, names):
        return {name for name in names
                if name == "__pycache__" or name.endswith(".pyc")
                or name in (".DS_Store", ".micropy-system-device-tree")}
    shutil.copytree(source, destination, ignore=ignore, dirs_exist_ok=True)


def mpremote(mpremote_path, port, *arguments, check=True, capture_output=False,
             **kwargs):
    return subprocess.run(
        [str(mpremote_path), "connect", str(port), "resume",
         *[str(arg) for arg in arguments]],
        check=check, text=True, capture_output=capture_output, **kwargs)


def capture_boot(port, expect_wifi, marker, timeout=90):
    """Passively capture boot completion and DHCP without entering raw REPL."""
    import serial

    deadline = time.monotonic() + timeout
    stream = ""
    main_seen = False
    ip_address = ""
    connection = None
    try:
        while time.monotonic() < deadline:
            if connection is None:
                try:
                    connection = serial.Serial(port, 115200, timeout=0.5)
                except (OSError, serial.SerialException):
                    time.sleep(0.25)
                    continue
            try:
                chunk = connection.read(connection.in_waiting or 1)
            except (OSError, serial.SerialException):
                try:
                    connection.close()
                except Exception:
                    pass
                connection = None
                time.sleep(0.25)
                continue
            if not chunk:
                continue
            stream = (stream + chunk.decode("utf-8", "replace"))[-16384:]
            main_seen = main_seen or marker in stream
            matches = re.findall(
                r"WiFiManager: Connected to .*? \((\d{1,3}(?:\.\d{1,3}){3})\)",
                stream)
            if matches and matches[-1] != "0.0.0.0":
                ip_address = matches[-1]
            if main_seen and (not expect_wifi or ip_address):
                break
    finally:
        if connection is not None:
            connection.close()
    return main_seen, ip_address


def shell_status(python, root, ip_address, port, timeout=10):
    try:
        result = subprocess.run(
            [str(python), str(root / "tools" / "telnet.py"), ip_address,
             str(port), "status"], capture_output=True, text=True,
            timeout=timeout, check=False)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def ensure_venv_python(app_root):
    """Re-exec under the project venv so pyserial is available."""
    python = project_python(app_root)
    if os.environ.get("MICROPY_PROVISION_BOOTSTRAPPED") == "1":
        return python
    same = (Path(sys.prefix).resolve() == (app_root / ".venv").resolve()
            or os.path.abspath(sys.executable) == os.path.abspath(str(python)))
    if not same:
        environment = os.environ.copy()
        environment["MICROPY_PROVISION_BOOTSTRAPPED"] = "1"
        os.execve(str(python), [str(python), str(Path(__file__).resolve()),
                               *sys.argv[1:]], environment)
    return python


def provision(args):
    root = framework_root()
    app_root = resolve_app_root(args.app_root)
    python = ensure_venv_python(app_root)
    mpremote_path = project_executable(app_root, "mpremote")
    if not mpremote_path.is_file():
        raise FileNotFoundError(
            "mpremote not found in .venv; run tools/setup_build_env.py")

    config_source = choose_config(app_root, args.base)
    if config_source.name == "system-config.example.json":
        print("==> No local system-config.json -- using the example template")

    print("==> Assembling a fresh device tree")
    run([python, root / "tools" / "assemble.py", "--app-root", app_root],
        stdout=subprocess.DEVNULL)
    device = app_root / "device"
    if not (device / "boot.py").is_file() or not (device / "main.py").is_file():
        raise RuntimeError("device tree missing after assemble.py")
    print("==> Device tree ready (board: %s)" % args.board)

    uf2_name = UF2_FILES[args.board]
    uf2_path = app_root / ".cache" / "uf2" / uf2_name
    print("==> Checking MicroPython 1.29.0 firmware (%s)" % args.board)
    download_uf2(uf2_path, UF2_BASE_URL + uf2_name)
    print("==> Firmware: %s (%d bytes)" % (uf2_path, uf2_path.stat().st_size))

    port = find_serial_port(os.environ.get("SERIAL_PORT"))
    print("==> Waiting for the Pico bootrom volume (board in BOOTSEL)...")
    volume = find_or_mount_boot_volume()
    if volume:
        print("    volume already mounted: %s" % volume)
    else:
        if port:
            print("    board running on %s -- entering bootloader" % port)
            mpremote(mpremote_path, port, "bootloader", check=False,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            print("    No serial port visible. Plug the Pico in with BOOTSEL held.")
        volume = wait_until(find_or_mount_boot_volume, 180)
        if not volume:
            raise RuntimeError("no Pico bootrom volume appeared within 180s")
        print("    volume: %s" % volume)

    print("==> Flashing firmware (code partition only)")
    copy_uf2(uf2_path, volume)
    eject_volume(volume)
    print("==> Ejected; board should now boot MicroPython")

    port = wait_until(find_serial_port, 120)
    if not port:
        raise RuntimeError("the board's serial port never appeared")
    print("==> Serial port: %s" % port)
    time.sleep(1)

    print("==> Formatting the data filesystem (wipes old apps/state/config)")
    format_code = """from rp2 import Flash
from os import umount, mount, VfsLfs2
flash = Flash()
umount('/')
VfsLfs2.mkfs(flash)
mount(flash, '/')
print('LFS formatted')"""
    mpremote(mpremote_path, port, "exec", format_code)

    print("==> Resetting once to remount the fresh filesystem")
    mpremote(mpremote_path, port, "reset", check=False,
             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)

    with tempfile.TemporaryDirectory(prefix="msy-provision-") as directory:
        temporary = Path(directory)
        stage = temporary / "device"
        config_output = temporary / "system-config.json"
        print("==> Staging a clean copy")
        stage_device_tree(device, stage)
        print("==> Uploading device tree")
        for item in sorted(stage.iterdir()):
            mpremote(mpremote_path, port, "cp", "-r", "-f", item, ":/")

        update_source = (Path(args.update_source) if args.update_source else
                         app_root / "update-source.json")
        if not update_source.is_absolute():
            update_source = app_root / update_source
        print("==> Resolving system-config.json")
        run([python, root / "tools" / "render_config.py",
             "--out", config_output, "--base", config_source,
             "--ssid", args.ssid, "--pass", args.password,
             "--name", args.name, "--update-source", update_source])
        print("==> Uploading system-config.json")
        mpremote(mpremote_path, port, "cp", "-f", config_output,
                 ":/system-config.json")

        version_file = app_root / "app" / "version.txt"
        if version_file.is_file():
            expected = version_file.read_text().strip()
            actual = ""
            print("==> Uploading version.txt last")
            for attempt in range(1, 4):
                mpremote(mpremote_path, port, "cp", "-f", version_file,
                         ":/version.txt", check=False)
                result = mpremote(mpremote_path, port, "cat", ":/version.txt",
                                  check=False, capture_output=True)
                actual = result.stdout.strip()
                if actual == expected:
                    break
                print("    version read-back mismatch (attempt %d)" % attempt)
                time.sleep(2)
            if actual != expected:
                print("WARNING: /version.txt could not be verified; first boot "
                      "will self-heal through OTA", file=sys.stderr)

        final_config = json.loads(config_output.read_text())
        final_ssid = final_config.get("WIFI", {}).get("SSID", "") or ""

    print("==> Verifying app boot and DHCP (passive USB serial)")
    mpremote(mpremote_path, port, "reset", check=False,
             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    main_seen, detected_ip = capture_boot(
        port, bool(final_ssid), args.boot_marker)
    if not main_seen:
        raise RuntimeError("the app did not reach its main loop within 90s")
    print("==> App booted and reached the main loop")
    if detected_ip:
        print("==> Board reported DHCP address: %s" % detected_ip)
    elif final_ssid:
        print("    note: Wi-Fi did not receive DHCP within 90s")

    # This must remain the final USB operation.
    print("==> Final reset (restores autonomous execution)")
    mpremote(mpremote_path, port, "reset", check=False,
             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not final_ssid:
        print("==> PROVISION OK (USB-verified; board is intentionally offline)")
        return 0
    if args.skip_shell:
        print("==> PROVISION OK (USB-verified; shell check skipped)")
        return 0

    ip_address = (os.environ.get("DEVICE_IP") or os.environ.get("OTC_IP")
                  or detected_ip)
    if ip_address:
        print("==> Checking Wi-Fi autonomy at shell %s:%d" %
              (ip_address, args.shell_port))
        def connected_status():
            status = shell_status(python, root, ip_address, args.shell_port)
            if status and (status.get("wifi") or {}).get("state") == "Connected":
                return status
            return None

        status = wait_until(connected_status, 60, interval=3)
        if status:
            ip_file = Path(args.ip_file)
            if not ip_file.is_absolute():
                ip_file = app_root / ip_file
            ip_file.write_text(ip_address + "\n")
            print("==> PROVISION OK: %s is autonomous at %s (shell :%d)" %
                  (args.board, ip_address, args.shell_port))
            return 0
        print("    note: device did not report connected Wi-Fi within 60s")
    print("==> PROVISION OK (USB-verified; network address not confirmed)")
    return 0


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    args = parse_args(argv)
    try:
        return provision(args)
    except (FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as error:
        print("Error: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
