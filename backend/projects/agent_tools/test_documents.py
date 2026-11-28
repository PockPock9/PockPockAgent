"""Word, PDF, spreadsheet and presentation output of create_office_document (scenario run 2026-11-28)."""

import re
import tempfile
import unittest
import zipfile
from pathlib import Path

from projects.agent_tools.common import AgentToolContext, AgentToolError
from projects.agent_tools.artifacts import create_office_artifact
from projects.agent_tools.documents import bold_runs, parse_blocks

RESUME = """# Kan Chan
Software engineer | kan@example.com

## Experience
- **Senior engineer**, PockPock (2023-now)
- Engineer, Mekong Labs

## Skills
Python, TypeScript
"""


def word_xml(path):
    return zipfile.ZipFile(path).read("word/document.xml").decode()


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.context = AgentToolContext(task_id="a" * 32, allowed_hosts=set(), attachments={}, output_dir=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_markdown_becomes_headings_lists_and_bold(self):
        blocks = parse_blocks(RESUME)
        self.assertEqual([b.kind for b in blocks], ["heading", "paragraph", "heading", "bullet", "bullet", "heading", "paragraph"])
        self.assertEqual(bold_runs("**Senior** engineer"), [("Senior", True), (" engineer", False)])

    def test_word_uses_real_heading_and_list_styles(self):
        result = create_office_artifact(self.context, "resume.docx", "word", "Kan Chan", RESUME)
        xml = word_xml(result["path"])
        styles = re.findall(r'w:pStyle w:val="([^"]+)"', xml)
        self.assertIn("Heading2", styles)
        self.assertEqual(styles.count("ListBullet"), 2)
        self.assertNotIn("## ", xml)
        self.assertNotIn("**", xml)
        self.assertEqual(styles.count("Title"), 1, "the title is written once, not twice")

    def test_pdf_is_a_real_pdf_with_the_text(self):
        from pypdf import PdfReader

        result = create_office_artifact(self.context, "resume.pdf", "pdf", "Kan Chan", RESUME)
        self.assertEqual(Path(result["path"]).read_bytes()[:5], b"%PDF-")
        text = PdfReader(result["path"]).pages[0].extract_text()
        self.assertIn("Experience", text)
        self.assertNotIn("##", text)

    def test_the_extension_fixes_a_wrong_kind(self):
        result = create_office_artifact(self.context, "invoice.pdf", "document", "Invoice", "Total: $510")
        self.assertTrue(result["path"].endswith("invoice.pdf"))

    def test_spreadsheet_numbers_are_numbers_and_markdown_tables_work(self):
        from openpyxl import load_workbook

        result = create_office_artifact(self.context, "totals.xlsx", "spreadsheet", "Totals", "| Region | Total |\n|---|---|\n| North | 3,650 |\n| South | 2800.5 |\n")
        rows = [[cell.value for cell in row] for row in load_workbook(result["path"]).active.rows]
        self.assertEqual(rows, [["Region", "Total"], ["North", 3650], ["South", 2800.5]])

    def test_each_heading_starts_a_slide(self):
        content = "# Problem\n- Food arrives cold\n\n# Solution\n- Insulated bags\n\n# Ask\n- $50k"
        result = create_office_artifact(self.context, "deck.pptx", "presentation", "TukFood", content)
        slides = [n for n in zipfile.ZipFile(result["path"]).namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        self.assertEqual(len(slides), 4, "a cover and three slides")

    def test_a_retry_may_replace_its_own_document_but_not_others(self):
        create_office_artifact(self.context, "notes.docx", "word", "Notes", "first")
        again = create_office_artifact(self.context, "notes.docx", "word", "Notes", "second")
        self.assertEqual(again.get("replaced"), "true")
        (Path(self.tmp.name) / "theirs.docx").write_bytes(b"x")
        with self.assertRaises(AgentToolError):
            create_office_artifact(self.context, "theirs.docx", "word", "Theirs", "text")


if __name__ == "__main__":
    unittest.main()
