# MicroPython System Reliability Roadmap

## 1. Purpose

This document is the implementation plan for turning the current Raspberry Pi Pico W OTA prototype into a reliable personal-device update system.

The priorities are:

1. make the existing automatic pull updater function predictably;
2. remove boot loops and ambiguous update state;
3. introduce application-level A/B slots with health confirmation and rollback;
4. simplify boot, configuration, networking, packaging, and task ownership;
5. validate failure behavior on real Pico W hardware.

Broader security hardening is intentionally deferred. Low-cost safety measures that also improve reliability—fixed paths, strict manifests, bounded files, and complete checksums—remain in scope.

## 2. Current Architecture and Decision

The current system uses automatic pull-based OTA updates. It supports two release transports:

- GitHub Releases API;
- a direct HTTPS server that returns GitHub-shaped `metadata.json`.

Both transports are intended to produce the same `firmware.tar.zlib` artifact and feed the same installer.

The manual browser-upload server from the older `ota-updater` project is not part of this project. It can be reconsidered later as another delivery transport, but it must not have a separate installation implementation.

The target architecture is:

```text
GitHub Releases ──────┐
                     ├── release metadata ── artifact download
Direct test server ──┘                         │
                                              ▼
                                     verified staging file
                                              │
                                              ▼
                                    inactive application slot
                                              │
                                              ▼
                                  pending slot + reboot attempt
                                              │
                           ┌──────────────────┴──────────────────┐
                           ▼                                     ▼
                    app confirms health                 app fails/hangs/resets
                           │                                     │
                           ▼                                     ▼
                    promote candidate                    return to old slot
```

## 3. Guiding Invariants

All implementation work should preserve these invariants:

1. The active application slot is never modified by a normal OTA installation.
2. The root boot selector is not replaced by normal application releases.
3. An artifact is not installed until its exact byte count and archive checksum have been verified.
4. A candidate is not considered active until the application explicitly confirms healthy startup.
5. Power loss at any update stage leaves either the previous slot bootable or a deterministic recovery choice.
6. Every persistent state transition is written through a temporary file and atomic rename.
7. Normal lack of network connectivity is not treated as a broken firmware release.
8. Update checking occurs in one lifecycle location, not independently in both `boot.py` and `main.py`.
9. Every archived regular file is declared exactly once in the integrity manifest, and every manifest entry is present exactly once.
10. Installer resource requirements are checked before destructive work starts.

## 4. Delivery Milestones

### Milestone 0 — Establish a Hardware Baseline

Before changing update semantics, record the exact target environment.

#### Tasks

- [x] Record Pico 2 W model, standard-board flash specification, and mounted filesystem capacity. Pico W/RP2040 capture remains pending until that target is available.
- [x] Record the exact Pico 2 W MicroPython version and build identifier.
- [x] Record the Pico 2 W `.mpy` ABI/version and verify that host `mpy-cross` emits matching MPY v6.3.
- [x] Test `uos.rename()` behavior on the Pico 2 W standard firmware filesystem:
  - file over existing file;
  - file over directory;
  - directory over file;
  - directory over empty directory;
  - directory over non-empty directory.
- [x] Capture `uos.statvfs('/')` values on a clean provisioned Pico 2 W.
- [ ] Capture current deployed application size and peak free heap during application boot. Clean-board free flash and idle heap are captured.
- [x] Add a short hardware compatibility section to the README.
- [x] Add a repeatable `mpremote` baseline capture command and on-device rename test.
- [x] Document the MicroPico-based manual capture alternative and distinguish editor stubs/device packages from the host release toolchain.
- [x] Pin project-local `mpy-cross` and `mpremote` 1.29.0 tooling for the selected runtime baseline.
- [x] Add independently installable Pico W and Pico 2 W MicroPython 1.29 editor-stub profiles.
- [x] Document flash-sizing formulas, safety-margin policy, and hardware-dependent exit conditions.

#### Acceptance criteria

- The supported MicroPython and `mpy-cross` versions are explicit.
- Rename assumptions are based on an actual Pico test rather than CPython behavior.
- A minimum free-flash requirement can be calculated from real measurements.

---

### Milestone 1 — Repair the Existing Pull OTA Pipeline

