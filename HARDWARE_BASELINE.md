# Hardware and Runtime Baseline

This project currently targets a Raspberry Pi Pico W running MicroPython. OTA reliability depends on the exact MicroPython build, `.mpy` ABI, filesystem capacity, and LittleFS rename behavior, so these values must be measured on the deployed board.

## Supported Toolchain

- Device runtime target: MicroPython 1.29.0 for both Raspberry Pi Pico W
  (RP2040) and Raspberry Pi Pico 2 W (RP2350).
- Host compiler: `mpy-cross==1.29.0.post2` from `requirements.txt`.
- Device management: `mpremote==1.29.0` from `requirements-dev.txt`.
- Editor stubs: separate MicroPython 1.29 profiles are pinned for Pico W and
  Pico 2 W because board-specific modules and constants can differ.
- `.mpy` compatibility rule: build release bytecode with the `mpy-cross` release matching the device's MicroPython release, then compare the device-reported MPY version before enabling installation.

The MicroPython release number alone is not the final compatibility check. The diagnostic records `sys.implementation._mpy`, including its raw value, MPY version, sub-version, and architecture identifier. Provision devices with MicroPython 1.29.0 before deploying `.mpy` bundles produced by this toolchain.

## Capturing a Baseline

### Using `mpremote` (recommended)

Install host tools:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

The project-local `.venv` is ignored by Git. Either use the explicit executable
paths shown below or activate it for the current shell with:

```sh
source .venv/bin/activate
```

Verify the tools with:

```sh
.venv/bin/mpy-cross --version
.venv/bin/mpremote --version
```

Install both editor-stub profiles, then select the board being edited/tested:

```sh
.venv/bin/python tools/select_stubs.py pico-w
.venv/bin/python tools/select_stubs.py pico2-w
```

Each command installs its profile when needed and points the ignored
`.micropython-stubs` path at the selected profile. `pyrightconfig.json` tells
Pylance to use that path. Only one board profile is active at a time to avoid
ambiguous duplicate definitions. Reload the VS Code window after switching if
Pylance does not refresh automatically.

Connect the Pico W over USB and run:

```sh
.venv/bin/python tools/capture_baseline.py
```

If automatic serial discovery fails:

```sh
.venv/bin/python tools/capture_baseline.py --port /dev/cu.usbmodem1101
```

The command executes `tools/device_baseline.py` from RAM through `mpremote`; it does not install that script on the board. Rename tests are confined to `/__baseline_test`, which is removed after each case. The resulting `hardware-baseline.json` is local machine/device evidence and is intentionally ignored by Git.

### Using the VS Code MicroPico extension

MicroPico can run `tools/device_baseline.py` on a connected Pico through the
**MicroPico: Run current file on Pico** command. Copy the JSON printed between
the `MICROPY_SYSTEM_BASELINE_BEGIN` and `MICROPY_SYSTEM_BASELINE_END` markers
into `hardware-baseline.json`, then format it as JSON.

MicroPico does not bundle or install the host `mpremote` and `mpy-cross`
executables used by this repository. Its package manager installs MicroPython
packages on a connected Pico W and does not replace the pinned host development
requirements.

The currently installed MicroPico extension bundles Pico 2 W MicroPython 1.26.0
stubs. The project-local 1.29 profiles supersede those bundled definitions for
project analysis. Stubs still affect editor completion only; provision each
physical board with MicroPython 1.29.0 before installing compiled releases.

## Deployed-Board Record

The first captured target is a fresh Pico 2 W. The ignored raw machine report
is stored locally in `hardware-baseline.json`.

| Property | Measured value |
|---|---|
| Board model | Raspberry Pi Pico 2 W with RP2350 |
| Firmware board build | `RPI_PICO2_W` |
| Board revision | Not exposed by the runtime; record from board markings if needed |
| Physical flash | 4 MiB nominal Pico 2 W board flash; mounted MicroPython filesystem is smaller |
| MicroPython release | 1.29.0 |
| MicroPython build | `v1.29.0 on 2026-08-24 (GNU 16.1.0 MinSizeRel)` |
| `sys.platform` | `rp2` |
| Raw `sys.implementation._mpy` | 7942 |
| MPY version/sub-version | 6.3 |
| MPY architecture ID | 7 |
| Filesystem type | LittleFS2 expected from the standard RP2 firmware; API does not expose its name |
| Filesystem block size | 4096 bytes |
| Filesystem total bytes | 2,621,440 bytes (2.5 MiB) |
| Filesystem free bytes, clean deployment | 2,613,248 bytes |
| Heap free after GC at baseline | 436,192 bytes |
| Heap free after rename tests | 436,032 bytes |
| CPU frequency | 150 MHz |
| Current deployed application bytes | Pending deployment measurement |
| Minimum heap during normal boot | Pending instrumented boot measurement |

Do not infer physical flash size from `statvfs('/')`: it reports the mounted filesystem capacity, not necessarily the complete flash chip.

## Rename Semantics

Record the outcome from `hardware-baseline.json`:

| Operation | Expected installer policy | Pico result |
|---|---|---|
| File over existing file | Supported on measured LittleFS | Success |
| File over existing directory | Handle explicitly | `OSError(21)` (`EISDIR`) |
| Directory over existing file | Handle explicitly | `OSError(20)` (`ENOTDIR`) |
| Directory over empty directory | Supported on measured LittleFS | Success |
| Directory over non-empty directory | Handle explicitly | `OSError(39)` (`ENOTEMPTY`) |

Regardless of measured behavior, the A/B installer should avoid rename-over-type-change operations. It should recreate an empty inactive slot, populate it completely, and atomically change only the small slot-state record.

## Flash Sizing Procedure

Measure these quantities in bytes:

- `F_total`: total mounted filesystem capacity;
- `F_free_clean`: free bytes on a normally provisioned board;
- `S_active`: active application slot size;
- `S_candidate`: uncompressed candidate slot size;
- `S_archive`: compressed staging artifact size;
- `S_state`: OTA state, temporary state, logs, and safety reserve;
- `S_growth`: expected persistent-data growth during installation.

For the transitional in-place updater, peak space is approximately:

```text
S_archive + S_tar + S_extracted + S_backup + S_state + S_growth
```

For streaming A/B installation, the target peak is approximately:

```text
S_active + S_candidate + S_archive + S_state + S_growth
```

Before erasing or writing an inactive slot, require:

```text
F_free_current >= S_candidate + S_archive_remaining + S_state + S_growth + safety_margin
```

Start with a safety margin of the larger of 64 KiB or 10% of filesystem capacity, then revise it using hardware fault-test measurements. The current source tree is not a valid candidate-size estimate because host `.py`, `.mpy`, packaging, and filesystem block allocation differ.

## Boot Memory Baseline

The standalone diagnostic records idle heap after garbage collection. Peak boot memory must additionally be instrumented at these checkpoints:

1. start of root launcher;
2. after configuration parsing;
3. before and after Wi-Fi initialization;
4. before and after TLS connection establishment;
5. after metadata parsing;
6. during archive extraction;
7. before and after candidate application startup.

Record the minimum `gc.mem_free()` observed rather than only the initial value. This instrumentation belongs in a later OTA milestone because the present code does not yet expose one centralized metrics collector.

## Milestone 0 Exit Conditions

The Pico 2 W runtime, MPY ABI, filesystem capacity, idle heap, and rename
semantics are now captured. The host compiler emits MPY v6.3, matching the
device. Deployment-size and peak-boot-heap measurements remain part of the
application integration work. A corresponding Pico W/RP2040 baseline should be
captured when that board is available.
