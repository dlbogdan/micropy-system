#!/usr/bin/env python3
"""Capture live serial output across a board reset to see the reset cause / crash.

Usage: capture_boot.py [PORT] [SECONDS]

PORT defaults to the first /dev/cu.usbmodem* (macOS) or /dev/ttyACM* (Linux)
device. The DTR/RTS toggle resets the Pico like mpremote does.
"""
import glob
import sys
import threading
import time

import serial

if len(sys.argv) > 1:
    PORT = sys.argv[1]
else:
    ports = sorted(glob.glob("/dev/cu.usbmodem*")) + sorted(glob.glob("/dev/ttyACM*"))
    if not ports:
        sys.exit("No serial port found; pass one explicitly: capture_boot.py /dev/... [SECONDS]")
    PORT = ports[0]
DURATION = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0

buf = []
stop = threading.Event()


def reader():
    with serial.Serial(PORT, 115200, timeout=0.5) as s:
        s.reset_input_buffer()
        # DTR/RTS toggle to reset the Pico (like mpremote does).
        time.sleep(0.1)
        s.dtr = False
        s.rts = True
        while not stop.is_set():
            n = s.in_waiting
            if n:
                data = s.read(n)
                buf.append(data)
                sys.stdout.write(data.decode("utf-8", "replace"))
                sys.stdout.flush()


t = threading.Thread(target=reader, daemon=True)
t.start()
time.sleep(DURATION)
stop.set()
t.join(timeout=2)
print("\n=== capture done (%d bytes) ===" % sum(len(b) for b in buf))
