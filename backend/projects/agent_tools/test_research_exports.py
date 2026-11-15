import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest

from projects.agent_tools import AgentToolContext, AgentToolError
from projects.agent_tools.research_answers import validate_research_answer
from projects.agent_tools.research_contracts import (
    ResearchProviderError,
    SourceEvidence,
    make_source_record,
)
from projects.agent_tools.research_exports import create_research_export

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import pockpock_server as gateway


class ResearchExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        retrieved_at = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
        published_at = datetime(2025, 5, 1, 0, 0, tzinfo=timezone.utc)
        first = make_source_record(
            url="https://example.org/a?x=1",
            provider="named_host_fetcher",
            retrieved_at=retrieved_at,
            published_at=published_at,
            title="First <source> [title]",
            snippet='=HYPERLINK("https://invalid.example")',
        )
        second = make_source_record(
            url="https://example.org/b",
            provider="named_host_fetcher",
            retrieved_at=retrieved_at,
            title="Second source",
            snippet="A second source snippet.",
        )
        cls.sources = [first.model_dump(mode="json"), second.model_dump(mode="json")]
        cls.evidence = [
            SourceEvidence(
                source_id=first.source_id,
                excerpt="The launch year was 2024.",
                retrieved_at=retrieved_at,
            ).model_dump(mode="json"),
            SourceEvidence(
                source_id=second.source_id,
                excerpt="The launch year was 2025.",
                retrieved_at=retrieved_at,
            ).model_dump(mode="json"),
        ]
        cls.first_id = first.source_id
        cls.second_id = second.source_id
        cls.answer = validate_research_answer(
            json.dumps({
                "contract_version": 1,
                "claims": [
                    {
                        "text": '<img src=x onerror="alert(1)">',
                        "status": "supported",
                        "citations": [{
                            "source_id": first.source_id,
                            "quote": "The launch year was 2024.",
                        }],
                    },
                    {
                        "text": "No verified date was found for another detail.",
                        "status": "unsupported",
                        "citations": [],
                    },
                ],
                "conflicts": [{
                    "topic": "Launch year",
                    "summary": "The two sources give different years.",
                    "citations": [
                        {"source_id": first.source_id, "quote": "The launch year was 2024."},
                        {"source_id": second.source_id, "quote": "The launch year was 2025."},
                    ],
                }],
                "limitations": ["The disagreement could not be resolved from these pages."],
                "completion_checks": ["[CHECK 1: PASS] Each quote matches retrieved evidence."],
            }),
            cls.sources,
            cls.evidence,
        )

    def _create(self, extension, provider_errors=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        context = AgentToolContext("a" * 32, set(), {}, Path(temporary.name))
        artifact = create_research_export(
            context,
            self.answer,
            self.sources,
            self.evidence,
            f"research-report{extension}",
            extension,
            provider_errors,
        )
        return context, artifact, Path(artifact["path"])

    def test_markdown_and_html_exports_keep_provenance_and_escape_page_text(self):
        _, markdown_artifact, markdown_path = self._create(".md")
        markdown = markdown_path.read_text(encoding="utf-8")
        self.assertEqual(markdown_artifact["kind"], "md")
        self.assertIn("[First \\<source\\> \\[title\\]](<https://example.org/a?x=1>)", markdown)
        self.assertIn(f"Source ID: `{self.first_id}`", markdown)
        self.assertIn("retrieved 2026-11-12T12:00:00+00:00", markdown)
        self.assertIn("published 2025-05-01T00:00:00+00:00", markdown)
        self.assertIn("## Conflicting evidence", markdown)
        self.assertIn("## Evidence limitations", markdown)

        _, html_artifact, html_path = self._create(".html")
        html = html_path.read_text(encoding="utf-8")
        self.assertEqual(html_artifact["kind"], "html")
        self.assertIn('href="https://example.org/a?x=1"', html)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("The launch year was 2025.", html)
        self.assertIn(self.first_id, html)

    def test_word_export_has_linked_citations_and_bounded_evidence(self):
        _, artifact, path = self._create(".docx")
        from docx import Document

        document = Document(path)
        paragraphs = "\n".join(paragraph.text for paragraph in document.paragraphs)
        self.assertEqual(artifact["kind"], "word")
        self.assertIn("Conflicting evidence", paragraphs)
        self.assertIn("The launch year was 2024.", paragraphs)
        self.assertIn("The disagreement could not be resolved", paragraphs)
        links = [rel.target_ref for rel in document.part.rels.values() if rel.is_external]
        self.assertIn("https://example.org/a?x=1", links)
        self.assertIn("https://example.org/b", links)

    def test_spreadsheet_export_has_citable_sheets_and_neutralizes_formulas(self):
        _, artifact, path = self._create(".xlsx")
        from openpyxl import load_workbook

        workbook = load_workbook(path, data_only=False)
        self.assertEqual(artifact["kind"], "spreadsheet")
        self.assertTrue({"Findings", "Conflicts", "Sources", "Limitations"}.issubset(workbook.sheetnames))
        self.assertEqual(workbook["Findings"]["D2"].hyperlink.target, "https://example.org/a?x=1")
        self.assertEqual(workbook["Sources"]["C2"].hyperlink.target, "https://example.org/a?x=1")
        unsafe_snippet = workbook["Sources"]["F2"]
        self.assertEqual(unsafe_snippet.data_type, "s")
        self.assertTrue(unsafe_snippet.value.startswith("'="))
        self.assertEqual(workbook["Conflicts"].max_row, 3)

    def test_presentation_export_keeps_citations_clickable_and_includes_conflicts(self):
        _, artifact, path = self._create(".pptx")
        from pptx import Presentation

        presentation = Presentation(path)
        slide_text = "\n".join(
            shape.text
            for slide in presentation.slides
            for shape in slide.shapes
            if shape.has_text_frame
        )
        links = [
            run.hyperlink.address
            for slide in presentation.slides
            for shape in slide.shapes
            if shape.has_text_frame
            for paragraph in shape.text_frame.paragraphs
            for run in paragraph.runs
            if run.hyperlink.address
        ]
        self.assertEqual(artifact["kind"], "presentation")
        self.assertIn("Conflicting evidence", slide_text)
        self.assertIn("The launch year was 2025.", slide_text)
        self.assertIn("Evidence limitation", slide_text)
        self.assertIn("https://example.org/a?x=1", links)
        self.assertIn("https://example.org/b", links)

    def test_export_rejects_unsupported_formats_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = AgentToolContext("b" * 32, set(), {}, Path(temporary))
            with self.assertRaises(AgentToolError):
                create_research_export(
                    context,
                    self.answer,
                    self.sources,
                    self.evidence,
                    "research-report.pdf",
                    ".pdf",
                )
            empty_answer = self.answer.model_copy(update={
                "claims": [],
                "conflicts": [],
                "limitations": [],
                "completion_checks": [],
            })
            with self.assertRaisesRegex(AgentToolError, "no findings"):
                create_research_export(
                    context,
                    empty_answer,
                    self.sources,
                    self.evidence,
                    "empty.md",
                    ".md",
                )
            first = create_research_export(
                context, self.answer, self.sources, self.evidence, "research-report.md", ".md"
            )
            second = create_research_export(
                context, self.answer, self.sources, self.evidence, "research-report.md", ".md"
            )
            self.assertEqual(first["name"], "research-report.md")
            self.assertEqual(second["name"], "research-report-2.md")
            self.assertNotEqual(Path(first["path"]).read_bytes(), b"")
            self.assertNotEqual(Path(second["path"]).read_bytes(), b"")

    def test_export_includes_retrieval_errors_and_removes_invalid_xml_characters(self):
        error = ResearchProviderError(
            provider="named_host_fetcher",
            code="upstream_error",
            message="A linked page could not be retrieved.",
            retryable=True,
        ).model_dump(mode="json")
        _, artifact, path = self._create(".md", [error])
        content = path.read_text(encoding="utf-8")
        self.assertIn("A linked page could not be retrieved\\.", content)
        self.assertEqual(artifact["kind"], "md")

        citation = self.answer.claims[0].citations[0]
        unsafe_quote = "The launch year\x00 was 2024."
        unsafe_answer = self.answer.model_copy(update={
            "claims": [self.answer.claims[0].model_copy(update={
                "citations": [citation.model_copy(update={"quote": unsafe_quote})],
            })],
            "conflicts": [],
        })
        unsafe_evidence = [
            {**self.evidence[0], "excerpt": unsafe_quote},
            self.evidence[1],
        ]
        with tempfile.TemporaryDirectory() as temporary:
            context = AgentToolContext("c" * 32, set(), {}, Path(temporary))
            artifact = create_research_export(
                context,
                unsafe_answer,
                self.sources,
                unsafe_evidence,
                "sanitized.md",
                ".md",
            )
            content = Path(artifact["path"]).read_text(encoding="utf-8")
        self.assertNotIn("\x00", content)
        self.assertIn("The launch year was 2024\\.", content)

    def test_gateway_emits_and_checks_the_validated_report_artifact(self):
        task_id = "d" * 32
        with tempfile.TemporaryDirectory() as temporary:
            context = AgentToolContext(task_id, set(), {}, Path(temporary))
            event = gateway.research_export_artifact_event(
                context,
                task_id,
                self.answer,
                self.sources,
                self.evidence,
                ".md",
                [],
            )
            self.assertEqual(event["type"], "artifact")
            self.assertEqual(event["name"], "research-report.md")
            self.assertEqual(event["url"], f"/api/agents/artifacts/{task_id}/research-report.md")
            self.assertTrue(Path(event["path"]).is_file())
            self.assertTrue(gateway.requested_artifact_exists(context.artifacts, ".md"))
            self.assertFalse(gateway.requested_artifact_exists(context.artifacts, ".html"))


if __name__ == "__main__":
    unittest.main()
