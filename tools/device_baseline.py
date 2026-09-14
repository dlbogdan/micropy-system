"""Collect a Pico/MicroPython reliability baseline.

Run this file on the device with mpremote. All filesystem mutations are
confined to BASE_DIR and are removed before the script exits.
"""

import gc
import machine
import sys
import ujson
import uos


BASE_DIR = "/__baseline_test"
REPORT_START = "=== MICROPY_SYSTEM_BASELINE_BEGIN ==="
REPORT_END = "=== MICROPY_SYSTEM_BASELINE_END ==="


def _path_exists(path):
    try:
        uos.stat(path)
        return True
    except OSError:
        return False


def _is_dir(path):
    try:
        return bool(uos.stat(path)[0] & 0x4000)
    except OSError:
        return False


def _remove_tree(path):
    if not _path_exists(path):
        return
    if not _is_dir(path):
        uos.remove(path)
        return

    for name in uos.listdir(path):
        _remove_tree(path.rstrip("/") + "/" + name)
    uos.rmdir(path)


def _write(path, content):
    with open(path, "w") as handle:
        handle.write(content)


def _read(path):
    with open(path, "r") as handle:
        return handle.read()


def _reset_case():
    _remove_tree(BASE_DIR)
    uos.mkdir(BASE_DIR)


def _record_rename(operation, setup, source, destination, verify):
    _reset_case()
    setup()
    result = {
        "operation": operation,
        "result": "unknown",
        "error": None,
    }
    try:
        uos.rename(source, destination)
        result["result"] = "success" if verify() else "unexpected_state"
    except OSError as exc:
        result["result"] = "error"
        result["error"] = repr(exc)
    finally:
        _remove_tree(BASE_DIR)
    return result


def _rename_tests():
    def file_over_file_setup():
        _write(BASE_DIR + "/source", "new")
        _write(BASE_DIR + "/destination", "old")

    def file_over_file_verify():
        return (
            not _path_exists(BASE_DIR + "/source")
            and _read(BASE_DIR + "/destination") == "new"
        )

    def file_over_dir_setup():
        _write(BASE_DIR + "/source", "new")
        uos.mkdir(BASE_DIR + "/destination")

    def file_over_dir_verify():
        return (
            not _path_exists(BASE_DIR + "/source")
            and not _is_dir(BASE_DIR + "/destination")
            and _read(BASE_DIR + "/destination") == "new"
        )

    def dir_over_file_setup():
        uos.mkdir(BASE_DIR + "/source")
        _write(BASE_DIR + "/source/marker", "new")
        _write(BASE_DIR + "/destination", "old")

    def dir_over_file_verify():
        return (
            not _path_exists(BASE_DIR + "/source")
            and _is_dir(BASE_DIR + "/destination")
            and _read(BASE_DIR + "/destination/marker") == "new"
        )

    def dir_over_empty_dir_setup():
        uos.mkdir(BASE_DIR + "/source")
        _write(BASE_DIR + "/source/marker", "new")
        uos.mkdir(BASE_DIR + "/destination")

    def dir_over_empty_dir_verify():
        return (
            not _path_exists(BASE_DIR + "/source")
            and _read(BASE_DIR + "/destination/marker") == "new"
        )

    def dir_over_nonempty_dir_setup():
        uos.mkdir(BASE_DIR + "/source")
        _write(BASE_DIR + "/source/new-marker", "new")
        uos.mkdir(BASE_DIR + "/destination")
        _write(BASE_DIR + "/destination/old-marker", "old")

    def dir_over_nonempty_dir_verify():
        return (
            not _path_exists(BASE_DIR + "/source")
            and _path_exists(BASE_DIR + "/destination/new-marker")
        )

    return [
        _record_rename(
            "file_over_existing_file",
            file_over_file_setup,
            BASE_DIR + "/source",
            BASE_DIR + "/destination",
            file_over_file_verify,
        ),
        _record_rename(
            "file_over_existing_directory",
            file_over_dir_setup,
            BASE_DIR + "/source",
            BASE_DIR + "/destination",
            file_over_dir_verify,
        ),
        _record_rename(
            "directory_over_existing_file",
            dir_over_file_setup,
            BASE_DIR + "/source",
            BASE_DIR + "/destination",
            dir_over_file_verify,
        ),
        _record_rename(
            "directory_over_empty_directory",
            dir_over_empty_dir_setup,
            BASE_DIR + "/source",
            BASE_DIR + "/destination",
            dir_over_empty_dir_verify,
        ),
        _record_rename(
            "directory_over_nonempty_directory",
            dir_over_nonempty_dir_setup,
            BASE_DIR + "/source",
            BASE_DIR + "/destination",
            dir_over_nonempty_dir_verify,
        ),
    ]


def _uname_dict():
    uname = uos.uname()
    fields = ("sysname", "nodename", "release", "version", "machine")
    result = {}
    for index, field in enumerate(fields):
        try:
            result[field] = uname[index]
        except Exception:
            result[field] = None
    return result


def _implementation_dict():
    implementation = sys.implementation
    version = implementation.version
    raw_mpy = getattr(implementation, "_mpy", None)
    result = {
        "name": implementation.name,
        "version": list(version),
        "build": getattr(implementation, "_build", None),
        "machine": getattr(implementation, "_machine", None),
        "thread": getattr(implementation, "_thread", None),
        "mpy_raw": raw_mpy,
        "mpy_version": None,
        "mpy_sub_version": None,
        "mpy_architecture_id": None,
    }
    if isinstance(raw_mpy, int):
        result["mpy_version"] = raw_mpy & 0xFF
        result["mpy_sub_version"] = (raw_mpy >> 8) & 0x03
        result["mpy_architecture_id"] = (raw_mpy >> 10) & 0x3F
    return result


def _filesystem_dict():
    stat = uos.statvfs("/")
    block_size = stat[0]
    return {
        "filesystem_type": "record_manually_if_not_reported_by_firmware",
        "block_size": block_size,
        "fragment_size": stat[1],
        "total_blocks": stat[2],
        "free_blocks": stat[3],
        "available_blocks": stat[4],
        "total_bytes": block_size * stat[2],
        "free_bytes": block_size * stat[3],
        "available_bytes": block_size * stat[4],
    }


def collect_baseline():
    gc.collect()
    unique_id = None
    try:
        import binascii
        unique_id = binascii.hexlify(machine.unique_id()).decode()
    except Exception:
        pass

    report = {
        "schema": 1,
        "platform": sys.platform,
        "implementation": _implementation_dict(),
        "uname": _uname_dict(),
        "machine": {
            "frequency_hz": machine.freq(),
            "reset_cause": machine.reset_cause(),
            "unique_id": unique_id,
            "board_revision": "record_manually_if_not_in_uname",
            "physical_flash_bytes": "record_from_board_specification",
        },
        "filesystem": _filesystem_dict(),
        "memory": {
            "free_heap_bytes_after_gc": gc.mem_free(),
            "allocated_heap_bytes": gc.mem_alloc(),
        },
        "rename_semantics": _rename_tests(),
    }
    gc.collect()
    report["memory"]["free_heap_bytes_after_tests"] = gc.mem_free()
    return report


def main():
    report = collect_baseline()
    print(REPORT_START)
    print(ujson.dumps(report))
    print(REPORT_END)


if __name__ == "__main__":
    main()
