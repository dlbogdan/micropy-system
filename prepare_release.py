import tarfile
import os
import zlib
import hashlib
import json
from datetime import datetime
import subprocess
import tempfile

SOURCE_DIR = 'src'  # Adjust if your .py files are elsewhere
OUTPUT_IMAGE = 'release/firmware.tar.zlib'
METADATA_FILE = 'release/image-info.json'
DEVICE_TYPE = 'pico'  # Or whatever your target is
HASH_FILENAME = 'integrity.json'  # Name of the hash file to include in the archive

def compile_to_mpy(source_dir, temp_dir):
    """Compile all .py files to .mpy using mpy-cross."""
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
                    print("Error: mpy-cross not found. check your requirements.txt")
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

def compress_zlib(tar_path, output_path):
    with open(tar_path, 'rb') as f_in:
        data = f_in.read()
        compressed = zlib.compress(data)
    with open(output_path, 'wb') as f_out:
        f_out.write(compressed)
    return compressed

def calculate_sha256(data):
    return hashlib.sha256(data).hexdigest()

def get_version():
    try:
        return subprocess.check_output(['git', 'describe', '--tags', '--always']).decode().strip()
    except Exception:
        return "unknown"

def main():
    # Create temporary directory for compiled files
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Compiling Python files to .mpy in temporary directory: {temp_dir}")
        compile_to_mpy(SOURCE_DIR, temp_dir)
        
        temp_tar = 'release/temp_firmware.tar'
        create_tar_archive(SOURCE_DIR, temp_tar, temp_dir)

        compressed_data = compress_zlib(temp_tar, OUTPUT_IMAGE)
        os.remove(temp_tar)

        metadata = {
            "device_type": DEVICE_TYPE,
            "version": get_version(),
            "sha256": calculate_sha256(compressed_data),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        with open(METADATA_FILE, 'w') as f:
            json.dump(metadata, f, indent=2)

if __name__ == "__main__":
    main()
