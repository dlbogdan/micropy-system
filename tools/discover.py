#!/usr/bin/env python3
"""Find a micropy-system device on the LAN by probing its shell port.

Scans the local /24 (derived from the host's egress IPv4, or --subnet)
concurrently and reports any host whose shell (telnet-style line command
server, port 23) answers a `status` command like a micropy-system device.
Use --host to probe a single address directly (works cross-subnet when routed).

Usage:  tools/discover.py [port]  |  --host 10.9.30.76  |  --subnet 10.9.30
"""

import argparse
import concurrent.futures
import socket
import sys


def local_subnet():
    """Return (network_octets, host_octet) for the primary IPv4, e.g. (("10","9","30"), 76)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no packet sent; just picks the egress interface
        ip = s.getsockname()[0]
    except OSError:
        ip = socket.gethostbyname(socket.gethostname())
    finally:
        s.close()
    a, b, c, d = ip.split(".")
    return (a, b, c), int(d)


def _recv_until_end(s, cap=4096):
    buf = b""
    marker = b"<<<END>>>\n"
    while marker not in buf and len(buf) < cap:
        try:
            chunk = s.recv(1024)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
    idx = buf.find(marker)
    return buf[:idx] if idx >= 0 else buf


def probe(port, marker, candidate):
    try:
        s = socket.create_connection((candidate, port), timeout=0.15)
    except OSError:
        return None
    try:
        s.settimeout(0.3)
        banner = _recv_until_end(s)
        s.sendall(b"status\n")
        head = _recv_until_end(s)
    except OSError:
        return None
    finally:
        s.close()
    if marker in (banner + head).decode("utf-8", "replace"):
        return candidate
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Find a micropy-system device on the LAN.")
    parser.add_argument("pos_port", nargs="?", type=int, default=None,
                        help="shell port (positional shortcut for --port)")
    parser.add_argument("--port", type=int, default=23,
                        help="device shell port (default 23)")
    parser.add_argument("--marker", default="service",
                        help="substring that must appear in the status response "
                             "(default: service)")
    parser.add_argument("--subnet", default=None,
                        help="network to scan as a dotted triple, e.g. 10.9.30 "
                             "(default: derived from the host IP)")
    parser.add_argument("--host", default=None,
                        help="probe a single host and exit "
                             "(works cross-subnet when routed)")
    args = parser.parse_args()
    port = args.pos_port if args.pos_port is not None else args.port

    if args.host:
        print("Probing %s on port %s..." % (args.host, port))
        if probe(port, args.marker, args.host):
            print("Found device: %s" % args.host)
            print("shell %s:%s (e.g. tools/telnet.py %s %s status)"
                  % (args.host, port, args.host, port))
            return
        print("No device at %s." % args.host)
        sys.exit(1)

    if args.subnet:
        base = tuple(args.subnet.split("."))
        if len(base) != 3:
            sys.exit("--subnet must be a dotted triple, e.g. 10.9.30")
        me = 0
    else:
        base, me = local_subnet()
    prefix = ".".join(base)
    print("Scanning %s.0/24 on port %s..." % (prefix, port))
    hosts = [prefix + ".%d" % i for i in range(1, 255) if i != me]
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
        for hit in ex.map(lambda h: probe(port, args.marker, h), hosts):
            if hit:
                print("Found device: %s" % hit)
                print("shell %s:%s (e.g. tools/telnet.py %s %s status)"
                      % (hit, port, hit, port))
                return
    print("No device found. Is it powered on and connected to the same network?")
    sys.exit(1)


if __name__ == "__main__":
    main()
