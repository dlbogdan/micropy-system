#!/usr/bin/env python3
"""
Local firmware builder script.
Compiles source files and creates firmware.tar.zlib and metadata.json in the build directory.
"""
import tarfile
import os
import zlib
import hashlib
import json
import shutil
from datetime import datetime, timezone
import subprocess
import tempfile
import socket
import argparse

# Configuration
SOURCE_DIR = 'src'  # Source directory containing Python files
BUILD_DIR = 'build'  # Output directory for built firmware
OUTPUT_IMAGE = os.path.join(BUILD_DIR, 'firmware.tar.zlib')
METADATA_FILE = os.path.join(BUILD_DIR, 'metadata.json')
HASH_FILENAME = 'integrity.json'  # Name of the hash file included in the archive
DEVICE_TYPE = 'pico'  # Target device type

# Default values
DEFAULT_VERSION = '1.0.0'
DEFAULT_REPO = 'dlbogdan/test-actions-buildfw'
DEFAULT_PORT = 8000

def ensure_directory(directory):
    """Create directory if it doesn't exist."""
    if not os.path.exists(directory):
        os.makedirs(directory)
        print(f"Created directory: {directory}")

def compile_to_mpy(source_dir, temp_dir):
    """Compile all .py files to .mpy using mpy-cross."""
    print(f"Compiling Python files to .mpy in temporary directory: {temp_dir}")
    
    # Compile files in src directory
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".py") and (not file == "main.py" and not file == "boot.py"):
                py_path = os.path.join(root, file)
                # Create relative path structure in temp directory
                rel_path = os.path.relpath(root, source_dir)
                temp_subdir = os.path.join(temp_dir, rel_path)
                os.makedirs(temp_subdir, exist_ok=True)
                
                # Compile to .mpy
                mpy_path = os.path.join(temp_subdir, file[:-3] + '.mpy')
                try:
                    subprocess.run(['mpy-cross', py_path, '-o', mpy_path], check=True)
                    print(f"Compiled {py_path} to {mpy_path}")
                except subprocess.CalledProcessError as e:
                    print(f"Error compiling {py_path}: {e}")
                    raise
                except FileNotFoundError:
                    print("Error: mpy-cross not found. Make sure it's installed and in your PATH.")
                    raise

