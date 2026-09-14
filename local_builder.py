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

# Configuration defaults. Applications can override these through the CLI.
SOURCE_DIR = 'src'
BUILD_DIR = 'build'
HASH_FILENAME = 'integrity.json'  # Name of the hash file included in the archive
FRAMEWORK_BUILD_FILENAME = 'framework-build.txt'
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

def prepare_modules(source_dir, temp_dir, module_format='mpy'):
    """Prepare non-launcher modules in exactly one selected representation."""
    print(f"Preparing {module_format} modules in temporary directory: {temp_dir}")
    
    # Compile files in src directory
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".py") and file not in ("main.py", "boot.py"):
                py_path = os.path.join(root, file)
                # Create relative path structure in temp directory
                rel_path = os.path.relpath(root, source_dir)
                temp_subdir = os.path.join(temp_dir, rel_path)
                os.makedirs(temp_subdir, exist_ok=True)
                
                if module_format == 'py':
                    destination = os.path.join(temp_subdir, file)
                    shutil.copy2(py_path, destination)
                    print(f"Copied {py_path} to {destination}")
                else:
                    destination = os.path.join(temp_subdir, file[:-3] + '.mpy')
                    try:
                        subprocess.run(['mpy-cross', py_path, '-o', destination], check=True)
                        print(f"Compiled {py_path} to {destination}")
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
    
    # Add hashes for generated build metadata and all compiled .mpy files.
    for root, _, files in os.walk(temp_dir):
        for file in files:
            if file.endswith((".mpy", ".py")) or file == FRAMEWORK_BUILD_FILENAME:
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

def validate_module_uniqueness(temp_dir):
    """Reject ambiguous module precedence in the prepared artifact tree."""
    modules = {}
    for root, _, files in os.walk(temp_dir):
        for filename in files:
            if not filename.endswith((".py", ".mpy")):
                continue
            path = os.path.relpath(os.path.join(root, filename), temp_dir)
            stem = os.path.splitext(path)[0]
            previous = modules.get(stem)
            if previous:
                raise ValueError(f"module is packaged as both {previous} and {path}")
            modules[stem] = path

def create_tar_archive(source_dir, tar_path, temp_dir):
    """Create tar archive from compiled .mpy files and root py files."""
    print(f"Creating TAR archive: {tar_path}")
    
    validate_module_uniqueness(temp_dir)
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

        framework_build_file = os.path.join(temp_dir, FRAMEWORK_BUILD_FILENAME)
        if os.path.exists(framework_build_file):
            tar.add(framework_build_file, arcname=FRAMEWORK_BUILD_FILENAME)
            print(f"Added {FRAMEWORK_BUILD_FILENAME} to archive")
        
        # Then add all compiled .mpy files
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith((".mpy", ".py")):
                    full_path = os.path.join(root, file)
                    # Convert path to be relative to source_dir
                    arcname = os.path.relpath(full_path, start=temp_dir)
                    tar.add(full_path, arcname=arcname)
                    print(f"Added {arcname} to archive")

def compress_zlib(tar_path, output_path, chunk_size=64 * 1024):
    """Stream TAR compression without retaining TAR or image in memory."""
    print(f"Compressing TAR to ZLIB: {output_path}")
    compressor = zlib.compressobj()
    with open(tar_path, 'rb') as source, open(output_path, 'wb') as output:
        while True:
            chunk = source.read(chunk_size)
            if not chunk:
                break
            output.write(compressor.compress(chunk))
        output.write(compressor.flush())
    return os.path.getsize(output_path)

def calculate_sha256(data):
    """Calculate SHA256 hash of binary data."""
    return hashlib.sha256(data).hexdigest()

def get_version(version_arg=None, source_dir=SOURCE_DIR):
    """Get version from version.txt, git, or use provided/default version."""
    # If version explicitly provided as argument
    if version_arg:
        return version_arg
    
    # Try to read from version.txt in src directory
    version_file = os.path.join(source_dir, 'version.txt')
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

