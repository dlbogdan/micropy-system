#!/usr/bin/env python3
"""Client for a micropy-system device shell (telnet-style lines on port 23).

One-shot:    tools/target/telnet.py HOST [PORT] COMMAND [ARGS...]
    tools/target/telnet.py 10.9.30.76 status
    tools/target/telnet.py 10.9.30.76 log 40
    tools/target/telnet.py 10.9.30.76 selftest
    tools/target/telnet.py 10.9.30.76 reboot
Interactive: tools/target/telnet.py HOST [PORT]
    prints the banner, then sends each local line as a command; 'repl' (when enabled)
    drops into the device's persistent Python loop; 'exit'/'quit' close.

Stock telnet/nc work too (port 23 is the standard telnet port):
    telnet 10.9.30.76
    nc 10.9.30.76 23

Protocol: the server answers every command with output lines terminated by
'<<<END>>>\n'; a banner with the same marker is sent on connect. Set
MICROPY_SHELL_TOKEN when the server requires authentication.

Progress and timeouts: command output is streamed as it arrives (long
device-side commands show their work), silence past 15 s prints a
'still waiting' heartbeat to stderr, and timeouts are activity-based: the
banner/first chunk is capped by OTC_CMD_TIMEOUT (default 10 s, the
half-boot guard), afterwards by OTC_CMD_IDLE_TIMEOUT (default 300 s --
single autotests legitimately run for minutes). Interactive idle cap:
OTC_READ_TIMEOUT (default 300 s).
"""

import os
import socket
import sys

END_MARKER = "<<<END>>>"
DEFAULT_PORT = 23
CONNECT_TIMEOUT = 5
# Interactive idle cap (a long device-side command, e.g. the 'test' battery,
# can stay silent for minutes between streamed lines).
READ_TIMEOUT = float(os.environ.get("OTC_READ_TIMEOUT", "300"))
# Half-boot guard: a connect can complete against a board whose shell is not
# up yet, so the BANNER and the FIRST reply chunk are capped tightly.
CMD_TIMEOUT = float(os.environ.get("OTC_CMD_TIMEOUT", "10"))
# Once a command has produced ANY output the board is demonstrably alive and
# working; long-running commands (the 'test' battery: single tests run for
# minutes) may then stay silent for a long time. Wait this long between
# chunks before giving up -- and say so while waiting (see _recv_until_end).
CMD_IDLE_TIMEOUT = float(os.environ.get("OTC_CMD_IDLE_TIMEOUT", "300"))
HEARTBEAT_S = 15.0
POLL_S = 1.0


def _recv_until_end(s, stream=False, first_timeout=CMD_TIMEOUT,
                    idle_timeout=CMD_IDLE_TIMEOUT, desc="a reply"):
    """Read from the socket until the END marker; return the payload bytes.

    Progress instead of a hang: with stream=True every chunk is echoed to
    stdout the moment it arrives (long commands show their work), and any
    silence past HEARTBEAT_S prints a 'still waiting' line to stderr so a
    long device-side operation never looks dead.

    Timeout instead of confusion: the FIRST chunk is capped by
    first_timeout (the half-boot guard, unchanged); afterwards the cap is
    idle_timeout between chunks, and the timeout error names the command
    and the knob instead of guessing 'mid-boot'.
    """
    buf = b""
    printed = 0
    marker = (END_MARKER + "\n").encode()
    got_any = False
    while marker not in buf:
        cap = first_timeout if not got_any else idle_timeout
        s.settimeout(min(cap, POLL_S))
        silence = 0.0
        next_beat = HEARTBEAT_S
        while True:
            try:
                chunk = s.recv(4096)
                break
            except socket.timeout:
                silence += min(cap, POLL_S)
                if silence >= next_beat:
                    sys.stderr.write("    ... still waiting (%ds since %s)\n"
                                     % (int(silence),
                                        "start" if not got_any
                                        else "last output"))
                    sys.stderr.flush()
                    next_beat += HEARTBEAT_S
                if silence >= cap:
                    if not got_any:
                        raise RuntimeError(
                            "timed out after %gs waiting for %s (board may "
                            "be mid-boot / half-up)" % (cap, desc))
                    raise RuntimeError(
                        "no more output for %gs while awaiting the end of "
                        "%s -- the board is working, not hung (raise "
                        "OTC_CMD_IDLE_TIMEOUT, or use tools/target/"
                        "autotest.py for the test battery)" % (cap, desc))
        if not chunk:
            break
        got_any = True
        buf += chunk
        if stream:
            # Echo only payload bytes: the END marker never reaches stdout
            # (callers parse it), and a marker split across chunks is held
            # back until it completes or proves to be payload.
            out = buf[printed:]
            cut = out.find(marker)
            if cut >= 0:
                out = out[:cut]
            elif len(out) >= len(marker):
                out = out[:-(len(marker) - 1)]
            else:
                out = b""
            if out:
                sys.stdout.write(out.decode("utf-8", "replace"))
                sys.stdout.flush()
                printed += len(out)
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
        _recv_until_end(s, desc="the shell banner")  # banner; discard
        _authenticate(s, token)
        s.sendall((command + "\n").encode())
        payload = _recv_until_end(s, stream=True,
                                  desc="the reply to '%s'" % command)
    finally:
        s.close()
    if payload and not payload.endswith(b"\n"):
        sys.stdout.write("\n")
        sys.stdout.flush()


def _interactive(host, port, token=None):
    s = _connect(host, port)
    try:
        _write_out(_recv_until_end(s, first_timeout=READ_TIMEOUT,
                                   idle_timeout=READ_TIMEOUT,
                                   desc="the shell banner"))  # banner
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
            # Stream the reply as it arrives: long device-side commands
            # (the 'test' battery) show progress instead of looking hung.
            payload = _recv_until_end(s, stream=True,
                                      first_timeout=READ_TIMEOUT,
                                      idle_timeout=READ_TIMEOUT,
                                      desc="the reply to '%s'" % line)
            if payload and not payload.endswith(b"\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
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
