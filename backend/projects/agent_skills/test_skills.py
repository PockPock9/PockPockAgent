"""Tests for the skill library: schema, validation, CRUD, retrieval gate."""

import tempfile
import unittest
from pathlib import Path

from projects.agent_skills.skills import (
    Skill,
    SkillLibrary,
    parse_frontmatter,
    skill_from_markdown,
    validate_skill,
)

VALID_MD = """---
name: "summarise-csv"
description: "Summarise a CSV file into a short markdown table."
version: "1.0.0"
verification: {"type": "manual"}
tags: ["csv", "summarise"]
---

# Summarise a CSV

1. Read the CSV file.
2. Count rows and list columns.
3. Write a short markdown table.
"""


class SkillSchemaTests(unittest.TestCase):
    def test_round_trip_frontmatter(self):
        skill = skill_from_markdown(VALID_MD)
        self.assertEqual(skill.name, "summarise-csv")
        self.assertEqual(skill.version, "1.0.0")
        self.assertEqual(skill.verification, {"type": "manual"})
        self.assertEqual(skill.tags, ["csv", "summarise"])
        self.assertIn("Read the CSV file", skill.body)
        self.assertEqual(skill.to_markdown(), skill_from_markdown(skill.to_markdown()).to_markdown())

    def test_missing_frontmatter_rejected(self):
        with self.assertRaises(ValueError):
            skill_from_markdown("# No frontmatter\n\nbody\n")

    def test_missing_description_rejected(self):
        with self.assertRaises(ValueError):
            skill_from_markdown('---\nname: "x"\n---\n\nbody\n')

    def test_validation_problems(self):
        bad = Skill(name="Bad Name!", description="", version="v1", body="")
        problems = validate_skill(bad)
        self.assertGreaterEqual(len(problems), 3)
        self.assertIn("name must be", problems[0])

    def test_bad_verification_type_rejected(self):
        skill = Skill(name="ok-skill", description="d", body="b",
                      verification={"type": "telepathy"})
        self.assertTrue(any("verification" in p for p in validate_skill(skill)))

    def test_parse_frontmatter_without_frontmatter(self):
        data, body = parse_frontmatter("# hello\n")
        self.assertEqual(data, {})
        self.assertEqual(body, "# hello\n")


class SkillLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.library = SkillLibrary(Path(self.tmp.name) / "skills", dense_enabled=False)

    def tearDown(self):
        self.tmp.cleanup()

    def _skill(self, name="summarise-csv"):
        return Skill(name=name, description=f"Do {name}", body="1. Do the thing.")

    def test_create_read_list_delete(self):
        path = self.library.create(self._skill())
        self.assertTrue(path.is_file())
        record = self.library.read("summarise-csv")
        self.assertEqual(record.skill.description, "Do summarise-csv")
        self.assertEqual(len(self.library.list()), 1)
        self.assertTrue(self.library.delete("summarise-csv"))
        self.assertEqual(self.library.list(), [])

    def test_create_duplicate_without_overwrite_fails(self):
        self.library.create(self._skill())
        with self.assertRaises(FileExistsError):
            self.library.create(self._skill())

    def test_invalid_name_rejected(self):
        with self.assertRaises(ValueError):
            self.library.create(Skill(name="Bad Name", description="d", body="b"))

    def test_read_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.library.read("nope")

    def test_retrieve_returns_only_promoted(self):
        draft = self._skill("draft-skill")
        promoted = self._skill("csv-summary-skill")
        self.library.create(draft)
        self.library.create(promoted)
        # Promote only the second one via the status hook.
        self.library.attach_statuses({"csv-summary-skill": "promoted"})
        results = self.library.retrieve("summarise the csv file please")
        names = [r.skill.name for r in results]
        self.assertIn("csv-summary-skill", names)
        self.assertNotIn("draft-skill", names)

    def test_retrieve_empty_when_nothing_promoted(self):
        self.library.create(self._skill())
        self.assertEqual(self.library.retrieve("summarise the csv file"), [])

    def test_retrieve_unrelated_query_returns_nothing(self):
        self.library.create(self._skill())
        self.library.attach_statuses({"summarise-csv": "promoted"})
        self.assertEqual(self.library.retrieve("launch the rocket to mars"), [])

    def test_malformed_skill_file_does_not_hide_library(self):
        self.library.create(self._skill())
        bad_dir = Path(self.tmp.name) / "skills" / "broken"
        bad_dir.mkdir()
        (bad_dir / "SKILL.md").write_text("---\nname: 123\n---\n\n", encoding="utf-8")
        names = [r.skill.name for r in self.library.list()]
        self.assertEqual(names, ["summarise-csv"])


if __name__ == "__main__":
    unittest.main()
