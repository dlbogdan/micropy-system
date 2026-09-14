#!/usr/bin/env python3
"""Serve locally built OTA artifacts over development-only plain HTTP."""

import argparse
from datetime import datetime
import functools
import http.server
import json
import mimetypes
import os
import socket
import socketserver


DEFAULT_PORT = 8000


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


class FirmwareRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Serve one configured build directory with bounded, explicit behavior."""

    def do_GET(self):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] GET {self.path}")
        if self.path == '/list':
            files = []
            for name in sorted(os.listdir(self.directory)):
                path = os.path.join(self.directory, name)
                if os.path.isfile(path):
                    stat = os.stat(path)
                    files.append({
                        'name': name,
                        'size': stat.st_size,
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    })
            payload = json.dumps({'files': files}, indent=2).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        return super().do_GET()

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()


def get_local_ip():
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(('8.8.8.8', 80))
        address = probe.getsockname()[0]
        probe.close()
        return address
    except Exception:
        return '127.0.0.1'


def validate_build_directory(directory):
    if not os.path.isdir(directory):
        raise ValueError(f"build directory does not exist: {directory}")
    names = os.listdir(directory)
    archives = sorted(name for name in names if name.endswith('.tar.zlib'))
    missing = []
    if 'metadata.json' not in names:
        missing.append('metadata.json')
    if not archives:
        missing.append('*.tar.zlib')
    if missing:
        raise ValueError("build directory is missing: " + ', '.join(missing))
    return archives


def run_server(directory, host='', port=DEFAULT_PORT):
    directory = os.path.abspath(directory)
    archives = validate_build_directory(directory)
    mimetypes.add_type('application/zlib', '.zlib')
    mimetypes.add_type('application/json', '.json')
    handler = functools.partial(FirmwareRequestHandler, directory=directory)
    address = get_local_ip() if host in ('', '0.0.0.0') else host
    with ReusableTCPServer((host, port), handler) as server:
        print("Serving: " + ', '.join(archives))
        print(f"OTA URL: http://{address}:{port}/")
        print(f"File list: http://{address}:{port}/list")
        print("WARNING: Plain HTTP is intended only for trusted local development networks.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped")


def main(argv=None):
    parser = argparse.ArgumentParser(description='Serve local OTA builds over HTTP')
    parser.add_argument('--directory', default='build', help='Build output directory')
    parser.add_argument('--host', default='', help='Bind address (default: all interfaces)')
    parser.add_argument('-p', '--port', type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    try:
        run_server(args.directory, args.host, args.port)
    except ValueError as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
