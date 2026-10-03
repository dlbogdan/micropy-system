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

## Quick Start: new project tutorial

The complete path from an empty repository to a Wi-Fi board running your app,
then the day-to-day loop. Run everything from the project root; the framework
lives in a submodule (`micropy-system/` below — use your path if it differs,
e.g. `vendor/micropy-system/`).

### 1. Add the framework

```sh
git submodule add https://github.com/dlbogdan/micropy-system.git micropy-system
./micropy-system/tools/micropy-wiring/init_project.py    # app skeleton + templates (non-destructive)
./micropy-system/tools/build/setup_build_env.py # .venv with mpy-cross, pyserial, ...
git add -A && git commit -m "Bootstrap micropy-system project"
```

### 2. Configure

- `system-config.json` (copy of `system-config.example.json`, gitignored):
  device name/model and `WIFI.SSID` / `WIFI.PASS`.
- `update-source.json` (optional, project root): which OTA source boards check —
  `{"mode": "local", "local": {"base_url": "http://<builder-lan-ip>:8000"}}`
  or `{"mode": "github", "github": {"repo": "user/repo", "token": ""}}`.
  No usable source forces `UPDATE_ON_BOOT` off.
- `app/main.py`: your app — must expose `async def main()`; do **not** call
  `asyncio.run()` and do **not** return.
- `app/version.txt`: `MAJOR.MINOR.PATCH`; must increase with every deploy.

### 3. Provision a blank board (one time, over USB)

```sh
./micropy-system/tools/target/provision.py --ssid "MyNet" --pass "secret"          # Pico 2 W (RP2350)
./micropy-system/tools/target/provision.py --board pico-w --ssid "MyNet" --pass "secret"  # Pico W (RP2040)
```

Flashes the pinned MicroPython 1.29.0, formats the data LFS (a UF2 flash does
**not** erase it), uploads the assembled device tree + resolved config,
verifies the app reaches its main loop, and performs the required final reset.
No network needed; the board is then autonomous.

### 4. Develop and deploy (Wi-Fi only, no USB)

```sh
DEVICE_IP=10.9.30.76 ./micropy-system/tools/target/deploy.py
```

`deploy.py` bumps `app/version.txt`, builds the app-only OTA package into
`build/`, (re)starts the local update server on `:8000`, reboots the board
over its shell (the boot-time OTA check downloads + installs *before* the
shell comes back — a silent ~10–20 s gap is normal), polls for A/B slot
promotion, and runs the app's self-test. `DEPLOY OK` means the new version is
active and the board is left running.

### 5. Inspect the running board

```sh
./micropy-system/tools/target/telnet.py 10.9.30.76 status    # one-line JSON
./micropy-system/tools/target/telnet.py 10.9.30.76 log 40    # last 40 log lines
./micropy-system/tools/target/telnet.py 10.9.30.76 selftest  # app-registered checks
./micropy-system/tools/target/telnet.py 10.9.30.76           # interactive command shell
# stock clients work too: telnet 10.9.30.76 | nc 10.9.30.76 23
```

### 6. Release to GitHub (optional)

```sh
./micropy-system/tools/micropy-wiring/release_github.py 1.2.0   # tag + push; project CI builds the release
```

Point boards at it by switching `update-source.json` to `"github"` mode and
re-provisioning (or editing the board config) — `deploy.py` always uses the
local server, so local and GitHub modes coexist.

### Update-model facts that matter

- **OTA packages carry only the app slot** (`app_entry.py` + app modules).
  Framework code under `lib/coresys/` reaches an *existing* board only via
  re-provisioning (or a shell-`repl` injection + reboot); a fresh board gets
  everything from `provision.py`.
- **Power-on self-test (POST) + A/B safety:** the *framework launcher*
  (`main.py` from `slot_main.py`, harness `lib/coresys/post.py`) runs a
  power-on self-test on every boot *before* a candidate may confirm — a
  free-heap check plus the guest's optional `post_checks()` hook (a list of
  `(name, ok, detail)` tuples defined on `app_entry`). A passing candidate is
  confirmed inside the watchdog window; a failing one is rolled back and
  quarantined, so the guest never owns A/B safety. The launcher records the
  boot context; the app reads `post.is_candidate_boot()` / `post.is_degraded()`
  and holds non-idempotent physical actuation (boiler, relays, setpoint
  release) for a candidate or degraded boot. A guest with no `post_checks()`
  still gets the heap check and full confirm/rollback protection.
