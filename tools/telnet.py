#!/usr/bin/env python3
"""Client for a micropy-system device shell (telnet-style lines on port 23).

One-shot:    tools/telnet.py HOST [PORT] COMMAND [ARGS...]
    tools/telnet.py 10.9.30.76 status
    tools/telnet.py 10.9.30.76 log 40
    tools/telnet.py 10.9.30.76 selftest
    tools/telnet.py 10.9.30.76 reboot
Interactive: tools/telnet.py HOST [PORT]
    prints the banner, then sends each local line as a command; 'repl' (when enabled)
    drops into the device's persistent Python loop; 'exit'/'quit' close.

Stock telnet/nc work too (port 23 is the standard telnet port):
    telnet 10.9.30.76
    nc 10.9.30.76 23

Protocol: the server answers every command with output lines terminated by
'<<<END>>>\n'; a banner with the same marker is sent on connect. Set
MICROPY_SHELL_TOKEN when the server requires authentication.
"""

import os
import socket
import sys

END_MARKER = "<<<END>>>"
DEFAULT_PORT = 23
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 120
# One-shot commands must never hang on a half-booted board (a connect can
# complete against a board whose shell is not up yet, then block on the banner
# read). Cap every one-shot read; interactive mode keeps READ_TIMEOUT.
CMD_TIMEOUT = float(os.environ.get("OTC_CMD_TIMEOUT", "10"))


def _recv_until_end(s):
    """Read from the socket until the END marker; return the payload bytes."""
    buf = b""
    marker = (END_MARKER + "\n").encode()
    while marker not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    idx = buf.find(marker)
    return buf[:idx] if idx >= 0 else buf


def _connect(host, port, read_timeout=READ_TIMEOUT):
    s = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
    s.settimeout(read_timeout)
    return s


def _write_out(payload):
    sys.stdout.write(payload.decode("utf-8", "replace"))
    if payload and not payload.endswith(b"\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()


def _authenticate(s, token):
    if not token:
        return
    s.sendall(("auth " + token + "\n").encode())
    response = _recv_until_end(s).decode("utf-8", "replace").strip()
    if response != "authenticated":
        raise RuntimeError("shell authentication failed")


def _one_shot(host, port, command, token=None):
    s = _connect(host, port, CMD_TIMEOUT)
    try:
        _recv_until_end(s)  # banner; discard
        _authenticate(s, token)
        s.sendall((command + "\n").encode())
        payload = _recv_until_end(s)
    finally:
        s.close()
    _write_out(payload)


def _interactive(host, port, token=None):
    s = _connect(host, port)
    try:
        _write_out(_recv_until_end(s))  # banner
        _authenticate(s, token)
        if token:
            print("authenticated")
        in_repl = False
        while True:
            try:
                line = input("py> " if in_repl else "> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            line = line.strip()
            if not line:
                continue
            if line in ("exit", "quit"):
                break
            if line == "repl":
                in_repl = True
            s.sendall((line + "\n").encode())
            _write_out(_recv_until_end(s))
    finally:
        s.close()


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(2)
    host = args[0]
    port = DEFAULT_PORT
    command = None
    rest = args[1:]
    if rest and rest[0].isdigit():
        port = int(rest[0])
        rest = rest[1:]
    if rest:
        command = " ".join(rest)
    token = os.environ.get("MICROPY_SHELL_TOKEN")
    try:
        if command:
            _one_shot(host, port, command, token=token)
        else:
            _interactive(host, port, token=token)
    except RuntimeError as e:
        sys.exit("error: %s" % e)
    except socket.timeout:
        sys.exit("error: %s:%s timed out (board may be mid-boot / half-up)" % (host, port))
    except OSError as e:
        sys.exit("error: %s:%s unreachable (%s)" % (host, port, e))


if __name__ == "__main__":
    main()