def calculate_file_sha256(file_path):
    """Calculate SHA256 hash for a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def create_hash_file(source_dir, temp_dir, hash_file_path):
    """Create a hash file with SHA256 sums of all files to be included in the archive."""
    hash_data = {}
    
    # Add hashes for boot.py and main.py if they exist
    for root_file in ['boot.py', 'main.py']:
        root_file_path = os.path.join(source_dir, root_file)
        if os.path.exists(root_file_path):
            file_hash = calculate_file_sha256(root_file_path)
            hash_data[root_file] = file_hash
            print(f"Added hash for {root_file}: {file_hash}")
    
    # Add hashes for all compiled .mpy files
    for root, _, files in os.walk(temp_dir):
        for file in files:
            if file.endswith(".mpy"):
                full_path = os.path.join(root, file)
                arcname = os.path.relpath(full_path, start=temp_dir)
                # Convert Windows backslashes to forward slashes for web compatibility
                arcname = arcname.replace('\\', '/')
                file_hash = calculate_file_sha256(full_path)
                hash_data[arcname] = file_hash
                print(f"Added hash for {arcname}: {file_hash}")
    
    # Write the hash data as JSON
    with open(hash_file_path, 'w') as hash_file:
        json.dump(hash_data, hash_file, indent=2)
    
    print(f"Created JSON hash file at {hash_file_path}")
    return hash_file_path

def create_tar_archive(source_dir, tar_path, temp_dir):
    """Create tar archive from compiled .mpy files and root py files."""
    print(f"Creating TAR archive: {tar_path}")
    
    # First create the hash file in the temp directory
    hash_file_path = os.path.join(temp_dir, HASH_FILENAME)
    create_hash_file(source_dir, temp_dir, hash_file_path)
    
    with tarfile.open(tar_path, "w") as tar:
        # Add the hash file as the first entry
        tar.add(hash_file_path, arcname=HASH_FILENAME)
        print(f"Added {HASH_FILENAME} to archive as the first file")
        
        # Then add boot.py and main.py from root if they exist
        for root_file in ['boot.py', 'main.py']:
            if os.path.exists(os.path.join(source_dir, root_file)):
                tar.add(os.path.join(source_dir, root_file), arcname=root_file)
                print(f"Added {root_file} to archive as {root_file} at root level")
        
        # Then add all compiled .mpy files
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith(".mpy"):
                    full_path = os.path.join(root, file)
                    # Convert path to be relative to source_dir
                    arcname = os.path.relpath(full_path, start=temp_dir)
                    tar.add(full_path, arcname=arcname)
                    print(f"Added {arcname} to archive")

def compress_zlib(tar_path, output_path):
    """Compress the tar file using zlib."""
    print(f"Compressing TAR to ZLIB: {output_path}")
    with open(tar_path, 'rb') as f_in:
        data = f_in.read()
        compressed = zlib.compress(data)
    with open(output_path, 'wb') as f_out:
        f_out.write(compressed)
    return compressed

def calculate_sha256(data):
    """Calculate SHA256 hash of binary data."""
    return hashlib.sha256(data).hexdigest()

def get_version(version_arg=None):
    """Get version from version.txt, git, or use provided/default version."""
    # If version explicitly provided as argument
    if version_arg:
        return version_arg
    
    # Try to read from version.txt in src directory
    version_file = os.path.join(SOURCE_DIR, 'version.txt')
    try:
        with open(version_file, 'r') as f:
            version = f.read().strip()
            print(f"Using version {version} from {version_file}")
            # Ensure version has 'v' prefix
            if version and not version.startswith('v'):
                version = f"v{version}"
            return version
    except (FileNotFoundError, IOError):
        print(f"No {version_file} file found, checking git...")
    
    # Try to get version from git
    try:
        version = subprocess.check_output(
            ['git', 'describe', '--tags', '--always'], 
            stderr=subprocess.DEVNULL
        ).decode().strip()
        print(f"Using version {version} from git")
        # Ensure version has 'v' prefix
        if version and not version.startswith('v'):
            version = f"v{version}"
        return version
    except Exception:
        print(f"Warning: Could not get version from git, using default: {DEFAULT_VERSION}")
        return f"v{DEFAULT_VERSION}"

def create_metadata(compressed_data, version, repo_name, server_port):
    """Create GitHub-like metadata JSON file."""
    sha256 = calculate_sha256(compressed_data)
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    local_ip = get_local_ip()
    
    # Fixed server port to match the HTTPS server (8443)
    https_port = 8443
    
    # Format version properly (ensure it has v prefix)
    if version and not version.startswith('v'):
        version = f"v{version}"
    
    metadata_github_format = {
        "url": f"https://{local_ip}:{https_port}/metadata.json",
        "assets_url": f"https://{local_ip}:{https_port}/",
        "upload_url": f"https://{local_ip}:{https_port}/",
        "html_url": f"https://{local_ip}:{https_port}/",
        "id": int(datetime.now().timestamp()),
        "author": {
            "login": "local-builder",
            "id": 1,
            "name": "Local Builder"
        },
        "node_id": "LOCAL_NODE",
        "tag_name": version,
        "target_commitish": "local",
        "name": f"Firmware {version}",
        "draft": False,
        "prerelease": False,
        "created_at": timestamp,
        "published_at": timestamp,
        "assets": [
            {
                "url": f"https://{local_ip}:{https_port}/firmware.tar.zlib",
                "id": 1,
                "node_id": "LOCAL_ASSET",
                "name": "firmware.tar.zlib",
                "label": "",
                "content_type": "application/octet-stream",
                "state": "uploaded",
                "size": len(compressed_data),
                "download_count": 0,
                "created_at": timestamp,
                "updated_at": timestamp,
                "browser_download_url": f"https://{local_ip}:{https_port}/firmware.tar.zlib"
            }
        ],
        "tarball_url": f"https://{local_ip}:{https_port}/",
        "zipball_url": f"https://{local_ip}:{https_port}/",
        "body": f"Locally built firmware release {version}.\nIncludes the compressed image and metadata."
    }
    
    # Create the image-info.json file (the one referenced in prepare_release.py)
    image_info = {
        "device_type": DEVICE_TYPE,
        "version": version,
        "sha256": sha256,
        "timestamp": timestamp
    }
    
    # Save the image info separately (for reference, not used by the server)
    image_info_path = os.path.join(BUILD_DIR, 'image-info.json')
    with open(image_info_path, 'w') as f:
        json.dump(image_info, f, indent=2)
    print(f"Created image metadata file: {image_info_path}")
    
    return metadata_github_format

def get_local_ip():
    """Get the local IP address of the machine."""
    try:
        # Create a socket to determine the outgoing IP address
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # Connect to Google DNS
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"  # Fallback to localhost

def main():
    print("Starting local firmware builder")
    parser = argparse.ArgumentParser(description="Build firmware locally and prepare server files")
    parser.add_argument('--version', type=str, help='Version to use for the firmware (default: auto from git)')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help=f'Port for the server URLs (default: {DEFAULT_PORT})')
    parser.add_argument('--repo', type=str, default=DEFAULT_REPO, help=f'Repository name (default: {DEFAULT_REPO})')
    
    args = parser.parse_args()
    version = get_version(args.version)
    
    print(f"=== Building firmware version {version} ===")
    
    # Ensure build directory exists
    ensure_directory(BUILD_DIR)
    
    # Create temporary directory for compiled files
    with tempfile.TemporaryDirectory() as temp_dir:
        # Step 1: Compile Python files to .mpy
        compile_to_mpy(SOURCE_DIR, temp_dir)
        
        # Step 2: Create temporary tar archive
        temp_tar = os.path.join(BUILD_DIR, 'temp_firmware.tar')
        create_tar_archive(SOURCE_DIR, temp_tar, temp_dir)
        
        # Step 3: Compress the tar file
        compressed_data = compress_zlib(temp_tar, OUTPUT_IMAGE)
        
        # Step 4: Create GitHub-like metadata.json
        metadata = create_metadata(compressed_data, version, args.repo, args.port)
        
        # Step 5: Write metadata.json file
        with open(METADATA_FILE, 'w') as f:
            json.dump(metadata, f, indent=2)
        print(f"Created metadata file: {METADATA_FILE}")
        
        # Clean up temporary tar file
        os.remove(temp_tar)
        print(f"Cleaned up temporary file: {temp_tar}")
        
        print(f"\n=== Build complete ===")
        print(f"Firmware: {OUTPUT_IMAGE}")
        print(f"Metadata: {METADATA_FILE}")
        print(f"Version: {version}")
        print(f"Local IP: {get_local_ip()}")
        print(f"Size: {len(compressed_data)} bytes")

if __name__ == "__main__":
    main()