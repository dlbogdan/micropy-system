#!/usr/bin/env python3
"""Run the device baseline through mpremote and save its JSON report."""

import argparse
import json
from pathlib import Path
import subprocess
import sys


REPORT_START = "=== MICROPY_SYSTEM_BASELINE_BEGIN ==="
REPORT_END = "=== MICROPY_SYSTEM_BASELINE_END ==="
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEVICE_SCRIPT = PROJECT_ROOT / "tools" / "device_baseline.py"
DEFAULT_OUTPUT = PROJECT_ROOT / "hardware-baseline.json"


def parse_report(output):
    try:
        payload = output.split(REPORT_START, 1)[1].split(REPORT_END, 1)[0]
    except IndexError as exc:
        raise ValueError("Device output did not contain a complete baseline report") from exc
    return json.loads(payload.strip())


def build_command(port):
    # Prefer the mpremote installed beside the active Python interpreter. This
    # keeps capture working when invoked as `.venv/bin/python ...` without
    # requiring virtual-environment activation.
    local_mpremote = Path(sys.prefix) / "bin" / "mpremote"
    command = [str(local_mpremote) if local_mpremote.exists() else "mpremote"]
    if port:
        command.extend(["connect", port])
    command.extend(["run", str(DEVICE_SCRIPT)])
    return command


def main():
    parser = argparse.ArgumentParser(
        description="Capture Pico/MicroPython runtime and rename behavior"
    )
    parser.add_argument(
        "--port",
        help="mpremote serial port, for example /dev/cu.usbmodem1101; omit for auto",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="JSON output path (default: hardware-baseline.json)",
    )
    args = parser.parse_args()

    try:
        process = subprocess.run(
            build_command(args.port),
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print(
            "mpremote is not installed. Run: python3 -m pip install -r requirements-dev.txt",
            file=sys.stderr,
        )
        return 2
    except subprocess.CalledProcessError as exc:
        print(exc.stdout, file=sys.stderr)
        print(exc.stderr, file=sys.stderr)
        return exc.returncode or 1

    try:
        report = parse_report(process.stdout)
    except (ValueError, json.JSONDecodeError) as exc:
        print("Could not parse the device report: {}".format(exc), file=sys.stderr)
        print(process.stdout, file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Wrote baseline to {}".format(args.output))
    print(
        "MicroPython {} | MPY {} | filesystem {} bytes total, {} bytes free".format(
            ".".join(str(part) for part in report["implementation"]["version"][:3]),
            report["implementation"]["mpy_version"],
            report["filesystem"]["total_bytes"],
            report["filesystem"]["free_bytes"],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
