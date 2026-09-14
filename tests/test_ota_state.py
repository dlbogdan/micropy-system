import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
fake_uos = types.ModuleType("uos")
fake_uos.remove = os.remove
fake_uos.rename = os.rename
sys.modules["uos"] = fake_uos
sys.modules["ujson"] = json
spec = importlib.util.spec_from_file_location(
    "ota_state_test", ROOT / "src/lib/coresys/ota_state.py")
ota_state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ota_state)


class OtaStateTests(unittest.TestCase):
    def paths(self, directory):
        root = Path(directory)
        return str(root / "state.json"), str(root / "state.bak"), str(root / "state.new")

    def write_json(self, path, value):
        Path(path).write_text(json.dumps(value))

    def test_missing_or_torn_records_fall_back_deterministically(self):
        with tempfile.TemporaryDirectory() as directory:
            state, backup, _ = self.paths(directory)
            self.assertEqual(ota_state.load_state(state, backup), ota_state.default_state())
            Path(state).write_text('{"schema":')
            Path(backup).write_text('broken')
            self.assertEqual(ota_state.load_state(state, backup), ota_state.default_state())

    def test_newest_valid_generation_wins_even_if_live_record_is_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            state, backup, _ = self.paths(directory)
            older = ota_state.default_state()
            older["generation"] = 3
            newer = ota_state.default_state()
            newer["generation"] = 4
            newer["active"] = "b"
            self.write_json(state, older)
            self.write_json(backup, newer)
            self.assertEqual(ota_state.load_state(state, backup), newer)

    def test_invalid_newer_record_does_not_hide_valid_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            state, backup, _ = self.paths(directory)
            valid = ota_state.default_state()
            valid["generation"] = 7
            invalid = dict(valid)
            invalid["generation"] = 8
            invalid["active"] = "invalid"
            self.write_json(state, invalid)
            self.write_json(backup, valid)
            self.assertEqual(ota_state.load_state(state, backup), valid)

    def test_atomic_write_increments_generation_and_retains_previous_record(self):
        with tempfile.TemporaryDirectory() as directory:
            state, backup, new = self.paths(directory)
            first = ota_state.write_state(
                ota_state.default_state(), state, backup, new)
            second_value = dict(first)
            second_value["active"] = "b"
            second = ota_state.write_state(second_value, state, backup, new)
            self.assertEqual(second["generation"], 2)
            self.assertEqual(json.loads(Path(backup).read_text()), first)
            self.assertEqual(ota_state.load_state(state, backup), second)
            self.assertFalse(Path(new).exists())

    def test_pending_state_invariants_are_strict(self):
        valid = ota_state.default_state()
        valid.update({
            "pending": "b", "previous": "a",
            "candidate_version": "1.2.3", "candidate_attempts": 0,
        })
        self.assertEqual(ota_state.validate_state(valid), valid)
        for change in (
                {"pending": "a"}, {"previous": "b"},
                {"candidate_attempts": -1}, {"schema": 99}):
            candidate = dict(valid)
            candidate.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                ota_state.validate_state(candidate)


if __name__ == "__main__":
    unittest.main()
