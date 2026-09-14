import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    ota_state = types.ModuleType("lib.coresys.ota_state")
    ota_state.load_state = lambda: None
    ota_state.write_state = lambda state: state
    sys.modules["lib.coresys.ota_state"] = ota_state
    spec = importlib.util.spec_from_file_location(
        "slot_manager_test", ROOT / "src/lib/coresys/slot_manager.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SlotManagerTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.active = {
            "schema": 1, "generation": 1, "active": "a", "pending": None,
            "previous": None, "candidate_version": None,
            "candidate_attempts": 0, "rejected_version": None,
        }

    def test_active_slot_is_selected_without_state_write(self):
        with mock.patch.object(self.module, "load_state", return_value=self.active), \
                mock.patch.object(self.module, "write_state") as write:
            slot, candidate, _ = self.module.prepare_slot_boot()
        self.assertEqual((slot, candidate), ("a", False))
        write.assert_not_called()

    def test_candidate_attempt_is_persisted_before_selection(self):
        pending = dict(self.active)
        pending.update({
            "pending": "b", "previous": "a",
            "candidate_version": "2.0.0",
        })
        with mock.patch.object(self.module, "load_state", return_value=pending), \
                mock.patch.object(self.module, "write_state", side_effect=lambda value: value) as write:
            slot, candidate, state = self.module.prepare_slot_boot()
        self.assertEqual((slot, candidate), ("b", True))
        self.assertEqual(state["candidate_attempts"], 1)
        write.assert_called_once()

    def test_unconfirmed_candidate_rolls_back_on_next_boot(self):
        pending = dict(self.active)
        pending.update({
            "pending": "b", "previous": "a", "candidate_version": "2.0.0",
            "candidate_attempts": 1,
        })
        with mock.patch.object(self.module, "load_state", return_value=pending), \
                mock.patch.object(self.module, "write_state", side_effect=lambda value: value):
            slot, candidate, state = self.module.prepare_slot_boot()
        self.assertEqual((slot, candidate), ("a", False))
        self.assertEqual(state["rejected_version"], "2.0.0")
        self.assertIsNone(state["pending"])

    def test_confirm_promotes_only_pending_slot(self):
        pending = dict(self.active)
        pending.update({
            "pending": "b", "previous": "a", "candidate_version": "2.0.0",
            "candidate_attempts": 1,
        })
        with mock.patch.object(self.module, "load_state", return_value=pending), \
                mock.patch.object(self.module, "write_state", side_effect=lambda value: value):
            with tempfile.TemporaryDirectory() as directory:
                version_path = str(Path(directory) / 'version.txt')
                confirmed = self.module.confirm_running_slot("b", version_path)
                self.assertEqual(Path(version_path).read_text(), '2.0.0')
        self.assertEqual(confirmed["active"], "b")
        self.assertIsNone(confirmed["pending"])

    def test_slot_path_activation_removes_other_slot(self):
        original = list(sys.path)
        try:
            sys.path[:] = ["/lib", "/apps/a", "/apps/b"]
            self.module.activate_slot_path("b")
            self.assertEqual(sys.path, ["/apps/b", "/lib"])
        finally:
            sys.path[:] = original


if __name__ == "__main__":
    unittest.main()
