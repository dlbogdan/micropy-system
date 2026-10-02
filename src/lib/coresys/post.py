"""Framework power-on self-test (POST) harness + boot context.

Runs a set of local, fast health checks on every boot, BEFORE a guest
application is allowed to confirm an A/B candidate (see ``slot_main.py``).
The harness is guest-agnostic:

* it always runs a small set of framework checks (free heap), and
* it optionally calls the guest entry module's ``post_checks()`` for
  domain-specific checks.

``post_checks()`` (on ``app_entry``) is an OPTIONAL hook returning a list of
``(name, ok, detail)`` tuples. A guest that defines none still gets the
framework checks and the full A/B confirm/rollback protection; a guest that
defines some adds them to the gate. Any exception raised by a guest check is
captured as a FAIL for that check, not propagated -- a broken check must not
crash the boot.

The result and the candidate/active context are recorded so the guest can
query them (``is_candidate_boot`` / ``is_degraded``) and hold
non-idempotent physical actuation while a supervised candidate is confirming
or while the active slot is running degraded. See ``state``/app contracts and
``slot_main.py`` for the full A/B safety flow.

Checks must stay local and fast (no network I/O, no blocking waits) so the
whole POST stays comfortably inside the A/B candidate confirmation window.
"""

import gc

import lib.coresys.logger as logger

# Below this free heap the slot is considered bloated/corrupt.
DEFAULT_MIN_HEAP_FREE = 128 * 1024


class PostResult(object):
    """Collects ``(name, ok, detail)`` checks and a final verdict."""

    def __init__(self):
        self.checks = []

    def add(self, name, ok, detail=""):
        self.checks.append((name, bool(ok), detail))
        return bool(ok)

    @property
    def ok(self):
        return all(ok for (_name, ok, _detail) in self.checks)

    @property
    def count(self):
        return len(self.checks)

    def summary(self):
        parts = []
        for name, ok, detail in self.checks:
            if ok:
                parts.append(name)
            else:
                parts.append(name + " (FAIL" + (" " + detail + ")" if detail
                                              else ")"))
        return "; ".join(parts)


def check_heap(min_free=DEFAULT_MIN_HEAP_FREE):
    """Free-heap check: a bloated/corrupt slot trips this. Returns a tuple."""
    free = gc.mem_free()
    ok = free >= min_free
    return ("heap", ok,
            "" if ok else "%d B free (< %d)" % (free, min_free))


def _run_guest_checks(result, app_entry):
    """Invoke the optional ``app_entry.post_checks()`` hook, if present."""
    if app_entry is None or not hasattr(app_entry, "post_checks"):
        return
    try:
        entries = app_entry.post_checks()
    except Exception as e:
        result.add("guest-post", False, "post_checks() raised: %s" % e)
        return
    for entry in entries:
        try:
            name, ok = entry[0], entry[1]
            detail = entry[2] if len(entry) > 2 else ""
        except (TypeError, IndexError):
            result.add("guest-post", False, "malformed check: %r" % (entry,))
            continue
        result.add(name, ok, detail)


def run_post(app_entry=None, min_heap_free=DEFAULT_MIN_HEAP_FREE):
    """Run framework + guest POST checks and return a :class:`PostResult`."""
    result = PostResult()
    result.add(*check_heap(min_heap_free))
    _run_guest_checks(result, app_entry)
    logger.info(
        "POST: %s (%d checks) -- %s" % (
            "PASS" if result.ok else "FAIL", result.count, result.summary()),
        log_to_file=True)
    return result


# --- Boot context: set by the launcher, queried by the guest --------------
# Runtime-only (never persisted). Populated once per boot by ``slot_main.py``
# after the POST runs, so a guest can hold actuation accordingly.
_context = {"is_candidate": False, "result": None}


def set_boot_context(is_candidate, result):
    """Record this boot's candidate/active status and POST result."""
    _context["is_candidate"] = bool(is_candidate)
    _context["result"] = result


def is_candidate_boot():
    """True on the supervised candidate boot that follows an OTA apply."""
    return _context["is_candidate"]


def result():
    """The :class:`PostResult` for this boot (or None before it runs)."""
    return _context["result"]


def is_degraded():
    """True when the POST failed (active slot running in degraded mode)."""
    res = _context["result"]
    return res is not None and not res.ok
