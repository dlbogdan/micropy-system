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

For a new application repository, add this framework as a submodule and run its
initializer:

```sh
git submodule add https://github.com/dlbogdan/micropy-system.git vendor/micropy-system
git submodule update --init --recursive
vendor/micropy-system/tools/init_project.sh
tools/setup_build_env.sh
cp system-config.example.json system-config.json
```

The initializer is non-destructive: it creates missing application boilerplate,
build/serve/framework-update scripts, configuration templates, editor settings,
ignore rules, and the GitHub release workflow without replacing existing files.

Edit `system-config.json` with the device model, Wi-Fi credentials, and update
source. For local development, set `DIRECT_BASE_URL` to the builder machine's
trusted-LAN URL (for example `http://192.168.1.10:8000/`) and enable
`UPDATE_ON_BOOT`.

For the first installation on a blank Pico, run:

```sh
python3 tools/assemble.py
```

Configure MicroPico to synchronize only the generated `device` directory, then
upload that complete tree once and reset the board. This bootstraps stable
`boot.py`, the stable A/B selector, framework libraries, OTA state, and the
initial application in slot A. Do not synchronize the application repository
root. Subsequent application releases use OTA and must not replace stable root
infrastructure.

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

### Application-to-Pico workflow

1. Develop application code under `app`. The application entry point is
   `app/main.py` and must expose an asynchronous `main()` function.
2. Increment `app/version.txt` using `MAJOR.MINOR.PATCH`. The offered version
   must be newer than the version currently stored on the Pico.
3. Build and assemble using the application-owned helper:

   ```sh
   tools/build_firmware.sh
   # Or select version and board explicitly:
   tools/build_firmware.sh 1.2.3 pico2-w-rp2350
   ```

   This refreshes the bootstrap-only `device` tree and creates the A/B OTA
   archive plus `metadata.json` and `image-info.json` under `build`.
4. Keep the local server running in a separate terminal:

   ```sh
   tools/serve_update.sh 8000
   ```

   The build port, server port, and `DIRECT_BASE_URL` port must match. Do not
   start a second server if the selected port is already in use.
5. Reset or power-cycle the Pico. On boot it fetches metadata, verifies and
   downloads the artifact, streams it into the inactive slot, persists the
   candidate selector, and reboots into that candidate.
6. After its application-level health checks and a short period of stable event
   loop operation, the candidate must confirm itself:

   ```python
   from lib.coresys.ota_state import load_state
   from lib.coresys.slot_manager import confirm_running_slot

   state = load_state()
   running_slot = state["pending"] or state["active"]
   confirm_running_slot(running_slot)
   ```

   Confirmation must not depend on Internet availability. If the candidate
   raises or fails to confirm before its deadline, the watchdog resets the
   board, the stable selector restores the previous slot, and the failed
   version is quarantined.
7. Verify a successful promotion over USB if needed:

   ```sh
   mpremote connect auto exec "from lib.coresys.ota_state import load_state; print(open('/version.txt').read()); print(load_state())"
   ```

   A healthy result has the new version, `pending` set to `None`, zero candidate
   attempts, no rejected version, and the newly selected active slot.
8. Commit and push the application source, version, and any intentional
   framework submodule update. The generated `build` and `device` trees should
   normally remain uncommitted.

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

Normal releases are A/B application-only images. The application
source `main.py` is packaged as `app_entry.py`; stable root launchers and OTA
infrastructure are excluded from normal slot releases:

```sh
python local_builder.py --source-dir app --output-dir build \
  --model pico2-w-rp2350 --version 2.0.0
```

The inactive slot is erased and rebuilt, so removed and renamed files disappear
without deletion manifests. Root merge, full-root backup, and `/__applying`
restore semantics are no longer part of normal OTA. Peak update storage is the
active slot, old inactive slot, and compressed staging artifact; the installer
reclaims the old inactive slot before streaming extraction when necessary.

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

Application repositories invoke the same builder through a pinned Git
submodule without copying its implementation:

```sh
python vendor/micropy-system/local_builder.py \
  --source-dir app \
  --output-dir build \
  --model pico2-w-rp2350 \
  --version 1.0.1
```

Paths are resolved from the caller's working directory. Normal OTA input is the
application source directory; its `main.py` becomes slot-local `app_entry.py`.
The complete assembled `device` tree exists only for initial USB provisioning.

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