- **USB stops the app:** `mpremote` (Ctrl-C) interrupts whatever is running.
  After provisioning, do everything over the shell (port 23).

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
vendor/micropy-system/tools/micropy-wiring/init_project.py
vendor/micropy-system/tools/build/setup_build_env.py
cp system-config.example.json system-config.json
```

The initializer is non-destructive: it creates missing application boilerplate,
configuration templates, editor settings, ignore rules, and the GitHub release
workflow without replacing existing files. It does not generate project tools —
every helper is invoked through the submodule path (see Device tools).

Edit `system-config.json` with the device model, Wi-Fi credentials, and update
source. For local development, set `DIRECT_BASE_URL` to the builder machine's
trusted-LAN URL (for example `http://192.168.1.10:8000/`) and enable
`UPDATE_ON_BOOT`.

For the first installation on a blank Pico, run:

```sh
python3 vendor/micropy-system/tools/build/assemble.py
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

Use the printed `http://LAN_ADDRESS:8000/` value as `DIRECT_BASE_URL`. Projects
invoke the framework tools through the submodule path, so their local flow is
simply:

```sh
micropy-system/tools/build/build_firmware.py 1.0.1 pico2-w-rp2350
micropy-system/tools/target/serve_update.py
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
3. Build and assemble using the framework's helper:

   ```sh
   micropy-system/tools/build/build_firmware.py
   # Or select version and board explicitly:
   micropy-system/tools/build/build_firmware.py 1.2.3 pico2-w-rp2350
   ```

   This refreshes the bootstrap-only `device` tree and creates the A/B OTA
   archive plus `metadata.json` and `image-info.json` under `build`.
4. Keep the local server running in a separate terminal:

   ```sh
   micropy-system/tools/target/serve_update.py 8000
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
vendor/micropy-system/tools/micropy-wiring/init_project.py
```

The initializer never overwrites existing files. It creates an application
overlay, configuration template, editor settings, ignore rules, and an
application-owned GitHub Actions release workflow. It does not generate project
tools: all helpers are invoked through the submodule path. Pass an explicit
project path when running the initializer outside a submodule checkout.

Release asset metadata includes the model, compressed size, SHA-256,
MicroPython runtime version, and MPY format. The device validates these fields
before decompressing the update.

## Device tools

Host-side device tooling is owned by the framework under `tools/`.
Projects do not ship their own tooling: the initializer generates no project
tools, and each helper is invoked from the project through the submodule path
(e.g. `./micropy-system/tools/target/deploy.py`). A project refreshes its framework
checkout with `tools/micropy-wiring/update_framework.py` and then commits the pointer.

Every tool resolves the project root the same way: `--app-root` flag,
then `$MICROPY_APP_ROOT`, then the git superproject, then the CWD — so they
work from the project, the submodule, or anywhere else.

Every tool is a Python entry point under `tools/` (executable, with a
`#!/usr/bin/env python3` shebang) — run it directly or via `python3`.
The tools support macOS and Linux. USB discovery uses
pyserial plus `/dev/cu.usb*`, `/dev/ttyACM*`, and `/dev/ttyUSB*`; BOOTSEL media
is found under `/Volumes`, `/media`, `/run/media`, or `/mnt`. On Linux,
`udisksctl` is used to mount an unmounted BOOTSEL volume when available.

Linux users must have serial access (commonly membership in `dialout`) and
permission to mount removable media. On a headless system without `udisksctl`,
mount the `RPI-RP2`/`RP2350` volume manually before provisioning.

### The device shell (on-device service)

Once Wi-Fi is up, a device runs the framework's `lib/coresys/telnet_service.py`
— a single telnet-style line command server on the standard telnet port
(23). It replaces any per-app HTTP status/log/reboot/console services:

