#!/usr/bin/env python3
"""
Simple HTTPS server to serve firmware files and metadata.
Place your firmware.tar.zlib and metadata.json in the 'build' directory.
"""
import http.server
import socketserver
import os
import json
import ssl
from datetime import datetime
import argparse
import mimetypes
import subprocess
import sys

# Define default port
DEFAULT_PORT = 8443  # Standard HTTPS port is 443, but using 8443 for non-root users
BUILD_DIR = "build"
CERT_DIR = "certs"
CERT_FILE = os.path.join(CERT_DIR, "server.crt")
KEY_FILE = os.path.join(CERT_DIR, "server.key")

class FirmwareRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom request handler to serve files from build directory"""
    
    def __init__(self, *args, **kwargs):
        # Set the directory to serve files from
        super().__init__(*args, directory=BUILD_DIR, **kwargs)
    
    def do_GET(self):
        """Handle GET requests"""
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] GET {self.path}")
        
        # Special handling for /list endpoint
        if self.path == '/list':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            file_list = []
            for file in os.listdir(BUILD_DIR):
                file_path = os.path.join(BUILD_DIR, file)
                if os.path.isfile(file_path):
                    file_stats = os.stat(file_path)
                    file_info = {
                        'name': file,
                        'size': file_stats.st_size,
                        'modified': datetime.fromtimestamp(file_stats.st_mtime).isoformat()
                    }
                    file_list.append(file_info)
            
            self.wfile.write(json.dumps({'files': file_list}, indent=2).encode())
            return
            
        # For all other requests, use the built-in method to serve files
        return super().do_GET()
    
    def end_headers(self):
        # Add CORS headers to allow access from anywhere
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()

def create_self_signed_cert():
    """Create a self-signed certificate for HTTPS."""
    os.makedirs(CERT_DIR, exist_ok=True)
    
    # Check if certificates already exist
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        print(f"Using existing certificates in {CERT_DIR}/")
        return True
    
    print("Generating self-signed certificates...")
    
    # Use OpenSSL to create a self-signed certificate
    try:
        # Create private key
        subprocess.run([
            'openssl', 'genrsa',
            '-out', KEY_FILE,
            '2048'
        ], check=True)
        
        # Create CSR (Certificate Signing Request)
        subprocess.run([
            'openssl', 'req', '-new',
            '-key', KEY_FILE,
            '-out', os.path.join(CERT_DIR, 'server.csr'),
            '-subj', '/CN=localhost'
        ], check=True)
        
        # Create self-signed certificate
        subprocess.run([
            'openssl', 'x509', '-req',
            '-days', '365',
            '-in', os.path.join(CERT_DIR, 'server.csr'),
            '-signkey', KEY_FILE,
            '-out', CERT_FILE
        ], check=True)
        
        print(f"Self-signed certificates created in {CERT_DIR}/")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error creating self-signed certificates: {e}")
        print("Please install OpenSSL and try again, or create certificates manually.")
        return False
    except Exception as e:
        print(f"Unexpected error creating certificates: {e}")
        return False

def run_server(port=DEFAULT_PORT):
    """Run the HTTPS server"""
    # Ensure build directory exists
    os.makedirs(BUILD_DIR, exist_ok=True)
    
    # Define common MIME types
    mimetypes.add_type('application/zlib', '.zlib')
    mimetypes.add_type('application/json', '.json')
    
    # Check for firmware and metadata files
    files_in_build = os.listdir(BUILD_DIR)
    firmware_files = [f for f in files_in_build if f.endswith('.tar.zlib')]
    has_metadata = 'metadata.json' in files_in_build
    
    if not firmware_files:
        print(f"Warning: No firmware files (*.tar.zlib) found in {BUILD_DIR}/")
    else:
        print(f"Found firmware files: {', '.join(firmware_files)}")
    
    if not has_metadata:
        print(f"Warning: metadata.json not found in {BUILD_DIR}/")
        print("You can create a basic metadata.json file with the following content:")
        sample_metadata = {
            "tag_name": "v1.0.0",
            "name": "Sample Firmware Release",
            "body": "Firmware release description",
            "assets": [
                {
                    "name": firmware_files[0] if firmware_files else "firmware.tar.zlib",
                    "browser_download_url": f"https://localhost:{port}/{firmware_files[0] if firmware_files else 'firmware.tar.zlib'}"
                }
            ]
        }
        print(json.dumps(sample_metadata, indent=2))
    
    # Create and configure the server
    handler = FirmwareRequestHandler
    httpd = socketserver.TCPServer(("", port), handler)
    
    # Add SSL certificate
    if not create_self_signed_cert():
        print("Failed to create or verify SSL certificates. HTTPS server cannot start.")
        return
    
    # Use SSLContext instead of the deprecated wrap_socket
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
    httpd.socket = ssl_context.wrap_socket(httpd.socket, server_side=True)
    
    # Get the local IP address
    local_ip = get_local_ip()
    
    print(f"\nServer started at https://{local_ip}:{port}")
    print(f"Access file list at https://{local_ip}:{port}/list")
    print("Press Ctrl+C to stop the server")
    
    if local_ip != "127.0.0.1":
        print("\nIMPORTANT: Since you're using a self-signed certificate, you may need to:")
        print("1. Add an exception for this certificate in your browser")
        print("2. Configure your device to trust this certificate or disable certificate validation")
        print("\nDevice configuration for direct_base_url:")
        print(f"\"direct_base_url\": \"https://{local_ip}:{port}/\"")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped")

def get_local_ip():
    """Get the local IP address of the machine."""
    try:
        # Create a socket to determine the outgoing IP address
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # Connect to Google DNS
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"  # Fallback to localhost

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Secure HTTPS server for firmware files")
    parser.add_argument('-p', '--port', type=int, default=DEFAULT_PORT, 
                        help=f'Port to run the server on (default: {DEFAULT_PORT})')
    args = parser.parse_args()
    
    run_server(args.port) 