This milestone makes the current in-place architecture usable before introducing A/B slots. Keep the scope narrow and observable.

#### 1.1 Fix direct runtime blockers

- [x] Fix the extra `firmware_filename` argument passed to `_download_firmware()`.
- [x] Add an integration test that reaches artifact verification, so this mismatch cannot recur.
- [x] Delete partial `/update.tar.zlib` before a new download.
- [x] On download failure, close streams and remove the partial artifact.
- [x] Treat an early EOF as an error when fewer bytes than `Content-Length` were received.
- [x] Treat malformed or unsupported length/transfer metadata deterministically; body reads are bounded to the declared length.
- [x] Add configurable connect, header-read, and body-read timeouts instead of applying one short timeout only to connection establishment.

#### 1.2 Verify the complete downloaded artifact

Define one normalized release model inside the device:

```json
{
  "version": "1.2.3",
  "url": "https://example/firmware.tar.zlib",
  "size": 123456,
  "sha256": "hex digest",
  "model": "pico-w"
}
```

- [x] Add artifact `size`, `sha256`, and device `model` to release metadata.
- [x] Parse GitHub and direct-server GitHub-shaped responses into this internal model.
- [x] Compare the computed archive hash against metadata before decompression.
- [x] Compare received byte count against expected metadata size and HTTP length.
- [x] Normalize SHA-256 values to lowercase strings; do not mix `bytes` and `str` representations.
- [x] Reject a release for a different model, runtime version, or MPY format.
- [x] Preserve the verified release version in persistent update state when applying starts.

#### 1.3 Correct retry accounting

Replace the current boot-check counter with release-specific state.

- [x] Do not increment failure counters merely because the device checked for updates.
- [x] Do not count offline boot, DNS failure, TLS failure, metadata-server outage, or download failure as an apply failure.
- [x] Track download diagnostics separately from installation and candidate-boot failures.
- [x] Associate apply counters with a version so a new release is not blocked by failures from an old release.
- [x] Persist a quarantine/rejected version when maximum apply attempts are reached.
- [x] Permit a newer release even if the previous release was rejected.
- [x] Add an explicit method to clear a rejected release during development.

#### 1.4 Correct boot orchestration

- [x] Make `boot.py` the sole owner of automatic update checks during the transitional architecture.
- [x] Remove the duplicate update check from `main.py`.
- [x] Ensure `boot.py` tears down update networking before normal application startup.
- [x] Avoid creating unrelated `asyncio.run()` loops for setup and shutdown; one boot coroutine owns the lifecycle.
- [x] Apply `NETWORK_TIMEOUT_MS` to Wi-Fi establishment and per-operation `REQUEST_TIMEOUT_MS` to update HTTP operations.
- [x] Define timeout behavior as “continue into the installed application,” not reset or count a firmware failure.
- [x] Make boot exceptions return through bounded cleanup rather than creating a boot reset loop.

#### 1.5 Repair current backup behavior

This is transitional and will be retired after A/B slots are proven.

- [x] Clear a previous temporary backup and rotate the valid backup to an old directory during promotion.
- [x] Build the new backup under `/backup.new`.
- [x] Promote `/backup.new` only after every copy succeeds.
- [x] Preserve the previous valid backup until the new one is complete and restore it if promotion fails.
- [x] Exclude update staging, logs, state files, and volatile data explicitly.
- [x] Check logical source bytes against free space before backup.
- [x] Abort before creating `/__applying` if backup is incomplete.
- [x] Handle file/directory type changes explicitly rather than relying on rename-overwrite behavior.
- [x] Document that deletions are unsupported during this milestone; stale paths remain until A/B slot replacement supersedes root merge.

#### Acceptance criteria

- A newer local release downloads and installs on real hardware.
- A truncated download is rejected and removed.
- An incorrect archive checksum is rejected before decompression.
- Three offline boots do not disable updates or modify candidate-failure state.
- A power cut during in-place replacement causes deterministic backup restoration on the next boot.
- The device does not perform a second update check immediately after boot enters `main.py`.

---

### Milestone 2 — Define and Harden the Release Format

#### 2.1 Consolidate builders