- **Built-in commands**: `status` (one-line JSON: version, slot, uptime,
  heap, wifi), `log [N]`, `heap`, `reboot` (ack, then `machine.reset()` —
  the boot-time OTA check then installs any served update), and `help`.
  The unrestricted `repl` command is disabled by default; an application must
  explicitly pass `allow_repl=True` to `TelnetService` to expose it.
- **Authentication**: pass `auth_token=...` to `TelnetService` to require
  `auth TOKEN` before every connection can issue commands. Set the same value
  in `MICROPY_SHELL_TOKEN` when using `tools/target/telnet.py` or `tools/target/net.py`.
  Omitting `auth_token` preserves an unauthenticated diagnostic shell.
- **App commands**: `shell.add("selftest", handler)` etc. from the app's
  `main()`.
- **Protocol**: plain lines; every answer ends with `<<<END>>>\n`; one
  client at a time. Stock `telnet 10.9.30.76` / `nc 10.9.30.76 23` work,
  as does `tools/target/telnet.py` (one-shot or interactive) and `tools/target/net.py`.

**Device lifecycle**

| Tool | Purpose |
| --- | --- |
| `tools/target/device.py` | USB CLI: `state`, `log`, `monitor`, `files`, `selftest` (app hook), `probe` (app hook), `exec`, `reset` |
| `tools/target/telnet.py` | Device-shell client: one-shot `HOST [PORT] CMD ...` or interactive `HOST [PORT]`; default port 23 |
| `tools/target/discover.py` | LAN scanner for the device shell port (default 23); `--host` works cross-subnet when routed |
| `tools/target/net.py` | Shell client for the device shell: `status`, `log`, `selftest`, `reboot`, `console`, `discover` |
| `tools/target/render_config.py` | Resolve `system-config.json`: Wi-Fi overrides + OTA source from `update-source.json` |
| `tools/target/provision.py` | Full blank/corrupt-board provisioning engine (UF2 flash, LFS format, tree upload, passive boot/DHCP capture, final reset) |
| `tools/build/assemble.py` | Assemble the `device/` A/B tree |

**Build, release, and deploy**

| Tool | Purpose |
| --- | --- |
| `tools/build/setup_build_env.py` | Create/refresh the project `.venv` from `requirements-dev.txt` |
| `tools/build/build_firmware.py` | `[VERSION] [MODEL]` → assemble + compile + package the OTA update into `build/` |
| `tools/target/serve_update.py` | `[PORT]` → serve `build/` for direct-server OTA (`firmware_server.py`) |
| `tools/micropy-wiring/release_github.py` | `MAJOR.MINOR.PATCH` → tag + push; the project's CI builds the GitHub release |
| `tools/target/deploy.py` | End-to-end: bump version → build → serve → OTA over Wi-Fi → wait for A/B promotion → self-test (`--usb` legacy path available) |

**Framework maintenance and debug**

| Tool | Purpose |
| --- | --- |
| `tools/micropy-wiring/update_framework.py` | Update the framework's own submodule checkout in the consuming project (fetch + ff-merge); the project then commits the pointer |
| `tools/target/capture_boot.py` | Capture serial output across a board reset (DTR/RTS toggle) to inspect the reset cause / crash |

`mpremote` and `pyserial` come from `requirements-dev.txt` (installed by
`tools/build/setup_build_env.py`). The provisioning engine expects the app to log a
main-loop marker over serial (default: `entering main loop`, configurable with
`--boot-marker`).

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License.

## Acknowledgements

- MicroPython project for providing the foundation
- Asyncio library for MicroPython enabling non-blocking operations


## everyday commands
./micropy-system/tools/build/setup_build_env.py
./micropy-system/tools/build/build_firmware.py
OTC_IP=10.9.30.76 ./micropy-system/tools/target/deploy.py
python micropy-system/tools/target/device.py --app-root . --name otc selftest
./micropy-system/tools/micropy-wiring/update_framework.py
.venv/bin/python micropy-system/tools/target/capture_boot.py