import uasyncio as asyncio
import hashlib
import gc
import ujson
import uos
import deflate
import utarfile
import machine
import binascii
import lib.coresys.logger as logger

# logger = logger.Logger()
led_pin = machine.Pin('LED', machine.Pin.OUT)


class FirmwareUpdater:
    """Singleton firmware updater with progress callback support."""
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, device_model=None, github_repo=None, github_token="", chunk_size=2048, max_redirects=10, direct_base_url=None, core_system_files=None, update_on_boot=True, max_failure_attempts=3, progress_callback=None):
        # If already initialized, just update the progress callback if provided
        if self._initialized:
            if progress_callback is not None:
                self.progress_callback = progress_callback
            return
            
        if device_model is None:
            raise ValueError("device_model is required for first initialization")
            
        self.device_model = device_model
        self.current_version = self._read_version()
        self.error = None
        
        # Store injected configuration values
        self.direct_base_url = direct_base_url
        self.github_repo = github_repo
        self.github_token = github_token
        self.chunk_size = chunk_size
        self.max_redirects = max_redirects
        self.core_system_files = core_system_files or []
        self.update_on_boot = update_on_boot
        self.max_failure_attempts = max_failure_attempts
        
        # Progress callback support
        self.progress_callback = progress_callback
        
        # Setup URL modes
        self.is_direct_mode = self.direct_base_url is not None
        
        if self.is_direct_mode:
            if self.direct_base_url and not self.direct_base_url.endswith('/'):
                self.direct_base_url += '/'
            self.metadata_url = f"{self.direct_base_url}metadata.json"
        else:
            if not self.github_repo:
                raise ValueError("Either github_repo or direct_base_url must be provided")
            self.base_url = f"https://api.github.com/repos/{self.github_repo}/releases/latest"
            
        # State variables
        self.total_size = 0
        self.bytes_read = 0
        self.download_done = False
        self.download_started = False
        self.firmware_download_path = '/update.tar.zlib'
        self.pending_update_version = None
        self.backup_dir = "/backup"
        self.hash_sums = {}
        
        # Flag file paths
        self.update_flag_path = '/__updating'
        self.applying_flag_path = '/__applying'
        
        self._initialized = True

    @classmethod
    def get_instance(cls):
        """Get the singleton instance if it exists."""
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset the singleton instance (mainly for testing)."""
        cls._instance = None
        cls._initialized = False

    def set_progress_callback(self, callback):
        """Set or update the progress callback function."""
        self.progress_callback = callback

    def _notify_progress(self, stage, progress_percent=0, message="", error=None):
        """Notify progress callback if set."""
        if self.progress_callback:
            try:
                self.progress_callback(
                    stage=stage,
                    progress_percent=progress_percent,
                    message=message,
                    error=error
                )
            except Exception as e:
                logger.warning(f"Progress callback error: {e}", log_to_file=True)

    @staticmethod
    def _read_version():
        """Read the current version from a version file."""
        try:
            with open('/version.txt', 'r') as f:
                return f.read().strip()
        except OSError:
            logger.warning(f"Version file not found, defaulting to 0.0.0", log_to_file=True)
            return "0.0.0"

    @staticmethod
    def _parse_semver(version):
        """Parse SemVer string into tuple for comparison."""
        try:
            major, minor, patch = map(int, version.split("."))
            return major, minor, patch
        except ValueError:
            raise ValueError(f"Invalid version format: {version}")

    @staticmethod
    def _parse_url(url):
        """Parse URL into host, port, and path components."""
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ValueError(f"Invalid or non-HTTPS URL: {url}")
        
        url_no_proto = url[8:]
        host_end_index = url_no_proto.find('/')
        
        if host_end_index == -1:
            host_part = url_no_proto
            path = "/"
        else:
            host_part = url_no_proto[:host_end_index]
            path = url_no_proto[host_end_index:]

        port = 443
        if ':' in host_part:
            host, port_str = host_part.split(':', 1)
            port = int(port_str)  # Let ValueError bubble up if invalid
        else:
            host = host_part

        if not host:
            raise ValueError(f"Could not extract host from URL: {url}")
            
        return host, port, path
            
    async def _make_http_request(self, host, port, path,timeout=2):
        """Make an HTTPS request and return the connection and response status."""
        logger.info(f'Connecting to {host}:{port} for path {path[:50]}...', log_to_file=True)
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port, ssl=True), timeout)
        headers = f'GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: MicroPython-Firmware-Updater/1.0\r\nConnection: close\r\n'
        if self.github_token:
            headers += f'Authorization: token {self.github_token}\r\n'
        headers += '\r\n'
        
        writer.write(headers.encode())
        await writer.drain()

        status_line = await reader.readline()
        return reader, writer, status_line
        
    @staticmethod
    async def _handle_redirect(reader, writer):
        """Handle HTTP redirect and return the new location."""
        location = None
        while True:
            header_line = await reader.readline()
            if header_line == b'\r\n': 
                break
            if header_line.startswith(b'Location:'):
                location = header_line.split(b': ')[1].decode().strip()
        
        writer.close()
        await writer.wait_closed()
        return location
        
    @staticmethod
    async def _process_response_headers(reader):
        """Process HTTP response headers and return content length."""
        content_length = 0
        while True:
            header_line = await reader.readline()
            if header_line == b'\r\n': 
                break
            if header_line.startswith(b'Content-Length:'):
                content_length = int(header_line.split(b':')[1].strip())
        
        return content_length
        
    async def _download_content(self, reader, store_in_memory, target_path, content_length):
        """Download content from the HTTP response."""
        hash_obj = hashlib.sha256()
        mem_buffer = bytearray() if store_in_memory else None
        file_handle = None
        
        if not store_in_memory:
            if not target_path or not isinstance(target_path, str):
                raise ValueError("Invalid target_path for file download")
            file_handle = open(target_path, 'wb')
        
        self.total_size = content_length
        self.bytes_read = 0
        
        remaining = content_length
        last_progress_percent = 0
        while remaining > 0:
            chunk = await reader.read(min(self.chunk_size, remaining))
            if not chunk: 
                break
            hash_obj.update(chunk)
            if store_in_memory and mem_buffer is not None:
                mem_buffer.extend(chunk)
            elif file_handle:
                file_handle.write(chunk)
            self.bytes_read += len(chunk)
            led_pin.toggle()
            remaining -= len(chunk)
            
            # Notify progress callback for download progress
            current_progress = self.percent_complete()
            if current_progress != last_progress_percent and current_progress % 5 == 0:  # Update every 5%
                self._notify_progress(
                    stage="downloading",
                    progress_percent=current_progress,
                    message=f"Downloaded {self.bytes_read}/{self.total_size} bytes"
                )
                last_progress_percent = current_progress
            
            gc.collect()
            await asyncio.sleep_ms(10)
        led_pin.off()
        if file_handle:
                file_handle.close()

        def hexdigest(data):
            # try:
            #     return data.hexdigest() # there might be a micropython version when this will become available
            # except Exception:
            return binascii.hexlify(data.digest()) # probably more efficient
                
        computed_hash = hexdigest(hash_obj) if content_length > 0 else "NO_CONTENT_HASH"
        
        if store_in_memory and mem_buffer is not None:
            content_str = mem_buffer.decode('utf-8')
            return content_str, computed_hash
        else:
            return None, computed_hash
            
    async def _download_file(self, url, target_path, store_in_memory=False)->tuple[str|None, str|bytes|None]:
        """Core download logic, assuming HTTPS. Optionally stores in memory."""
        self.total_size = 0
        self.bytes_read = 0
        self.download_done = False
        self.error = None
        self.download_started = False
        redirects = self.max_redirects
        current_url = url
        
        writer = None
        try:
            while redirects > 0:
                host, port, path = self._parse_url(current_url)
                reader, writer, status_line = await self._make_http_request(host, port, path)
                
                if status_line.startswith(b'HTTP/1.1 301') or status_line.startswith(b'HTTP/1.1 302'):
                    location = await self._handle_redirect(reader, writer)
                    current_url = location
                    redirects -= 1
                    if redirects == 0:
                        raise ValueError("Maximum redirects reached")
                    continue
                    
                if not (status_line.startswith(b'HTTP/1.1 200') or status_line.startswith(b'HTTP/1.0 200')):
                    writer.close()
                    await writer.wait_closed()
                    raise ValueError(f'Unexpected response: {status_line.decode().strip()}')

                content_length = await self._process_response_headers(reader)
                
                if content_length == 0 and not store_in_memory:
                    writer.close()
                    await writer.wait_closed()
                    raise ValueError('Empty content length for firmware file')

                self.download_started = True
                gc.collect()
                
                content_str, computed_hash = await self._download_content(
                    reader, store_in_memory, target_path, content_length)
                
                writer.close()
                await writer.wait_closed()
                led_pin.off()
                self.download_done = True
                
                return content_str, computed_hash

            raise ValueError('Maximum redirects exceeded')

        except Exception as e:
            self.error = f"Download failed for {url}: {str(e)}"
            logger.error(f"FirmwareUpdater: {self.error}")
            if writer and not writer.is_closing():
                writer.close()
                await writer.wait_closed()
            return None, None 

    def percent_complete(self):
        if not self.download_started or self.total_size == 0:
            return 0
        return int((self.bytes_read / self.total_size) * 100)

    def is_download_done(self):
        return self.download_done
    
    # Flag management methods
    def was_interrupted_during_applying(self):
        """Check if the system was interrupted during update application"""
        try:
            uos.stat(self.applying_flag_path)
            return True
        except OSError:
            return False
    
    def remove_applying_flag(self):
        """Remove the applying flag file"""
        try:
            uos.remove(self.applying_flag_path)
            logger.info("Removed applying flag file.", log_to_file=True)
        except OSError:
            pass
    
    def _cleanup_old_update_flag(self):
        """Remove the old update flag when updates are disabled"""
        try:
            uos.remove(self.update_flag_path)
            logger.info("Removed old update flag as updates are disabled.", log_to_file=True)
        except OSError:
            pass
    
    def _read_failure_counter(self):
        """Read the current failure counter from update flag file"""
        try:
            with open(self.update_flag_path, 'r') as f:
                content = f.read().strip()
                if content:
                    return int(content)
        except (OSError, ValueError):
            pass
        return 0
    
    def _write_failure_counter(self, count):
        """Write failure counter to update flag file"""
        with open(self.update_flag_path, 'w') as f:
            f.write(str(count))
    
    def _cleanup_success_flags(self):
        """Internal method to clean up flags after successful operations"""
        try:
            uos.remove(self.update_flag_path)
            logger.info("Update successful. Removed update flag.", log_to_file=True)
        except OSError:
            pass

    async def _fetch_release_metadata(self, metadata_url):
        """Fetch release metadata from the provided URL."""
        # Download metadata
        download_result = await self._download_file(
            metadata_url, target_path=None, store_in_memory=True)
        
        # Unpack download result
        metadata_content_str, metadata_hash = None, None
        if download_result is not None:
            metadata_content_str, metadata_hash = download_result
            
        if self.error or not metadata_content_str:
            error_msg = f"Failed to download latest release metadata: {self.error if self.error else 'No content or download error'}"
            logger.error(error_msg, log_to_file=True)
            return None
            
        return metadata_content_str
        
    def _parse_release_metadata(self, metadata_content_str):
        """Parse metadata and check if a newer version is available."""
        try:
            latest_release = ujson.loads(metadata_content_str)

            if not isinstance(latest_release, dict):
                self.error = "Latest release metadata is not a valid JSON object."
                logger.error(self.error, log_to_file=True)
                return None
            
            if not latest_release: 
                self.error = "No latest release found (empty or invalid response)."
                logger.error(self.error, log_to_file=True)
                return None

            latest_version_str = latest_release.get("tag_name", "0.0.0")
            if not latest_version_str or latest_version_str == "0.0.0":
                 self.error = "Latest release is missing version info (tag_name)."
                 logger.error(self.error, log_to_file=True)
                 return None
                 
            if latest_version_str.startswith('v'):
                latest_version_str = latest_version_str[1:]
                
            return latest_release, latest_version_str
                
        except Exception as e:
            self.error = f"Latest release metadata processing error: {str(e)}"
            logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
            return None
    
    def _compare_versions(self, latest_version_str):
        """Compare current and latest versions to determine if update is needed."""
        try:
            current_semver = self._parse_semver(self.current_version)
            latest_semver = self._parse_semver(latest_version_str)

            if latest_semver <= current_semver:
                return False

            return True
            
        except Exception as e:
            self.error = f"Version comparison error: {str(e)}"
            logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
            return False
            

        
    async def _download_firmware(self, firmware_url):
        """Download the firmware file."""
        self.download_done = False 
        self.download_started = False
        self.bytes_read = 0
        self.total_size = 0

        firmware_download_result = await self._download_file(
            firmware_url, self.firmware_download_path, store_in_memory=False)

        firmware_content_str, computed_sha256 = None, None 
        if firmware_download_result is not None:
            firmware_content_str, computed_sha256 = firmware_download_result

        if self.error or not computed_sha256:
            errmsg = f"Firmware download failed: {self.error if self.error else 'No hash or download error'}"
            logger.error(f"FirmwareUpdater: {errmsg}", log_to_file=True)
            self.pending_update_version = None  # Clear pending version on download error
            return False

        return True

    def should_attempt_update(self):
        """Check if update should be attempted, handling all flag logic internally"""
        # Check if updates are enabled
        if not self.update_on_boot:
            self._cleanup_old_update_flag()
            return False, "Updates disabled in config"
            
        # Check failure counter
        failure_counter = self._read_failure_counter()
        
        if failure_counter >= self.max_failure_attempts:
            logger.error("Max update failure attempts reached.", log_to_file=True)
            self.update_on_boot = False
            logger.info("UPDATE_ON_BOOT disabled to prevent further attempts.", log_to_file=True)
            self._cleanup_old_update_flag()
            return False, f"Max attempts reached ({failure_counter})"
            
        # Start new attempt - increment counter
        next_failure_count = failure_counter + 1
        self._write_failure_counter(next_failure_count)
        
        return True, f"Starting update attempt {next_failure_count}"

    async def check_update(self):
        """Checks if a new firmware update is available without downloading."""
        self.error = None
        self._notify_progress("checking", 0, "Checking for firmware updates...")

        # Fetch and parse metadata
        metadata_url = self.metadata_url if self.is_direct_mode else self.base_url
        self._notify_progress("checking", 25, "Fetching release metadata...")
        metadata_content_str = await self._fetch_release_metadata(metadata_url)

        if not metadata_content_str:
            self._notify_progress("checking", 100, "Failed to fetch metadata", error=self.error)
            return False, None, None

        self._notify_progress("checking", 50, "Parsing release metadata...")
        parse_result = self._parse_release_metadata(metadata_content_str)
        if not parse_result:
            self._notify_progress("checking", 100, "Failed to parse metadata", error=self.error)
            return False, None, None

        latest_release, latest_version_str = parse_result

        # Compare versions
        self._notify_progress("checking", 75, "Comparing versions...")
        is_newer_available = self._compare_versions(latest_version_str)

        if is_newer_available:
            logger.info(f"Update available: {self.current_version} -> {latest_version_str}", log_to_file=True)
            self._notify_progress("checking", 100, f"Update available: {self.current_version} -> {latest_version_str}")
        else:
            self._notify_progress("checking", 100, f"Firmware is up-to-date: {latest_version_str}")
            # If firmware is up-to-date, clean up any leftover update flags (only if they exist)
            if self._path_exists(self.update_flag_path):
                self._cleanup_success_flags()  # Only clean up if flag actually exists
            
        return is_newer_available, latest_version_str, latest_release
    
    async def download_update(self, latest_release):
        """Downloads the firmware update."""
        self.error = None
        self._notify_progress("downloading", 0, "Starting firmware download...")
        
        if not latest_release or not isinstance(latest_release, dict):
            self.error = "Invalid release data"
            self._notify_progress("downloading", 100, "Invalid release data", error=self.error)
            return False

        latest_version_str = latest_release.get("tag_name", "0.0.0")
        if latest_version_str.startswith('v'):
            latest_version_str = latest_version_str[1:]
        
        self.pending_update_version = latest_version_str
        self._notify_progress("downloading", 5, f"Preparing to download version {latest_version_str}")

        # Find firmware URL
        firmware_url, firmware_filename = self._get_firmware_url(latest_release)
        if not firmware_url:
            self.pending_update_version = None
            self._notify_progress("downloading", 100, "No firmware asset found", error=self.error)
            return False

        # Download firmware
        self._notify_progress("downloading", 10, f"Starting download of {firmware_filename}")
        success = await self._download_firmware(firmware_url, firmware_filename)
        if not success:
            self.pending_update_version = None
            self._notify_progress("downloading", 100, "Download failed", error=self.error)
            return False
            
        logger.info(f"Firmware downloaded successfully: {firmware_filename}", log_to_file=True)
        self._notify_progress("downloading", 100, f"Download completed: {firmware_filename}")
        return True
        
    def _get_firmware_url(self, latest_release):
        """Extract firmware download URL from release data."""
        assets = latest_release.get("assets", [])
        
        for asset in assets:
            if asset.get("name", "").endswith(".tar.zlib"):
                return asset.get("browser_download_url"), asset.get("name")
                
        self.error = "No firmware asset found in release"
        return None, None

    @staticmethod
    def _mkdirs(path):
        current_path = ""
        if path.startswith('/'): 
            current_path = "/"
            parts = path.strip('/').split('/')
        else: 
            parts = path.split('/')
        for part in parts:
            if not part: continue
            if current_path == "/" and part: current_path += part
            elif current_path and part: current_path += "/" + part
            elif not current_path and part: current_path = part
            try: uos.mkdir(current_path)
            except OSError as e:
                if e.args[0] != 17: raise 

    def _check_update_archive_exists(self, archive_path):
        """Check if the update archive exists."""
        try:
            uos.stat(archive_path)
            return True
        except OSError as e:
            if e.args[0] == 2:  # ENOENT - No such file or directory
                msg = f"Update archive {archive_path} not found. Assuming already applied or download failed. Aborting apply phase."
                logger.info(f"FirmwareUpdater: {msg}", log_to_file=True)
                print(f"INFO: {msg}")
                return False
            else:
                # Different OSError, perhaps permissions or other issue
                self.error = f"Error accessing update archive {archive_path}: {str(e)}"
                logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
                print(f"ERROR: {self.error}")
                raise  # Re-raise to be caught by caller
    
    async def _decompress_firmware(self, compressed_path, decompressed_path)->bool:
        """Decompress the zlib-compressed firmware file."""
        logger.info(f"Decompressing {compressed_path} to {decompressed_path}...", log_to_file=True)

        f_zlib = None
        d_stream = None
        f_tar_out = None
        result = True
        try:
            f_zlib = open(compressed_path, "rb")
            # Using positional arguments for DeflateIO: stream, format, wbits
            # format=deflate.ZLIB, wbits=0 (for auto window size from header)
            d_stream = deflate.DeflateIO(f_zlib, deflate.ZLIB, 0) 
            f_tar_out = open(decompressed_path, "wb")

            chunk_size = 512 
            while True:
                chunk = d_stream.read(chunk_size)
                if not chunk: break
                f_tar_out.write(chunk)
                led_pin.toggle()
                await asyncio.sleep(0) 
            led_pin.off()


        except Exception as e:
            self.error = f"Decompression failed: {str(e)}"
            logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
            result = False

        finally:
            if f_zlib:
                try: f_zlib.close()
                except Exception as e_close:
                    print(f"Error closing f_zlib: {e_close}")
            if d_stream:
                try: d_stream.close()
                except Exception as e_close:
                    print(f"Error closing d_stream: {e_close}")
            if f_tar_out:
                try: f_tar_out.close()
                except Exception as e_close:
                    print(f"Error closing f_tar_out: {e_close}")
        return result

    def _parse_sha256sums_file(self, extract_to_dir):
        """Parse the integrity.txt file into a dictionary."""
        hash_file_path = f"{extract_to_dir}/integrity.json"
        try:
            with open(hash_file_path, 'r') as hash_file:
                try:
                    # Parse as JSON
                    hash_sums = ujson.load(hash_file)
                    if not isinstance(hash_sums, dict):
                        self.error = "Invalid hash file format: not a JSON object"
                        logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
                        return {}
                    return hash_sums
                except Exception as json_err:
                    self.error = f"Failed to parse hash file as JSON: {str(json_err)}"
                    logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
                    return {}
        except Exception as e:
            self.error = f"Failed to open integrity.json: {str(e)}"
            logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
            return {}

    async def _process_tar_entry(self, tar, entry, extract_to_dir):
        """Process a single tar entry."""
        try:
            if not entry: 
                return False, False  # not processed, no error
                
            file_name = entry.name
            
            # Silently skip PaxHeader entries
            if "@PaxHeader" in file_name:
                return False, False  # not processed, no error
            
            if file_name.startswith('/') or '..' in file_name or file_name.startswith('.'):
                logger.warning(f"Skipping potentially unsafe path: {file_name}", log_to_file=True)
                return False, False  # not processed, no error
                
            target_path = f"{extract_to_dir}/{file_name}"
            
            if entry.type == utarfile.DIRTYPE:
                self._mkdirs(target_path)
                logger.info(f"Processing tar entry: {file_name} ... Type: DIRECTORY, Extract: OK", log_to_file=True)
                return True, False  # processed, no error
                
            else:  # Is a file
                parent_dir = target_path.rpartition('/')[0]
                if parent_dir: 
                    self._mkdirs(parent_dir)  # Ensure parent dir exists
                        
                f_entry = tar.extractfile(entry)
                if f_entry:
                    # If this is the integrity.json file, just extract it normally
                    if file_name == "integrity.json":
                        with open(target_path, "wb") as outfile:
                            while True:
                                chunk = f_entry.read(1024)  # Read in chunks
                                led_pin.toggle()
                                if not chunk: break
                                outfile.write(chunk)
                        led_pin.off()
                        logger.info(f"Extracting tar entry: {file_name} : Ok", log_to_file=True)
                        # Parse the hash file after extracting it
                        self.hash_sums = self._parse_sha256sums_file(extract_to_dir)
                        return True, False  # processed, no error
                    else:
                        # For all other files, compute hash while extracting
                        hash_obj = hashlib.sha256()
                        with open(target_path, "wb") as outfile:
                            while True:
                                chunk = f_entry.read(1024)  # Read in chunks
                                led_pin.toggle()
                                if not chunk: break
                                hash_obj.update(chunk)
                                outfile.write(chunk)
                        led_pin.off()
                        # Verify the hash if we have hash_sums
                        if self.hash_sums:
                            # Convert the hash_obj to a hex string
                            computed_hash = binascii.hexlify(hash_obj.digest()).decode()
                            
                            # Check if we have an expected hash for this file
                            if file_name in self.hash_sums:
                                expected_hash = self.hash_sums[file_name]
                                if computed_hash != expected_hash:
                                    self.error = f"Hash mismatch for {file_name}: computed={computed_hash}, expected={expected_hash}"
                                    logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
                                    return True, True  # processed, but error
                                else:
                                    # Success case - single line log with both hash and extract status
                                    logger.info(f"Extract & verify tar entry: {file_name} : Ok", log_to_file=True)
                            else:
                                logger.warning(f"No hash entry found for {file_name}", log_to_file=True)
                                logger.info(f"Extracting tar entry: {file_name} : Ok", log_to_file=True)

                        return True, False  # processed, no error
                else:
                    logger.error(f"Could not extract file entry: {file_name}", log_to_file=True)
                    return False, True  # not processed, error
                    
        except Exception as e_entry:
            errmsg_entry = f"Error processing tar entry '{entry.name if entry else "UNKNOWN"}': {e_entry}"
            logger.error(f"FirmwareUpdater: {errmsg_entry}", log_to_file=True)
            return False, True  # not processed, error
    
    async def _extract_firmware(self, tar_path, extract_to_dir):
        """Extract the tar file to the specified directory."""
        logger.info(f"Extracting {tar_path} to {extract_to_dir}...", log_to_file=True)
        
        processed_count = 0
        error_count = 0
        # tar = None
        
        try:
            self._mkdirs(extract_to_dir)
        except Exception as e:
            self.error = f"Directory creation failed for {extract_to_dir}: {str(e)}"
            logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
            return False
        
        try:
            tar = utarfile.TarFile(name=tar_path)
            
            # Reset hash_sums before beginning extraction
            self.hash_sums = {}
            
            for entry in tar:  # Iterate through members
                processed, had_error = await self._process_tar_entry(tar, entry, extract_to_dir)
                if processed:
                    processed_count += 1
                if had_error:
                    error_count += 1
                await asyncio.sleep(0)  # Yield during extraction
                    
            logger.info(f"Extraction finished. Files processed: {processed_count}, Errors: {error_count}", log_to_file=True)

        except Exception as e:
            self.error = f"Tar extraction failed: {str(e)}"
            logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
            error_count += 1  # Count this as a major error too
            
        # Check for errors
        if error_count > 0 or self.error:
            if not self.error: 
                self.error = f"{error_count} errors during tar extraction."
            if str(error_count) in self.error and "errors during tar extraction" in self.error: 
                 logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
            return False
            
        if processed_count == 0 and not self.error:
            self.error = "No files were extracted from the tar archive."
            logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
            return False
            
        logger.info(f"Firmware successfully extracted to {extract_to_dir}.", log_to_file=True)
        return True
        
    async def _update_version_file(self):
        """Update the version file with the pending version."""
        if not self.pending_update_version:
            logger.info("Skipping version file update: No pending version was set.", log_to_file=True)
            return True

        logger.info(f"Finalizing update: Writing version {self.pending_update_version} to /version.txt...", log_to_file=True)

        try:
            with open('/version.txt', 'w') as vf:
                vf.write(self.pending_update_version)
            self.current_version = self.pending_update_version
            self.pending_update_version = None  # Clear after successful write
            return True
            
        except Exception as e:
            self.error = f"Critical error: Failed to update version file to {self.pending_update_version} after file system operations: {str(e)}"
            logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
            return False
        
    async def apply_update(self):
        """Apply the downloaded firmware update."""
        self.error = None
        compressed_file_path = self.firmware_download_path
        decompressed_tar_path = "/update.tmp.tar"
        extract_to_dir = "/update"
        
        self._notify_progress("applying", 0, "Starting update application...")
        
        try:
            if not self._check_update_archive_exists(compressed_file_path):
                # No archive, so no temp files to clean beyond what _check_update_archive_exists might imply
                self._notify_progress("applying", 100, "Update archive not found", error="Archive not found")
                return False
        except Exception:
            # Error already set and logged in _check_update_archive_exists
            # No specific temp files created yet to clean here.
            self._notify_progress("applying", 100, "Error accessing update archive", error=self.error)
            return False
            
        logger.info(f"Applying update from {compressed_file_path}...", log_to_file=True)
        self._notify_progress("applying", 10, "Decompressing firmware archive...")
        
        decompression_success = await self._decompress_firmware(compressed_file_path, decompressed_tar_path)
        if not decompression_success:
            # Cleanup only the decompressed tar path if it was created
            await self._cleanup_temp_update_files(compressed_file_path, decompressed_tar_path, extract_to_dir, cleanup_archive=False, cleanup_extracted_dir=False)
            logger.error("Decompression failed, cannot proceed. Update aborted.", log_to_file=True)
            self._notify_progress("applying", 100, "Decompression failed", error=self.error)
            return False
            
        self._notify_progress("applying", 25, "Extracting firmware files...")
        extraction_success = await self._extract_firmware(decompressed_tar_path, extract_to_dir)
        if not extraction_success:
            # Cleanup decompressed tar and potentially partially extracted directory
            await self._cleanup_temp_update_files(compressed_file_path, decompressed_tar_path, extract_to_dir, cleanup_archive=False, cleanup_extracted_dir=True)
            logger.error("Extraction failed, update aborted.", log_to_file=True)
            self._notify_progress("applying", 100, "Extraction failed", error=self.error)
            return False

        if self.core_system_files:
            self._notify_progress("applying", 35, "Checking core system files...")
            logger.info("Checking for core system files in the update package...", log_to_file=True)
            if not self._check_core_files_exist(extract_to_dir):
                logger.error(f"Core system file check failed: {self.error}. Aborting update.", log_to_file=True)
                await self._cleanup_temp_update_files(compressed_file_path, decompressed_tar_path, extract_to_dir, cleanup_archive=False, cleanup_extracted_dir=True)
                self._notify_progress("applying", 100, "Core system file check failed", error=self.error)
                return False
            logger.info("Core system files check passed.", log_to_file=True)
            
        logger.info("Backup existing files.", log_to_file=True)
        self._notify_progress("applying", 45, "Backing up existing files...")
        if not await self._backup_existing_files():
            logger.error(f"Update aborted due to backup failure: {self.error}", log_to_file=True)
            await self._cleanup_temp_update_files(compressed_file_path, decompressed_tar_path, extract_to_dir, cleanup_archive=False, cleanup_extracted_dir=True)
            self._notify_progress("applying", 100, "Backup failed", error=self.error)
            return False

        # Create /__applying flag before starting irreversible operations
        logger.info("Creating /__applying flag file...", log_to_file=True)
        self._notify_progress("applying", 55, "Creating applying flag...")
        try:
            with open('/__applying', 'w') as _:
                pass # Create an empty file
            logger.info("Created /__applying flag file.", log_to_file=True)
        except Exception as e:
            self.error = f"Failed to create /__applying flag: {str(e)}"
            logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
            await self._cleanup_temp_update_files(compressed_file_path, decompressed_tar_path, extract_to_dir, cleanup_archive=False, cleanup_extracted_dir=True)
            self._notify_progress("applying", 100, "Failed to create applying flag", error=self.error)
            return False


        logger.info("Copy files from /update to /.", log_to_file=True)
        self._notify_progress("applying", 65, "Applying updated files to system...")
        if not await self._move_from_update_to_root(extract_to_dir): # Pass extract_to_dir for cleanup
            logger.error(f"Update aborted due to overwrite failure: {self.error}", log_to_file=True)
            # Attempt to restore from backup if move fails, as system might be in inconsistent state
            logger.info("Attempting to restore from backup due to overwrite failure...", log_to_file=True)
            self._notify_progress("applying", 70, "Restoring from backup due to failure...")
            await self.restore_from_backup() # Logged internally
            await self._cleanup_temp_update_files(compressed_file_path, decompressed_tar_path, extract_to_dir, cleanup_archive=False, cleanup_extracted_dir=True)
            self._notify_progress("applying", 100, "File overwrite failed", error=self.error)
            return False
            
        self._notify_progress("applying", 85, "Updating version file...")
        version_update_success = await self._update_version_file()
        # We proceed to cleanup and reboot even if version update fails, logging the error.
        if not version_update_success:
            logger.error(f"Failed to update version file (error: {self.error}), but continuing to finalize update.", log_to_file=True)

        logger.info("Update process appears successful. Performing final cleanup...", log_to_file=True)
        self._notify_progress("applying", 95, "Cleaning up temporary files...")
        await self._cleanup_temp_update_files(compressed_file_path, decompressed_tar_path, extract_to_dir, cleanup_archive=True, cleanup_extracted_dir=True)
        # Step 7.5: Remove __applying flag file
        self.remove_applying_flag()
            
        logger.info("System update successfully applied. Rebooting device...", log_to_file=True)
        
        # Automatically clean up success flags since update was successful
        self._cleanup_success_flags()
        
        self._notify_progress("applying", 100, "Update completed successfully. Rebooting...")
        await asyncio.sleep(1)  # Brief pause for logs to potentially flush
        #machine.reset()
        
        return True

    async def _copy_item_recursive(self, source_path, dest_path):
        # Ensure parent of dest_path exists for the current item being copied
        dest_parent_dir = dest_path.rpartition('/')[0]
        if dest_parent_dir and dest_parent_dir != "/": # Avoid trying to mkdir "/" or empty string
            self._mkdirs(dest_parent_dir) # _mkdirs handles existing dirs

        s_stat = uos.stat(source_path)
        is_dir = (s_stat[0] & 0x4000) != 0 # S_IFDIR check

        if is_dir:
            self._mkdirs(dest_path) # Create the directory itself in destination
            log_msg = f"Copying dir: {source_path} to {dest_path}"
            logger.info(log_msg, log_to_file=True)
            for item_name in uos.listdir(source_path):
                await self._copy_item_recursive(f"{source_path.rstrip('/')}/{item_name}", f"{dest_path.rstrip('/')}/{item_name}")
                await asyncio.sleep(0) # Yield during directory iteration
        else: # Is a file
            log_msg = f"Copying file: {source_path} to {dest_path}"
            logger.info(log_msg, log_to_file=True)
            try:
                with open(source_path, 'rb') as src_f, open(dest_path, 'wb') as dst_f:
                    while True:
                        chunk = src_f.read(self.chunk_size) 
                        led_pin.toggle()
                        if not chunk: break
                        dst_f.write(chunk)
                        await asyncio.sleep(0) # Yield after each chunk
                    led_pin.off()
            except Exception as e:
                raise Exception(f"Failed to copy file {source_path} to {dest_path}: {str(e)}")

    async def _remove_dir_recursive(self, dir_path):
        log_msg = f"Recursively removing directory: {dir_path}"
        logger.info(log_msg, log_to_file=True)
        
        # Ensure dir_path is not root, as a safeguard
        if dir_path == '/' or not dir_path:
            err_msg = "Attempted to remove root directory or empty path."
            logger.error(f"CRITICAL ERROR: {err_msg}", log_to_file=True)
            self.error = err_msg
            raise Exception(err_msg)
            
        for item_name in uos.listdir(dir_path):
            item_path = f"{dir_path.rstrip('/')}/{item_name}"
            try:
                s_stat = uos.stat(item_path)
                is_dir = (s_stat[0] & 0x4000) != 0
                if is_dir:
                    await self._remove_dir_recursive(item_path)
                else:
                    uos.remove(item_path)
            except OSError as e:
                 # If stat fails (e.g. broken symlink or non-existent during concurrent modification)
                 # or remove fails. Log and continue if possible, or re-raise if critical.
                 err_msg_item = f"Error processing {item_path} during recursive delete of {dir_path}: {e}"
                 logger.warning(f"FirmwareUpdater: {err_msg_item}", log_to_file=True)
            await asyncio.sleep(0) # Yield
        uos.rmdir(dir_path)

    async def _backup_existing_files(self):
        step_msg = "Backing up existing system files..."
        logger.info(step_msg, log_to_file=True)
        
        backup_dir = "/backup"
        # Exclude backup dir, update dir, temp files, logs, and sensitive configs
        excluded_top_level_items = [
            backup_dir, 
            "/update", 
            self.firmware_download_path, # /update.tar.zlib
            "/update.tmp.tar",
            "/log.txt",
            "/__updating",
            "/__applying"
        ]
        try:
            self._mkdirs(backup_dir) # Ensure backup_dir itself exists
            
            root_items = uos.listdir("/")
            for item_name in root_items:
                # Construct full source path from root
                source_path = f"/{item_name.lstrip('/')}"
                
                if source_path in excluded_top_level_items:
                    skip_msg = f"Backup: Skipping excluded top-level item: {source_path}"
                    logger.info(skip_msg, log_to_file=True)
                    continue

                # Construct full destination path within backup_dir
                dest_path = f"{backup_dir.rstrip('/')}{source_path}" 
                try:
                    await self._copy_item_recursive(source_path, dest_path)
                except Exception as e_copy:
                    self.error = f"Backup error for {source_path} to {dest_path}: {str(e_copy)}"
                    logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
                    return False # Abort backup on first error
                await asyncio.sleep(0) # Yield between top-level items
            
            success_msg = "Backup completed successfully."
            logger.info(success_msg, log_to_file=True)
            return True
        except Exception as e_main:
            self.error = f"Backup process failed: {str(e_main)}"
            logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
            return False
        
    @staticmethod
    def _is_existing_path_a_directory(path:str) -> bool:
        try:
            s_stat = uos.stat(path)
            return (s_stat[0] & 0x4000) != 0
        except OSError:
            return False
        
        
    @staticmethod
    def _path_exists(path:str) -> bool:
        try:
            uos.stat(path)
            return True
        except OSError as e:
            if e.args[0] == 2:
                return False
            else:
                raise e

    async def _merge_directories_recursive(self, source_dir, dest_dir):
        """Recursively merge source directory into destination directory using atomic operations"""
        logger.info(f"Merging directory: {source_dir} -> {dest_dir}", log_to_file=True)
        
        try:
            # Check if source directory exists
            if not self._path_exists(source_dir):
                logger.warning(f"Source directory doesn't exist: {source_dir}", log_to_file=True)
                return True
            
            # Ensure destination directory exists
            if not self._path_exists(dest_dir):
                # Destination doesn't exist - we can just rename the entire directory atomically
                logger.info(f"Destination directory doesn't exist, atomic move: {source_dir} -> {dest_dir}", log_to_file=True)
                uos.rename(source_dir, dest_dir)
                return True
            
            # Both directories exist, need to merge contents
            source_items = uos.listdir(source_dir)
            
            for item_name in source_items:
                source_item = f"{source_dir.rstrip('/')}/{item_name}"
                dest_item = f"{dest_dir.rstrip('/')}/{item_name}"
                
                # Safety check - skip dangerous system paths when merging to root
                if dest_dir == "/" and item_name in ["dev", "proc", "sys", "boot"]:
                    logger.warning(f"Skipping system directory: {dest_item}", log_to_file=True)
                    continue
                
                source_is_dir = self._is_existing_path_a_directory(source_item)
                dest_exists = self._path_exists(dest_item)
                dest_is_dir = dest_exists and self._is_existing_path_a_directory(dest_item)
                
                if not dest_exists:
                    # Destination doesn't exist - atomic move
                    logger.info(f"Atomic move: {source_item} -> {dest_item}", log_to_file=True)
                    uos.rename(source_item, dest_item)
                    
                elif source_is_dir and dest_is_dir:
                    # Both are directories - recurse
                    logger.info(f"Recursing into directories: {source_item} -> {dest_item}", log_to_file=True)
                    if not await self._merge_directories_recursive(source_item, dest_item):
                        return False
                    
                elif not source_is_dir and not dest_is_dir:
                    # Both are files - atomic replacement
                    logger.info(f"Atomic file replacement: {source_item} -> {dest_item}", log_to_file=True)
                    uos.rename(source_item, dest_item)
                    
                else:
                    # Type mismatch (file->dir or dir->file) - atomic replacement
                    logger.info(f"Type mismatch atomic replacement: {source_item} -> {dest_item}", log_to_file=True)
                    uos.rename(source_item, dest_item)
                
                await asyncio.sleep(0)  # Yield control
            
            # Try to remove now-empty source directory
            try:
                uos.rmdir(source_dir)
                logger.info(f"Removed empty source directory: {source_dir}", log_to_file=True)
            except OSError as e:
                # Directory not empty (shouldn't happen) or other error
                logger.warning(f"Could not remove source directory {source_dir}: {e}", log_to_file=True)
            
            return True
            
        except Exception as e:
            self.error = f"Directory merge failed for {source_dir} -> {dest_dir}: {str(e)}"
            logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
            return False

    async def _move_from_update_to_root(self, update_source_dir): # Added update_source_dir parameter
        """Move files from update to root using recursive directory merging with atomic operations"""
        step_msg = "Moving updated files from /update to / using atomic operations..."
        logger.info(step_msg, log_to_file=True)
        
        try:
            if not self._path_exists(update_source_dir):
                warn_msg = f"Warning: Update source directory '{update_source_dir}' not found. Nothing to move."
                logger.warning(warn_msg, log_to_file=True)
                return True # Nothing to move, so operation is vacuously successful.

            # Simply merge the update directory into root using recursive atomic operations
            success = await self._merge_directories_recursive(update_source_dir, "/")
            
            if success:
                logger.info("Atomic recursive merge completed successfully.", log_to_file=True)
            else:
                logger.error("Atomic recursive merge failed.", log_to_file=True)
                
            return success
            
        except Exception as e_main_move:
            self.error = f"Atomic file move process failed: {str(e_main_move)}"
            logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
            return False

    async def restore_from_backup(self):
        """Restore system files from backup after failed update."""
        self.error = None
        logger.info("Attempting to restore system from backup...", log_to_file=True)
        self._notify_progress("restoring", 0, "Starting system restore from backup...")
        
        # Check if backup directory exists
        try:
            if not self.backup_dir.strip('/') in uos.listdir('/'):
                self.error = f"Backup directory {self.backup_dir} not found"
                logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
                self._notify_progress("restoring", 100, "Backup directory not found", error=self.error)
                return False
        except Exception as e:
            self.error = f"Error checking backup directory: {str(e)}"
            logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
            self._notify_progress("restoring", 100, "Error checking backup directory", error=self.error)
            return False
            
        try:
            # List all files and directories in backup
            self._notify_progress("restoring", 10, "Scanning backup directory...")
            items = uos.listdir(self.backup_dir)
            if not items:
                self.error = "Backup directory is empty"
                logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
                self._notify_progress("restoring", 100, "Backup directory is empty", error=self.error)
                return False
                
            # Process each item in the backup directory
            total_items = len(items)
            for i, item_name in enumerate(items):
                progress = 20 + int((i / total_items) * 70)  # 20-90% for file restoration
                self._notify_progress("restoring", progress, f"Restoring {item_name}...")
                source_path = f"{self.backup_dir.rstrip('/')}/{item_name}"
                dest_path = f"/{item_name}"
                
                # Check if destination already exists and remove it
                try:
                    uos.stat(dest_path)  # Check if exists
                    s_stat_dest = uos.stat(dest_path)
                    is_dir_dest = (s_stat_dest[0] & 0x4000) != 0
                    if is_dir_dest:
                        logger.info(f"Removing existing directory before restore: {dest_path}", log_to_file=True)
                        await self._remove_dir_recursive(dest_path)
                    else:
                        logger.info(f"Removing existing file before restore: {dest_path}", log_to_file=True)
                        uos.remove(dest_path)
                except OSError as e:
                    if e.args[0] == 2:  # ENOENT (file not found)
                        pass  # Destination doesn't exist, which is fine
                    else:
                        logger.warning(f"Error checking/removing {dest_path}: {e}", log_to_file=True)
                        # Continue with restoration - not critical if we can't remove
                
                # Copy from backup to root
                try:
                    logger.info(f"Restoring {source_path} to {dest_path}", log_to_file=True)
                    await self._copy_item_recursive(source_path, dest_path)
                except Exception as e_copy:
                    self.error = f"Failed to restore {source_path} to {dest_path}: {str(e_copy)}"
                    logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
                    return False
                    
                # Yield to prevent blocking for too long
                await asyncio.sleep(0)
                    
            logger.info("System successfully restored from backup", log_to_file=True)
            self._notify_progress("restoring", 100, "System successfully restored from backup")
            self.remove_applying_flag()
            return True
            
        except Exception as e:
            self.error = f"System restore process failed: {str(e)}"
            logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
            self._notify_progress("restoring", 100, "System restore failed", error=self.error)
            self.remove_applying_flag()  # Remove flag even on failure
            return False

    def _check_core_files_exist(self, extract_to_dir):
        """Check if all core system files exist in the extracted update."""
        if not self.core_system_files:
            logger.info("No core system files defined. Skipping check.", log_to_file=True)
            return True # Nothing to check, so it passes

        missing_files = []
        for core_file_rel_path in self.core_system_files:
            # Ensure core_file_rel_path is relative and doesn't start with /
            normalized_path = core_file_rel_path.lstrip('/')
            full_path_to_check = f"{extract_to_dir.rstrip('/')}/{normalized_path}"
            try:
                uos.stat(full_path_to_check)
                logger.info(f"Core file found: {full_path_to_check}", log_to_file=True)
            except OSError as e:
                if e.args[0] == 2: # ENOENT - No such file or directory
                    missing_files.append(normalized_path)
                    logger.error(f"Core file MISSING: {full_path_to_check}", log_to_file=True)
                else:
                    # Other OSError (e.g., permission denied)
                    self.error = f"Error accessing potential core file {full_path_to_check}: {str(e)}"
                    logger.error(f"FirmwareUpdater: {self.error}", log_to_file=True)
                    return False # Abort on access error

        if missing_files:
            self.error = f"Update aborted: Missing core system files in package: {', '.join(missing_files)}"
            # Logger error is already done per file, this is a summary.
            return False
        
        return True

    async def _cleanup_temp_update_files(self, compressed_file_path, decompressed_tar_path, extract_to_dir, cleanup_archive=True, cleanup_extracted_dir=True):
        """Clean up temporary files and directories used during the update process."""
        logger.info("Cleaning up temporary update files...", log_to_file=True)
        
        # Remove decompressed tar file
        if decompressed_tar_path:
            try:
                uos.stat(decompressed_tar_path) # Check if it exists before trying to remove
                uos.remove(decompressed_tar_path)
                logger.info(f"Removed temporary decompressed file: {decompressed_tar_path}", log_to_file=True)
            except OSError as e:
                if e.args[0] == 2: # ENOENT
                    logger.info(f"Temporary decompressed file not found (already removed?): {decompressed_tar_path}", log_to_file=True)
                else:
                    logger.warning(f"Could not remove temporary decompressed file {decompressed_tar_path}: {str(e)}", log_to_file=True)
        
        # Remove extracted update directory
        if cleanup_extracted_dir and extract_to_dir:
            try:
                # Check if extract_to_dir exists as a directory
                s_stat = uos.stat(extract_to_dir)
                is_dir = (s_stat[0] & 0x4000) != 0
                if is_dir:
                    await self._remove_dir_recursive(extract_to_dir)
                    logger.info(f"Removed temporary extraction directory: {extract_to_dir}", log_to_file=True)
                else: # It exists but is not a directory (should not happen if extraction was successful)
                    logger.warning(f"Temporary extraction path {extract_to_dir} exists but is not a directory. Attempting to remove as file.", log_to_file=True)
                    uos.remove(extract_to_dir)
            except OSError as e:
                if e.args[0] == 2: # ENOENT
                     logger.info(f"Temporary extraction directory not found (already removed?): {extract_to_dir}", log_to_file=True)
                else:
                    logger.warning(f"Could not remove temporary extraction directory {extract_to_dir}: {str(e)}", log_to_file=True)
            except Exception as e_rec: # Catch errors from _remove_dir_recursive
                logger.error(f"Error during recursive removal of {extract_to_dir}: {e_rec}", log_to_file=True)

        # Optionally remove the original downloaded archive
        if cleanup_archive and compressed_file_path:
            try:
                uos.stat(compressed_file_path) # Check if it exists
                uos.remove(compressed_file_path)
                logger.info(f"Removed downloaded update archive: {compressed_file_path}", log_to_file=True)
            except OSError as e:
                if e.args[0] == 2: # ENOENT
                    logger.info(f"Downloaded update archive not found (already removed?): {compressed_file_path}", log_to_file=True)
                else:
                    logger.warning(f"Could not remove downloaded update archive {compressed_file_path}: {str(e)}", log_to_file=True)
        logger.info("Temporary file cleanup finished.", log_to_file=True)

# Example usage (conceptual, assuming an event loop is running):
# async def main():