- [x] Select `local_builder.py` as the canonical implementation or extract shared build functions into one module.
- [x] Make `prepare_release.py` call the shared builder or remove it.
- [x] Provide output adapters for local direct-server files and GitHub release assets.
- [x] Create output directories explicitly and fail with a concise diagnostic.
- [x] Stream TAR compression on the desktop instead of loading both TAR and compressed image fully into memory.

#### 2.2 Pin `.mpy` compatibility

- [ ] Pin/document the exact `mpy-cross` version matching the supported MicroPython firmware.
- [ ] Record the MicroPython/MPY ABI in release metadata.
- [ ] Reject an incompatible release before installation.
- [x] Provide a build option that packages `.py` instead of `.mpy` for debugging compatibility issues.
- [x] Never package both `.py` and `.mpy` for the same module unless precedence is intentional and tested.

#### 2.3 Make the TAR contract strict

Define the archive as application-relative paths only. For the transitional installer these may map to root; for A/B they map to the inactive slot.

- [ ] Require `integrity.json` as the first regular entry, or implement a full second verification pass.
- [ ] Require every regular file to have exactly one manifest hash.
- [ ] Reject manifest entries that do not correspond to an archived file.
- [ ] Reject duplicate paths.
- [ ] Reject absolute paths, parent traversal, empty normalized paths, excessive path depth, and excessive path length.
- [ ] Reject unsupported TAR entry types.
- [ ] Validate complete 512-byte TAR headers and file bodies.
- [ ] Validate TAR header checksums.
- [ ] Add limits for total uncompressed bytes, individual file size, and file count.
- [ ] Close TAR and decompression streams on all outcomes.

#### 2.4 Represent file deletion

- [ ] For the transitional root-merge installer, add an explicit deletion list to the manifest.
- [ ] Validate deletion paths with the same strict normalization as archived files.
- [ ] Apply deletions only after backup and applying-state persistence.
- [ ] Remove the deletion mechanism when normal application updates exclusively replace inactive slots, except for explicitly managed persistent data migrations.

#### Acceptance criteria

- The host builder validates its own artifact before publishing it.
- The Pico rejects missing, extra, duplicate, truncated, oversized, and hash-mismatched files.
- The Pico rejects incompatible `.mpy` releases before modifying the active installation.
- Nested application paths are preserved exactly.

---

### Milestone 3 — Introduce Stable Application A/B Slots

#### 3.1 Target filesystem layout

```text
/boot.py
/main.py
/system-config.json
/ota-state.json
/apps/a/app_entry.py
/apps/a/...
/apps/b/app_entry.py
/apps/b/...
/staging/firmware.tar.zlib
```

The root `boot.py`, root `main.py`, OTA state reader/writer, and minimum recovery code are stable infrastructure. Normal releases contain only slot application files.

#### 3.2 Define atomic state

Use a small schema such as:

```json
{
  "schema": 1,
  "generation": 12,
  "active": "a",
  "pending": "b",
  "previous": "a",
  "candidate_version": "1.2.3",
  "candidate_attempts": 0,
  "rejected_version": null
}
```

- [ ] Implement a dedicated OTA state module with validation and defaults.
- [ ] Write `ota-state.new`, close it, and rename it over the live state.
- [ ] Keep `ota-state.bak` or two generation-numbered records for recovery from a torn state write.
- [ ] Define deterministic fallback when both state records are invalid.
- [ ] Never infer active slot solely from directory existence.

#### 3.3 Create the stable launcher

- [ ] Keep root `boot.py` small: hardware/bootstrap setup only.
- [ ] Keep root `main.py` small: choose a slot, adjust `sys.path`, import `app_entry`, and run it.
- [ ] Avoid importing the slot entry as `main` to prevent collision with the root launcher.
- [ ] Increment and persist candidate attempt count before importing a pending slot.
- [ ] Catch candidate import/startup exceptions and return to the previous slot.
- [ ] Record reset cause where supported to aid rollback diagnostics.
- [ ] Ensure a corrupt candidate cannot overwrite selector modules through ordinary releases.

#### 3.4 Install directly into the inactive slot

