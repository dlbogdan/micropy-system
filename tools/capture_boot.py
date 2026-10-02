#!/usr/bin/env python3
"""Capture serial output across a Pico reset on macOS or Linux."""

import argparse
import sys
import threading
import time

from tooling import find_serial_port


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", help="USB serial port (auto-detected)")
    parser.add_argument("seconds", nargs="?", type=float, default=30.0)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        import serial
    except ImportError:
        raise SystemExit("pyserial is missing; run tools/setup_build_env.sh")
    port = find_serial_port(args.port)
    if not port:
        raise SystemExit(
            "No serial port found; connect the Pico or pass /dev/... explicitly")

    captured = []
    stop = threading.Event()

    def reader():
        with serial.Serial(port, 115200, timeout=0.5) as connection:
            connection.reset_input_buffer()
            # DTR/RTS toggle resets the Pico (like mpremote does).
            time.sleep(0.1)
            connection.dtr = False
            connection.rts = True
            while not stop.is_set():
                count = connection.in_waiting
                if count:
                    data = connection.read(count)
                    captured.append(data)
                    sys.stdout.write(data.decode("utf-8", "replace"))
                    sys.stdout.flush()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    time.sleep(args.seconds)
    stop.set()
    thread.join(timeout=2)
    print("\n=== capture done (%d bytes) ===" %
          sum(len(chunk) for chunk in captured))


if __name__ == "__main__":
    main()
