import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from projects.local_memory import LocalPreferenceMemory, extract_safe_preferences


class LocalPreferenceMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary.name) / "memory.sqlite3"

        def connect_db():
            connection = sqlite3.connect(database_path)
            connection.row_factory = sqlite3.Row
            return connection

        self.memory = LocalPreferenceMemory(connect_db, threading.Lock())
        self.memory.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def test_extracts_only_allowlisted_reusable_preferences(self):
        preferences = extract_safe_preferences(
            "I prefer concise answers. I prefer Python for code examples. "
            "My private token is sk-example-do-not-store."
        )

        self.assertEqual(preferences, [
            ("code_language", "Prefer Python for code examples."),
            ("response_style", "Prefer concise responses."),
        ])
        self.assertNotIn("sk-example", repr(preferences))
        self.assertEqual(extract_safe_preferences("Remember my home address: 1 Main St."), [])

    def test_memory_is_local_deduplicated_disableable_and_deletable(self):
        first = self.memory.remember_from_text("I prefer concise answers.")
        second = self.memory.remember_from_text("I prefer concise answers.")

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        preference_id = second[0]["id"]
        self.assertTrue(self.memory.delete_preference(preference_id))
        self.assertEqual(self.memory.list_preferences(), [])

        self.memory.set_enabled(False)
        self.assertEqual(self.memory.remember_from_text("I prefer detailed answers."), [])
        self.assertFalse(self.memory.is_enabled())
        self.memory.set_enabled(True)
        self.memory.remember_from_text("I prefer detailed answers.")
        self.memory.clear()
        self.assertEqual(self.memory.list_preferences(), [])

    def test_new_value_replaces_old_value_for_the_same_preference_category(self):
        first = self.memory.remember_from_text("I prefer concise answers.")[0]
        second = self.memory.remember_from_text("I prefer detailed answers.")[0]

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.memory.list_preferences()), 1)
        self.assertEqual(self.memory.list_preferences()[0]["preference"], "Prefer detailed responses.")


if __name__ == "__main__":
    unittest.main()