- [ ] Determine inactive slot from valid state.
- [ ] Check projected free-space needs before deleting the inactive slot.
- [ ] Remove and recreate only the inactive slot.
- [ ] Feed `deflate.DeflateIO` directly to `utarfile.TarFile(fileobj=...)`.
- [ ] Extract and verify into the inactive slot without creating `/update.tmp.tar` or `/update`.
- [ ] Require `app_entry.py` and any declared framework modules.
- [ ] Persist pending-slot state only after extraction and complete verification succeed.
- [ ] Retain the downloaded artifact until pending state is safely persisted; then remove it.
- [ ] Reboot only after every staging stream is closed and state is durable.

#### 3.5 Candidate health confirmation

- [ ] Expose a tiny `confirm_running_slot()` API to the application.
- [ ] Define minimum health as successful configuration load, manager creation, and stable event-loop operation for a short period.
- [ ] Do not require Internet connectivity for health confirmation.
- [ ] Confirm by atomically promoting `pending` to `active` and clearing candidate attempts.
- [ ] Preserve the old slot until confirmation succeeds.
- [ ] Log candidate version, attempt number, confirmation, and rollback.

#### 3.6 Rollback and watchdog

- [ ] Start with one candidate boot attempt before rollback.
- [ ] Roll back on uncaught candidate startup exception.
- [ ] Evaluate `machine.WDT` behavior on the exact MicroPython build.
- [ ] If watchdog is enabled, ensure the normal app has a centralized feed owner.
- [ ] Roll back an unconfirmed candidate after watchdog reset.
- [ ] Avoid treating intentional user resets after confirmation as failures.
- [ ] Quarantine a failed candidate version while allowing a newer release.

#### Acceptance criteria

- Power loss at every installation step leaves the previous active slot bootable.
- A candidate that raises during import rolls back automatically.
- A candidate that hangs before confirmation rolls back after watchdog reset.
- A healthy candidate confirms and becomes active.
- Loss of Wi-Fi during candidate startup does not cause rollback.
- Deleted and renamed application files do not survive from a previous release because the inactive slot starts empty.
- Normal OTA packages cannot replace the stable selector.

---

### Milestone 4 — Retire Full-Root Backup and In-Place Merge

Only begin this milestone after A/B fault tests pass consistently.

#### Tasks

- [ ] Remove `_backup_existing_files()` from the normal OTA path.
- [ ] Remove `_move_from_update_to_root()` and recursive root merge.
- [ ] Remove `/__applying` backup-restore semantics from ordinary application releases.
- [ ] Remove root restore code or retain it only as a manually invoked emergency tool.
- [ ] Remove deletion manifests for slot-local files.
- [ ] Update flash-space calculations for two slots plus one compressed staging artifact.
- [ ] Add an optional policy for deleting the old inactive slot only when space is needed for a future update.

#### Acceptance criteria

- The normal update path never recursively copies or replaces the live root application.
- Recovery consists of selecting the previous slot, not rewriting root from backup.
- Peak update flash use is measured and documented.

---

### Milestone 5 — System-Level Cleanup

#### 5.1 Configuration durability and write wear

- [ ] Define a complete in-memory default configuration tree.
- [ ] Merge defaults into loaded configuration once instead of saving once per missing key.
- [ ] Save configuration at most once during initial default population.
- [ ] Write configuration through `system-config.new` and atomic rename.
- [ ] Keep a last-known-good config or recover safely from invalid JSON.
- [ ] Validate types and ranges, including chunk size, timeouts, retry counts, repository format, and slot limits.
- [ ] Separate mutable runtime OTA state from user configuration.

#### 5.2 Remove problematic singleton behavior

- [ ] Decide whether `FirmwareUpdater`, `SystemManager`, `WiFiManager`, and task managers truly require singleton lifetime.
- [ ] Prefer explicit ownership and dependency injection where only one instance is naturally created.
- [ ] If a singleton remains, implement explicit `reconfigure()` semantics.
- [ ] Do not silently ignore changed constructor arguments after first initialization.
- [ ] Reset global instances cleanly between host tests.

#### 5.3 Clarify boot/main responsibilities

Target ownership:

- root `boot.py`: minimal hardware/bootstrap work;
- root `main.py`: slot selection and launch;
- slot `app_entry.py`: application and manager lifecycle;
- OTA background task or controlled pre-launch service: update check/download;
- OTA installer: inactive-slot installation and state transitions.

