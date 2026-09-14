# MicroPython Firmware System Manager

A robust framework for managing MicroPython-based IoT devices with automatic over-the-air (OTA) firmware updates, WiFi connectivity management, and system monitoring capabilities.

## Overview

This project provides a complete system management solution for MicroPython-enabled microcontrollers (particularly optimized for Raspberry Pi Pico W). It handles:

- **OTA Firmware Updates**: Automatic updates from GitHub releases or a direct server
- **WiFi Management**: Non-blocking WiFi connection and monitoring
- **System Monitoring**: Memory usage, task management, and diagnostics
- **Configuration Management**: Central configuration system for all components

## Features

### Firmware Updates

- **Multiple Update Sources**: Support for GitHub releases or direct server URLs
- **Progress Tracking**: Callback system to monitor update progress
- **Secure Updates**: HTTPS connections with optional GitHub token authentication
- **Fault Tolerance**: Backup and recovery mechanisms for interrupted updates
- **Version Control**: Semantic versioning-based update checks

### Network Management

- **Non-blocking WiFi**: Asynchronous connection handling that doesn't interfere with other operations
- **Connection Monitoring**: Automatic reconnection and status reporting
- **Configurable**: Easy hostname and credential configuration

### System Management

- **Task Management**: Background task scheduling and monitoring
- **Resource Monitoring**: Memory usage tracking and reporting
- **Singleton Pattern**: Efficient resource usage through singleton design
- **Diagnostic Reports**: Comprehensive system status reporting

## Project Structure

- **boot.py**: Handles system initialization and firmware update checks on boot
- **main.py**: Main application loop and system component initialization
- **lib/coresys/**: Core system modules
  - **manager_firmware.py**: OTA firmware update functionality
  - **manager_system.py**: System coordination and monitoring
  - **manager_wifi.py**: WiFi connection management
  - **manager_config.py**: Configuration management
  - **manager_tasks.py**: Background task scheduling
  - **logger.py**: Logging utilities

## Configuration

The system is configured through a JSON file (`/system-config.json`) with the following key sections:

```json
{
  "DEVICE": {
    "NAME": "micropython-device",
    "MODEL": "generic"
  },
  "WIFI": {
    "SSID": "your-wifi-ssid",
    "PASS": "your-wifi-password"
  },
    "FIRMWARE": {
    "GITHUB_REPO": "username/repo",
    "GITHUB_TOKEN": "",
    "DIRECT_BASE_URL": "https://your-update-server.com/firmware/",
    "UPDATE_ON_BOOT": true,
    "CHUNK_SIZE": 2048,
    "MAX_REDIRECTS": 10,
    "CORE_SYSTEM_FILES": [
            "boot.py",
            "lib/coresys/manager_firmware.mpy",
            "lib/coresys/manager_system.mpy",
            "lib/coresys/manager_wifi.mpy",
            "lib/coresys/manager_config.mpy",
            "lib/coresys/logger.mpy",
            "lib/coresys/manager_tasks.mpy"
    ],
    "MAX_FAILURE_ATTEMPTS": 3,
    "NETWORK_TIMEOUT_MS": 60000,
    "REQUEST_TIMEOUT_MS": 15000,
    "RUNTIME_VERSION": "1.29.0",
    "MPY_VERSION": 6
  }
}
```

## Getting Started

### Supported Runtime and Hardware Baseline

The current toolchain targets MicroPython 1.29.0 on both Pico W (RP2040) and
Pico 2 W (RP2350), with separate board-specific IntelliSense profiles and a
matching pinned `mpy-cross` release. Before enabling OTA installation on a
board, provision MicroPython 1.29.0 and capture its runtime, MPY ABI, filesystem
capacity, heap baseline, and LittleFS rename behavior by following
[HARDWARE_BASELINE.md](HARDWARE_BASELINE.md). Do not assume that CPython or a
desktop filesystem has the same rename semantics as the Pico.

### Prerequisites

- MicroPython-compatible device (tested on Raspberry Pi Pico W)
- MicroPython firmware installed (Python 3.x compatible)
- Network connectivity (WiFi)

### Installation

1. Clone this repository
2. Copy all files to your MicroPython device
3. Create or modify the `/system-config.json` file with your configuration
4. Reset the device to start the system

### Update Server Options

#### GitHub Releases

Set the `GITHUB_REPO` in your configuration to use GitHub releases for updates. Your releases should include:

- A zipped firmware bundle
- Version information following semantic versioning (e.g., "1.2.3")

#### Direct Server

Set the `DIRECT_BASE_URL` to point to a server hosting firmware updates. The server should provide:

- A `metadata.json` file with version information
- Firmware bundles in the expected format

## Development

### Testing Updates Locally

The project includes `firmware_server.py` for local testing:

```
python firmware_server.py
```

This starts a local HTTPS server serving firmware updates for testing.

### Creating Firmware Bundles

Firmware updates should be packaged as TAR archives with ZLIB compression, containing all files to be updated.

Local builds must select a target board because Pico W and Pico 2 W releases
are separate assets:

```sh
.venv/bin/python local_builder.py --model pico-w-rp2040 --version 1.0.1
.venv/bin/python local_builder.py --model pico2-w-rp2350 --version 1.0.1
```

Application repositories can invoke the same builder through a pinned Git
submodule and package an assembled device tree without copying the builder:

```sh
python vendor/micropy-system/local_builder.py \
  --source-dir device \
  --output-dir build \
  --model pico2-w-rp2350 \
  --version 1.0.1
```

Paths are resolved from the caller's working directory. The source directory
must represent the final Pico filesystem layout, including root-level
`boot.py` and `main.py`. This keeps application overlays and release workflows
in the application repository while the packaging implementation remains in
`micropy-system`.

Release asset metadata includes the model, compressed size, SHA-256,
MicroPython runtime version, and MPY format. The device validates these fields
before decompressing the update.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License.

## Acknowledgements

- MicroPython project for providing the foundation
- Asyncio library for MicroPython enabling non-blocking operations