def get_framework_build():
    """Return the framework repository's exact Git tag/commit identity."""
    try:
        return subprocess.check_output(
            ['git', 'describe', '--tags', '--always', '--dirty'],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"

def get_build_date():
    """Return the packaging date in an unambiguous UTC format."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def write_framework_build(temp_dir, build_string=None, build_date=None):
    """Create framework Git and build-date metadata for the release artifact."""
    build_string = build_string or get_framework_build()
    build_date = build_date or get_build_date()
    build_path = os.path.join(temp_dir, FRAMEWORK_BUILD_FILENAME)
    with open(build_path, 'w') as build_file:
        build_file.write(build_string + ' built ' + build_date + '\n')
    return build_path

def create_metadata(compressed_path, version, repo_name, server_port,
                    device_model, firmware_filename, build_dir,
                    output_mode='direct-server'):
    """Create GitHub-like metadata JSON file."""
    sha256 = calculate_file_sha256(compressed_path)
    compressed_size = os.path.getsize(compressed_path)
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    local_ip = get_local_ip()
    
    # Format version properly (ensure it has v prefix)
    if version and not version.startswith('v'):
        version = f"v{version}"
    
    metadata_github_format = {
        "url": f"http://{local_ip}:{server_port}/metadata.json",
        "assets_url": f"http://{local_ip}:{server_port}/",
        "upload_url": f"http://{local_ip}:{server_port}/",
        "html_url": f"http://{local_ip}:{server_port}/",
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
                "url": f"http://{local_ip}:{server_port}/{firmware_filename}",
                "id": 1,
                "node_id": "LOCAL_ASSET",
                "name": firmware_filename,
                "label": "",
                "content_type": "application/octet-stream",
                "state": "uploaded",
                "size": compressed_size,
                "sha256": sha256,
                "model": device_model,
                "runtime_version": "1.29.0",
                "mpy_version": 6,
                "download_count": 0,
                "created_at": timestamp,
                "updated_at": timestamp,
                "browser_download_url": f"http://{local_ip}:{server_port}/{firmware_filename}"
            }
        ],
        "tarball_url": f"http://{local_ip}:{server_port}/",
        "zipball_url": f"http://{local_ip}:{server_port}/",
        "body": f"Locally built firmware release {version}.\nIncludes the compressed image and metadata."
    }
    
    # Create the image-info.json file (the one referenced in prepare_release.py)
    image_info = {
        "device_type": DEVICE_TYPE,
        "version": version,
        "sha256": sha256,
        "timestamp": timestamp
    }
    
    image_info["model"] = device_model
    image_info["size"] = compressed_size
    image_info["runtime_version"] = "1.29.0"
    image_info["mpy_version"] = 6
    image_info["asset"] = firmware_filename

    # This compact manifest is suitable as a GitHub release sidecar and is
    # also useful for inspecting direct-server builds.
    image_info_path = os.path.join(build_dir, 'image-info.json')
    with open(image_info_path, 'w') as f:
        json.dump(image_info, f, indent=2)
    print(f"Created image metadata file: {image_info_path}")
    
    if output_mode == 'direct-server':
        return metadata_github_format
    return None

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

def main(argv=None):
    print("Starting local firmware builder")
    parser = argparse.ArgumentParser(description="Build firmware locally and prepare server files")
    parser.add_argument('--source-dir', default=SOURCE_DIR, help=f'Assembled device filesystem to package (default: {SOURCE_DIR})')
    parser.add_argument('--output-dir', default=BUILD_DIR, help=f'Directory for firmware and metadata outputs (default: {BUILD_DIR})')
    parser.add_argument('--version', type=str, help='Version to use for the firmware (default: auto from git)')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help=f'Port for the server URLs (default: {DEFAULT_PORT})')
    parser.add_argument('--repo', type=str, default=DEFAULT_REPO, help=f'Repository name (default: {DEFAULT_REPO})')
    parser.add_argument('--model', required=True, choices=['pico-w-rp2040', 'pico2-w-rp2350'], help='Target board model')
    parser.add_argument(
        '--output-mode',
        choices=['direct-server', 'github-assets'],
        default='direct-server',
        help='Write direct-server metadata or GitHub-uploadable asset files',
    )
    parser.add_argument(
        '--module-format', choices=['mpy', 'py'], default='mpy',
        help='Package compiled .mpy modules or debuggable .py sources',
    )
    
    args = parser.parse_args(argv)
    source_dir = os.path.abspath(args.source_dir)
    output_dir = os.path.abspath(args.output_dir)
    if not os.path.isdir(source_dir):
        parser.error(f"source directory does not exist: {source_dir}")
    accidental_paths = [
        name for name in ('vendor', 'tools', 'device', 'build', '.git')
        if os.path.exists(os.path.join(source_dir, name))
    ]
    if accidental_paths:
        parser.error(
            "source directory looks like a host project root; unexpected paths: "
            + ", ".join(accidental_paths)
        )

    version = get_version(args.version, source_dir)
    firmware_filename = f"{args.model}-firmware.tar.zlib"
    output_image = os.path.join(output_dir, firmware_filename)
    metadata_file = os.path.join(output_dir, 'metadata.json')
    
    print(f"=== Building firmware version {version} ===")
    
    # Ensure build directory exists
    ensure_directory(output_dir)
    
    # Create temporary directory for compiled files
    with tempfile.TemporaryDirectory() as temp_dir:
        framework_build = get_framework_build()
        framework_build_date = get_build_date()
        write_framework_build(temp_dir, framework_build, framework_build_date)
        # Step 1: Prepare modules in the selected, non-ambiguous format.
        prepare_modules(source_dir, temp_dir, args.module_format)
        
        # Step 2: Create temporary tar archive
        temp_tar = os.path.join(output_dir, 'temp_firmware.tar')
        create_tar_archive(source_dir, temp_tar, temp_dir)
        
        # Step 3: Compress the tar file
        compressed_size = compress_zlib(temp_tar, output_image)
        
        # Step 4: Create GitHub-like metadata.json
        metadata = create_metadata(
            output_image, version, args.repo, args.port, args.model,
            firmware_filename, output_dir, args.output_mode)
        
        # Direct-server transport consumes GitHub-shaped metadata.json.
        # GitHub transport receives equivalent release metadata from its API;
        # image-info.json remains available as an uploadable build sidecar.
        if metadata is not None:
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            print(f"Created direct-server metadata: {metadata_file}")
        
        # Clean up temporary tar file
        os.remove(temp_tar)
        print(f"Cleaned up temporary file: {temp_tar}")
        
        print(f"\n=== Build complete ===")
        print(f"Firmware: {output_image}")
        if metadata is not None:
            print(f"Direct-server metadata: {metadata_file}")
        print(f"Release sidecar: {os.path.join(output_dir, 'image-info.json')}")
        print(f"Version: {version}")
        print(f"Framework build: {framework_build} built {framework_build_date}")
        print(f"Local IP: {get_local_ip()}")
        print(f"Size: {compressed_size} bytes")

if __name__ == "__main__":
    main()
