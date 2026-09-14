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

The project includes a dependency-free HTTP server for local testing. Build
with the same port that the server will use, then start it:

```sh
.venv/bin/python local_builder.py --model pico2-w-rp2350 --version 1.0.1 --port 8000
.venv/bin/python firmware_server.py --directory build --port 8000
```

Use the printed `http://LAN_ADDRESS:8000/` value as `DIRECT_BASE_URL`. Target
projects created by `tools/init_project.sh` also receive
`tools/serve_update.sh`, so their local flow is simply:

```sh
tools/build_firmware.sh 1.0.1 pico2-w-rp2350
tools/serve_update.sh
```

If port 8000 is already occupied, either stop the existing server or choose a
matching alternate port for both build and serving (for example 8001). The
generated serving helper accepts the port as its first argument.

Plain HTTP avoids MicroPython trust-store problems with self-signed
certificates. It is deliberately intended only for a trusted development LAN;
production GitHub downloads continue to use HTTPS.

Existing devices that still contain the HTTPS-only updater cannot fetch their
first HTTP update. Bootstrap this transport change once over USB: reassemble
the device tree and synchronize it with MicroPico (or replace
`lib/coresys/manager_firmware.py`/`.mpy` manually), then reset the board. If an
older `manager_firmware.mpy` is present beside a newly copied `.py`, remove the
stale `.mpy` so MicroPython cannot continue importing the old implementation.

Target-project assembly adds a `.micropy-system-device-tree` marker. Configure
MicroPico's sync folder as `device`; the initializer creates a minimal
`.vscode/settings.json` containing only this setting and leaves an existing
settings file unchanged. It does not create `.micropico`. Never synchronize
the repository root.
Host-side build tooling rejects common project-root paths such as `vendor`,
`tools`, nested `device`, and `build`. Device runtime code deliberately makes
no assumptions about legitimate application directory names.

### Creating Firmware Bundles

Firmware updates should be packaged as TAR archives with ZLIB compression, containing all files to be updated.

Local builds must select a target board because Pico W and Pico 2 W releases
are separate assets:

```sh
.venv/bin/python local_builder.py --model pico-w-rp2040 --version 1.0.1
.venv/bin/python local_builder.py --model pico2-w-rp2350 --version 1.0.1
```

The default `--output-mode direct-server` writes the compressed artifact,
GitHub-shaped `metadata.json`, and `image-info.json`. Use
`--output-mode github-assets` for a GitHub release artifact plus its compact
`image-info.json` sidecar; GitHub itself supplies the API release response.
Use `--module-format py` to package debuggable source modules instead of the
default compiled `.mpy` modules. The builder rejects ambiguous prepared trees
that contain both representations of the same module.

The build toolchain pins `mpy-cross==1.29.0.post2` for MicroPython 1.29.0 and
verifies that it emits MPY v6.3 before compiling. Release metadata records the
module format, MPY major/sub-version, and target architecture (`armv6m` for
Pico W or `armv8m` for Pico 2 W). Compiled releases with incompatible metadata
are rejected before artifact download; source-format releases do not require
an MPY ABI match.

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

When this repository is installed at `vendor/micropy-system` as a Git
submodule, initialize the surrounding application repository with:

```sh
vendor/micropy-system/tools/init_project.sh
```

The initializer never overwrites existing files. It creates an application
overlay, deterministic device-tree assembler, framework-update helper,
configuration template, ignore rules, and an application-owned GitHub Actions
release workflow. Pass an explicit project path when running the initializer
outside a submodule checkout.

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
