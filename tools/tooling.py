#!/usr/bin/env python3
"""Shared, cross-platform helpers for micropy-system host tools."""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


BOOT_LABELS = ("RPI-RP2", "RP2350")
PICO_USB_VID = 0x2E8A


def framework_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_app_root(explicit=None) -> Path:
    """Resolve app root: argument, environment, Git superproject, then CWD."""
    value = explicit or os.environ.get("MICROPY_APP_ROOT")
    if value:
        return Path(value).expanduser().resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(framework_root()), "rev-parse",
             "--show-superproject-working-tree"],
            capture_output=True, text=True, timeout=10, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd().resolve()


def project_python(app_root: Path, required=True) -> Path:
    """Return the project venv interpreter, or host Python when permitted."""
    executable = "python.exe" if os.name == "nt" else "python"
    candidate = app_root / ".venv" / ("Scripts" if os.name == "nt" else "bin") / executable
    if candidate.is_file():
        return candidate
    if required:
        raise FileNotFoundError(
            "build environment is missing; run tools/setup_build_env.sh")
    return Path(sys.executable)


def project_executable(app_root: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return app_root / ".venv" / ("Scripts" if os.name == "nt" else "bin") / (name + suffix)


def git_output(*args, cwd=None) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()


def serial_ports():
    """Return likely MicroPython USB serial ports on macOS and Linux."""
    detected = []
    try:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
        ports.sort(key=lambda item: (item.vid != PICO_USB_VID, item.device))
        for item in ports:
            device = item.device or ""
            usb_path = ("usb" in device.lower() or "ttyacm" in device.lower())
            if device and (item.vid == PICO_USB_VID or usb_path):
                detected.append(device)
    except (ImportError, OSError):
        pass

    patterns = (
        "/dev/cu.usbmodem*", "/dev/cu.usbserial*", "/dev/tty.usbmodem*",
        "/dev/ttyACM*", "/dev/ttyUSB*",
    )
    for pattern in patterns:
        detected.extend(sorted(glob.glob(pattern)))
    return list(dict.fromkeys(detected))


def find_serial_port(explicit=None):
    if explicit:
        return str(explicit) if Path(explicit).exists() else None
    ports = serial_ports()
    return ports[0] if ports else None


def _linux_lsblk_mounts():
    try:
        output = subprocess.check_output(
            ["lsblk", "--json", "--output", "LABEL,MOUNTPOINT,MOUNTPOINTS"],
            text=True, stderr=subprocess.DEVNULL, timeout=10)
        devices = json.loads(output).get("blockdevices", [])
    except (OSError, subprocess.SubprocessError, ValueError):
        return []

    found = []

    def visit(device):
        label = device.get("label")
        mounts = device.get("mountpoints") or [device.get("mountpoint")]
        if label in BOOT_LABELS:
            found.extend(mount for mount in mounts if mount)
        for child in device.get("children") or []:
            visit(child)

    for device in devices:
        visit(device)
    return found


def boot_volume_candidates(system=None, home=None):
    """Return standard boot-volume paths for macOS and desktop Linux."""
    system = system or platform.system()
    explicit_home = home is not None
    home = Path(home or Path.home())
    if system == "Darwin":
        roots = [Path("/Volumes")]
    elif system == "Linux":
        user = home.name if explicit_home else (os.environ.get("USER") or home.name)
        roots = [Path("/media") / user, Path("/run/media") / user,
                 Path("/media"), Path("/mnt")]
    else:
        roots = []
    return [root / label for root in roots for label in BOOT_LABELS]


def find_boot_volume(system=None, candidates=None):
    """Find a mounted Pico BOOTSEL volume on macOS or Linux."""
    system = system or platform.system()
    paths = []
    if system == "Linux":
        paths.extend(Path(path) for path in _linux_lsblk_mounts())
    paths.extend(Path(path) for path in (
        candidates if candidates is not None else boot_volume_candidates(system)))
    for path in paths:
        if path.is_dir():
            return path.resolve()
    return None


def eject_volume(path: Path):
    """Best-effort unmount/eject for macOS and Linux."""
    path = Path(path)
    if platform.system() == "Darwin" and shutil_which("diskutil"):
        subprocess.run(["diskutil", "eject", str(path)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=False)
        return
    if platform.system() == "Linux":
        source = ""
        if shutil_which("findmnt"):
            result = subprocess.run(
                ["findmnt", "-n", "-o", "SOURCE", "--target", str(path)],
                capture_output=True, text=True, check=False)
            source = result.stdout.strip()
        if source and shutil_which("udisksctl"):
            subprocess.run(["udisksctl", "unmount", "-b", source],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False)
            return
    if shutil_which("umount"):
        subprocess.run(["umount", str(path)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)


def shutil_which(command):
    # Kept behind a function so platform behavior is easy to mock in tests.
    import shutil
    return shutil.which(command)
