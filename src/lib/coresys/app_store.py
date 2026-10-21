"""App store: the app-owned key/value JSON file, in the menu-store shape.

A device has two config files and they have different owners:

  /system-config.json  FRAMEWORK-owned. tools/target/render_config.py
      re-renders it at every provisioning, so a value written on the
      device does not survive the next flash. Read it through
      manager_config; write it only for settings the framework owns.
  /app-config.json     APP-owned. Values the user commits on the device
      (menu settings, calibration, thresholds). Survives provisioning.

The shape here (keys/load/save) is the one the UI engine's store protocol
consumes (uifw.menu.load_store / bind_store): the framework owns
persistence, the UI edits through it. ConfigSection is the same shape over
one section of a live ConfigManager, for framework-owned values the UI
merely displays or edits.

Writes follow manager_config.save_config's proven pattern: one open('w')
plus json.dump, no rename. HARDWARE_BASELINE.md: LittleFS rename
semantics differ from POSIX, and a store that never renames never meets
the caveat.
"""
import json


class AppStore:
    """keys/load/save over one JSON file. A missing or corrupt file
    starts empty: a seed is not a crash."""

    def __init__(self, path='/app-config.json'):
        self.path = path
        try:
            with open(path) as f:
                d = json.load(f)
            self.d = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            self.d = {}

    def keys(self):
        return list(self.d.keys())

    def load(self, iid):
        return self.d.get(iid)

    def save(self, iid, value):
        self.d[iid] = value
        with open(self.path, 'w') as f:
            json.dump(self.d, f)


class ConfigSection:
    """keys/load/save over ONE section of a manager_config instance
    (duck-typed: .config dict, .get(section, key), .set(section, key,
    value)). The framework keeps persistence and subscribers; the UI
    edits through the same keys."""

    def __init__(self, config_manager, section='UI'):
        self.cfg = config_manager
        self.section = section

    def _sec(self):
        s = getattr(self.cfg, 'config', {}).get(self.section)
        return s if isinstance(s, dict) else {}

    def keys(self):
        return list(self._sec().keys())

    def load(self, iid):
        return self._sec().get(iid)

    def save(self, iid, value):
        self.cfg.set(self.section, iid, value)
