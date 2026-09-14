import sys

from lib.coresys.ota_state import load_state, write_state


MAX_CANDIDATE_ATTEMPTS = 1


def slot_path(slot):
    if slot not in ("a", "b"):
        raise ValueError("Invalid application slot")
    return "/apps/" + slot


def rollback_candidate(state=None):
    """Atomically abandon a candidate and retain its version quarantine."""
    state = dict(state or load_state())
    if state["pending"] is None:
        return state
    failed_version = state["candidate_version"]
    state.update({
        "active": state["previous"],
        "pending": None,
        "previous": None,
        "candidate_version": None,
        "candidate_attempts": 0,
        "rejected_version": failed_version,
    })
    return write_state(state)


def prepare_slot_boot():
    """Select a slot and durably count a candidate attempt before import."""
    state = load_state()
    if (state["pending"] is not None and
            state["candidate_attempts"] >= MAX_CANDIDATE_ATTEMPTS):
        state = rollback_candidate(state)
    if state["pending"] is not None:
        state["candidate_attempts"] += 1
        state = write_state(state)
        return state["pending"], True, state
    return state["active"], False, state


def confirm_running_slot(slot, version_path='/version.txt'):
    """Promote the currently running candidate after application health checks."""
    state = load_state()
    if state["pending"] is None:
        if slot != state["active"]:
            raise ValueError("Cannot confirm an inactive slot")
        return state
    if slot != state["pending"]:
        raise ValueError("Only the pending slot can be confirmed")
    candidate_version = state["candidate_version"]
    state.update({
        "active": slot,
        "pending": None,
        "previous": None,
        "candidate_version": None,
        "candidate_attempts": 0,
        "rejected_version": None,
    })
    state = write_state(state)
    if candidate_version:
        with open(version_path, 'w') as version_file:
            version_file.write(candidate_version)
    return state


def activate_slot_path(slot):
    """Put exactly one selected slot first on the module search path."""
    selected = slot_path(slot)
    sys.path[:] = [
        path for path in sys.path
        if path not in (slot_path("a"), slot_path("b"))
    ]
    sys.path.insert(0, selected)
    return selected
