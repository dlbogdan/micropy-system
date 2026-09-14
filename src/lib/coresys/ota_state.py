import ujson
import uos


SCHEMA_VERSION = 1
SLOTS = ("a", "b")
STATE_PATH = "/ota-state.json"
BACKUP_PATH = "/ota-state.bak"
NEW_PATH = "/ota-state.new"


def default_state():
    return {
        "schema": SCHEMA_VERSION,
        "generation": 0,
        "active": "a",
        "pending": None,
        "previous": None,
        "candidate_version": None,
        "candidate_attempts": 0,
        "rejected_version": None,
    }


def validate_state(value):
    """Return a detached valid state or raise ValueError."""
    if not isinstance(value, dict):
        raise ValueError("OTA state must be an object")
    required = set(default_state().keys())
    if set(value.keys()) != required:
        raise ValueError("OTA state fields do not match schema")
    if value["schema"] != SCHEMA_VERSION:
        raise ValueError("Unsupported OTA state schema")
    if not isinstance(value["generation"], int) or value["generation"] < 0:
        raise ValueError("Invalid OTA state generation")
    if value["active"] not in SLOTS:
        raise ValueError("Invalid active slot")
    pending = value["pending"]
    previous = value["previous"]
    if pending is not None and pending not in SLOTS:
        raise ValueError("Invalid pending slot")
    if previous is not None and previous not in SLOTS:
        raise ValueError("Invalid previous slot")
    if pending is None:
        if previous is not None or value["candidate_version"] is not None:
            raise ValueError("Candidate fields require a pending slot")
    elif pending == value["active"] or previous != value["active"]:
        raise ValueError("Pending state must preserve the active slot as previous")
    attempts = value["candidate_attempts"]
    if not isinstance(attempts, int) or attempts < 0:
        raise ValueError("Invalid candidate attempt count")
    if pending is None and attempts != 0:
        raise ValueError("Candidate attempts require a pending slot")
    for key in ("candidate_version", "rejected_version"):
        if value[key] is not None and not isinstance(value[key], str):
            raise ValueError("Invalid %s" % key)
    return dict(value)


def _read_record(path):
    try:
        with open(path, "r") as state_file:
            return validate_state(ujson.load(state_file))
    except (OSError, ValueError, TypeError):
        return None


def load_state(state_path=STATE_PATH, backup_path=BACKUP_PATH):
    """Select the newest valid generation, or deterministic defaults."""
    records = []
    for path in (state_path, backup_path):
        record = _read_record(path)
        if record is not None:
            records.append(record)
    if not records:
        return default_state()
    records.sort(key=lambda state: state["generation"], reverse=True)
    return records[0]


def _remove_if_exists(path):
    try:
        uos.remove(path)
    except OSError as error:
        if not error.args or error.args[0] != 2:
            raise


def write_state(state, state_path=STATE_PATH, backup_path=BACKUP_PATH,
                new_path=NEW_PATH):
    """Atomically publish state while retaining the prior valid generation."""
    state = validate_state(state)
    current = load_state(state_path, backup_path)
    state["generation"] = max(
        state["generation"], current["generation"] + 1)
    _remove_if_exists(new_path)
    with open(new_path, "w") as state_file:
        ujson.dump(state, state_file)
        state_file.flush()
    # Validate the closed temporary record before replacing either durable copy.
    if _read_record(new_path) is None:
        _remove_if_exists(new_path)
        raise ValueError("Temporary OTA state failed validation")
    _remove_if_exists(backup_path)
    try:
        uos.rename(state_path, backup_path)
    except OSError as error:
        if not error.args or error.args[0] != 2:
            raise
    uos.rename(new_path, state_path)
    return state