- [ ] Remove duplicate manager construction across boot and main.
- [ ] Ensure each event loop has one clear owner.
- [ ] Ensure shutdown runs in the same loop that created asynchronous resources.
- [ ] Replace unconditional reset-on-any-main-exception with candidate-aware rollback or bounded safe-mode behavior.
- [ ] Add exponential/backoff delay to repeated non-candidate application failures to avoid hot reboot loops.

#### 5.4 Networking resilience

- [ ] Distinguish connection timeout, DNS failure, TLS failure, HTTP status failure, header timeout, and body timeout in diagnostics.
- [ ] Make header matching case-insensitive.
- [ ] Support expected HTTP redirect codes and require a non-empty redirect location.
- [ ] Handle relative redirects or reject them clearly.
- [ ] Decide whether chunked transfer encoding is supported; reject it explicitly if not.
- [ ] Confirm GitHub API and asset hosts work with the target MicroPython TLS stack.
- [ ] Ensure connection writers close on cancellation and every exception path.
- [ ] Avoid holding all metadata indefinitely; enforce a small maximum metadata size.
- [ ] Keep normal application startup independent of Internet availability.

#### 5.5 Logging durability

- [ ] Bound `log.txt` size with rotation or truncation.
- [ ] Avoid logging per-chunk events to flash.
- [ ] Use concise state-transition records for update diagnostics.
- [ ] Include reset cause, active slot, pending slot, candidate version, and attempt count in boot logs.
- [ ] Ensure logging failures never prevent boot or rollback.
- [ ] Flush critical update state before reset; treat logs as secondary.

#### 5.6 Task management and watchdog ownership

- [ ] Review background task cancellation and exception propagation.
- [ ] Ensure failed tasks are reported rather than silently disappearing.
- [ ] Define one owner for the watchdog feed.
- [ ] Avoid long synchronous filesystem operations without cooperative yields.
- [ ] Avoid excessive `gc.collect()` inside every network chunk unless measurements show it is required.
- [ ] Record peak heap during metadata parsing, TLS setup, extraction, and application startup.

#### 5.7 Repository and documentation cleanup

- [ ] Update README terminology from “firmware” to “application bundle” where MicroPython itself is not being replaced.
- [ ] Document that GitHub and direct-server modes are transports for one installer.
- [ ] Document exact release metadata and archive schemas.
- [ ] Document device provisioning and initial slot creation.
- [ ] Document USB/manual recovery steps if both slots or OTA state are corrupt.
- [ ] Document how to clear a rejected candidate version.
- [ ] Remove or consolidate duplicate builder scripts.
- [ ] Keep generated `build/`, `release/`, certificates, logs, and caches ignored.

#### Acceptance criteria

- Configuration loss during a write recovers from a valid old or new record.
- Boot performs one update decision and creates one coherent manager lifecycle.
- Offline startup reaches the application within the configured bounded time.
- Repeated application errors do not produce an uncontrolled rapid reset loop.
- Logs remain bounded during long operation.

---

### Milestone 6 — Automated and Hardware Fault Testing

#### 6.1 Host-side tests

- [ ] Version parsing and comparison, including malformed versions.
- [ ] GitHub metadata normalization.
- [ ] Direct-server metadata normalization.
- [ ] Model, ABI, size, and hash rejection.
- [ ] OTA state serialization, generation selection, corruption, and recovery.
- [ ] Slot selection and candidate-attempt policy.
- [ ] Manifest completeness and duplicate detection.
- [ ] Path normalization and extraction limits.
- [ ] Builder self-validation.
- [ ] Retry and rejected-version state transitions.

Use compatibility fakes for `uos`, `machine`, `deflate`, networking, and filesystem fault injection rather than attempting to execute all hardware behavior directly under CPython.

#### 6.2 On-device integration tests

