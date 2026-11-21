import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "projects"))

from agent_verifier.capsule import StateCapsule


class CapsuleTests(unittest.TestCase):
    def test_round_trip_preserves_all_fields(self):
        capsule = StateCapsule(
            goal="Build the widget",
            decisions=["Use stdlib only"],
            constraints=["No network"],
            open_threads=["Check the API shape"],
            next_step="Write the test",
            step_index=2,
        )
        capsule.record_file("app.py", sha256_before="a" * 64, sha256="b" * 64)
        restored = StateCapsule.from_dict(capsule.to_dict())
        self.assertEqual(restored.goal, "Build the widget")
        self.assertEqual(restored.decisions, ["Use stdlib only"])
        self.assertEqual(restored.constraints, ["No network"])
        self.assertEqual(restored.open_threads, ["Check the API shape"])
        self.assertEqual(restored.next_step, "Write the test")
        self.assertEqual(restored.step_index, 2)
        self.assertEqual(len(restored.files_changed), 1)
        self.assertEqual(restored.files_changed[0].path, "app.py")
        self.assertEqual(restored.files_changed[0].sha256, "b" * 64)
        self.assertTrue(restored.files_changed[0].diff_hash)

    def test_from_dict_tolerates_missing_and_bad_input(self):
        self.assertEqual(StateCapsule.from_dict(None).goal, "")
        self.assertEqual(StateCapsule.from_dict({"goal": 42}).goal, "42")
        self.assertEqual(StateCapsule.from_dict({"files_changed": [{"path": 1}]}).files_changed, [])

    def test_content_hash_is_stable_and_changes_with_content(self):
        first = StateCapsule(goal="x")
        second = StateCapsule(goal="x")
        third = StateCapsule(goal="y")
        self.assertEqual(first.content_hash(), second.content_hash())
        self.assertNotEqual(first.content_hash(), third.content_hash())

    def test_record_file_updates_in_place(self):
        capsule = StateCapsule()
        capsule.record_file("a.py", sha256="1" * 64)
        capsule.record_file("a.py", sha256="2" * 64)
        self.assertEqual(len(capsule.files_changed), 1)
        self.assertEqual(capsule.files_changed[0].sha256, "2" * 64)


if __name__ == "__main__":
    unittest.main()
