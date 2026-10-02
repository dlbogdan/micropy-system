#!/usr/bin/env python3
"""Find a micropy-system device on the LAN by probing its HTTP API port.

Scans the local /24 (derived from the host's egress IPv4, or --subnet)
concurrently and reports any host whose /status endpoint looks like a
micropy-system device. Use --host to probe a single address directly (works
cross-subnet when routed).

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


def probe(port, marker, candidate):
    try:
        with socket.create_connection((candidate, port), timeout=0.15) as s:
            s.sendall(b"GET /status HTTP/1.0\r\nHost: x\r\n\r\n")
            head = s.recv(2048).decode("utf-8", "replace")
        if marker in head:
            return candidate
    except OSError:
        pass
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Find a micropy-system device on the LAN.")
    parser.add_argument("pos_port", nargs="?", type=int, default=None,
                        help="HTTP port (positional shortcut for --port)")
    parser.add_argument("--port", type=int, default=8080,
                        help="device HTTP port (default 8080)")
    parser.add_argument("--marker", default="service",
                        help="substring that must appear in the /status response "
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
            print("http://%s:%s/status" % (args.host, port))
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
                print("http://%s:%s/status" % (hit, port))
                return
    print("No device found. Is it powered on and connected to the same network?")
    sys.exit(1)


if __name__ == "__main__":
    main()
