import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "app_store_test", ROOT / "src/lib/coresys/app_store.py")
app_store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_store)


class ConfigManagerStub:
    """The measured manager_config surface this adapter touches:
    .config dict, get(section, key, default), set(section, key, value)."""

    def __init__(self, config):
        self.config = config
        self.sets = []

    def get(self, section, key, default=None):
        return self.config.get(section, {}).get(key, default)

    def set(self, section, key, value):
        self.sets.append((section, key, value))
        self.config.setdefault(section, {})[key] = value


class AppStoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="app-store-")
        self.path = os.path.join(self.dir, "app-config.json")

    def tearDown(self):
        if os.path.isfile(self.path):
            os.remove(self.path)

    def test_round_trip_and_reopen(self):
        store = app_store.AppStore(self.path)
        self.assertEqual(store.keys(), [])
        self.assertIsNone(store.load("brightness"))
        store.save("brightness", 7)
        store.save("theme", "mono")
        again = app_store.AppStore(self.path)
        self.assertEqual(sorted(again.keys()), ["brightness", "theme"])
        self.assertEqual(again.load("brightness"), 7)
        self.assertEqual(again.load("theme"), "mono")

    def test_file_holds_plain_json(self):
        app_store.AppStore(self.path).save("v", [1, 2])
        with open(self.path) as f:
            self.assertEqual(json.load(f), {"v": [1, 2]})

    def test_missing_file_starts_empty(self):
        store = app_store.AppStore(os.path.join(self.dir, "absent.json"))
        self.assertEqual(store.keys(), [])
        store.save("a", 1)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "absent.json")))

    def test_corrupt_file_starts_empty_not_fatal(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        store = app_store.AppStore(self.path)
        self.assertEqual(store.keys(), [])
        store.save("recovered", True)
        self.assertEqual(app_store.AppStore(self.path).load("recovered"), True)

    def test_non_dict_json_starts_empty(self):
        with open(self.path, "w") as f:
            json.dump([1, 2, 3], f)
        self.assertEqual(app_store.AppStore(self.path).keys(), [])

    def test_overwrite_keeps_one_record_per_key(self):
        store = app_store.AppStore(self.path)
        store.save("k", 1)
        store.save("k", 2)
        self.assertEqual(store.keys(), ["k"])
        self.assertEqual(store.load("k"), 2)


class ConfigSectionTests(unittest.TestCase):
    def test_reads_and_writes_through_the_manager(self):
        cfg = ConfigManagerStub({"UI": {"theme": "mono"}})
        view = app_store.ConfigSection(cfg, "UI")
        self.assertEqual(view.keys(), ["theme"])
        self.assertEqual(view.load("theme"), "mono")
        view.save("contrast", 12)
        self.assertEqual(cfg.config["UI"]["contrast"], 12)
        self.assertEqual(cfg.sets, [("UI", "contrast", 12)])

    def test_absent_section_is_an_empty_view(self):
        cfg = ConfigManagerStub({})
        view = app_store.ConfigSection(cfg, "UI")
        self.assertEqual(view.keys(), [])
        self.assertIsNone(view.load("anything"))
        view.save("a", 1)
        self.assertEqual(cfg.config["UI"], {"a": 1})

    def test_non_dict_section_is_treated_as_empty(self):
        cfg = ConfigManagerStub({"UI": "oops"})
        self.assertEqual(app_store.ConfigSection(cfg, "UI").keys(), [])


if __name__ == "__main__":
    unittest.main()