- [ ] Clean installation into slot A.
- [ ] Successful A-to-B update and confirmation.
- [ ] Successful B-to-A update and confirmation.
- [ ] Metadata unavailable.
- [ ] Wi-Fi unavailable.
- [ ] Connection lost during artifact download.
- [ ] Wrong `Content-Length`.
- [ ] Wrong archive SHA-256.
- [ ] Corrupt zlib data.
- [ ] Truncated TAR header and body.
- [ ] Missing required entry module.
- [ ] Missing, extra, and mismatched integrity entries.
- [ ] Filesystem full before and during extraction.
- [ ] Power removal during inactive-slot deletion.
- [ ] Power removal during extraction.
- [ ] Power removal immediately before and after pending-state persistence.
- [ ] Candidate import exception.
- [ ] Candidate runtime exception before confirmation.
- [ ] Candidate hang before confirmation.
- [ ] Reset immediately after confirmation.
- [ ] Corrupt primary OTA state with valid backup state.
- [ ] Corrupt both OTA state records.
- [ ] Incompatible `.mpy` artifact.

#### 6.3 Long-running tests

- [ ] Hundreds of boots without an update.
- [ ] Repeated offline/online transitions.
- [ ] Repeated alternating A/B updates.
- [ ] Log growth verification.
- [ ] Config and state write-wear observation.
- [ ] Heap and flash fragmentation observation.

#### Acceptance criteria

- Every injected failure has a documented deterministic outcome.
- No tested update failure makes USB reflashing necessary when the stable selector remains intact.
- A known-good slot remains bootable through all pre-confirmation failures.
- Automated host tests run in CI on every change.

## 5. Proposed Implementation Order

Implement in this exact sequence to avoid mixing architectural changes with basic bug fixes:

1. Hardware baseline and rename tests.
2. Fix `_download_firmware()` call mismatch.
3. Enforce complete downloads and clean partial files.
4. Normalize release metadata and verify archive size/hash/model.
5. Correct retry accounting.
6. Remove duplicate update check and clarify event-loop ownership.
7. Repair backup freshness and free-space checks for the transitional updater.
8. Consolidate the builder and pin `mpy-cross` compatibility.
9. Harden TAR and integrity validation.
10. Add host tests around metadata, state, and archives.
11. Introduce stable root selector and atomic OTA state.
12. Install into an inactive slot via streaming decompression.
13. Add candidate confirmation and exception rollback.
14. Add watchdog-based hang rollback after measuring watchdog behavior.
15. Run the complete hardware fault matrix.
16. Retire full-root backup, restore, and recursive root merge.
17. Complete configuration, logging, singleton, networking, and documentation cleanup.

## 6. Suggested Module Boundaries

The existing `manager_firmware.py` has too many responsibilities. Refactor incrementally toward:

```text
lib/coresys/ota/
    release.py       metadata normalization and version policy
    transport.py     HTTPS request and bounded download
    artifact.py      artifact size/hash verification
    archive.py       zlib/TAR extraction and manifest verification
    state.py         atomic slot and candidate state
    installer.py     inactive-slot preparation and installation
    launcher.py      slot choice, attempts, confirmation, rollback
```

Keep the public orchestration surface small:

```text
check_for_release()
download_release()
install_to_inactive_slot()
mark_candidate_pending()
select_boot_slot()
confirm_running_slot()
reject_pending_slot()
```

Avoid a singleton inside these low-level modules. Pass configuration, filesystem adapters, logger, and progress callbacks explicitly so they can be tested.

## 7. Deferred Work

The following items are intentionally outside the immediate reliability roadmap:

- cryptographic release signatures;
- certificate pinning;
- credential rotation and provisioning redesign;
- authenticated manual web uploads;
- updating the MicroPython runtime/UF2 itself;
- custom RP2040 flash partitions or native second-stage bootloaders.

The design should not prevent later signature verification. The normalized release model and artifact-verification boundary are the correct future insertion points.

## 8. Definition of Done

The reliability project is complete when:

- automatic updates work from both GitHub Releases and the local direct server;
- the same normalized release and installer logic is used for both transports;
- the currently active application is never modified during installation;
- every candidate requires explicit post-boot health confirmation;
- failed or hanging candidates automatically return to the previous slot;
- network outages do not consume candidate boot attempts;
- downloads and archives are completely size/hash/structure validated;
- state and configuration writes survive interruption;
- `.mpy` compatibility is enforced;
- peak flash and heap requirements are measured and documented;
- all defined host tests pass;
- all critical power-loss and watchdog scenarios pass repeatedly on a real Pico W;
- normal update failures do not require USB recovery.
