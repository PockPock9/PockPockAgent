import asyncio
from pathlib import Path
import ssl
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from projects import agent_tools
from projects.agent_tools import (
    AgentToolContext,
    AgentToolError,
    ProjectAgentContext,
    _PageTextParser,
    _validate_public_url,
    apply_project_patch,
    create_office_artifact,
    explicit_task_hosts,
    execute_agent_tool,
    execute_project_tool,
    is_bulk_media_download_request,
    list_project_files,
    normalize_public_url,
    propose_project_edit,
    propose_project_patch,
    read_project_file,
    requested_artifact_extension,
    save_text_artifact,
    search_project,
    search_public_site,
    website_ssl_context,
)
from frog_ai_server import require_local_agent_request



class ArtifactToolTests(unittest.TestCase):
        def test_saves_only_new_files_inside_task_directory(self):
            with tempfile.TemporaryDirectory() as temporary:
                output_dir = Path(temporary)
                context = AgentToolContext("a" * 32, set(), {}, output_dir)
                artifact = save_text_artifact(context, "summary.md", "# Result")
                self.assertEqual(Path(artifact["path"]).parent, output_dir)
                self.assertEqual(Path(artifact["path"]).read_text(encoding="utf-8"), "# Result")
                with self.assertRaises(AgentToolError):
                    save_text_artifact(context, "summary.md", "replacement")
                with self.assertRaises(AgentToolError):
                    save_text_artifact(context, "..\\outside.md", "outside")

        def test_creates_office_deliverables_without_running_code(self):
            examples = (
                ("word", "report.docx", "Report", "One paragraph."),
                ("spreadsheet", "table.xlsx", "Table", "Name,Value\nItem,42"),
                ("presentation", "brief.pptx", "Brief", "First slide\n\nSecond slide"),
            )
            with tempfile.TemporaryDirectory() as temporary:
                context = AgentToolContext("c" * 32, set(), {}, Path(temporary))
                for kind, filename, title, content in examples:
                    with self.subTest(kind=kind):
                        artifact = create_office_artifact(context, filename, kind, title, content)
                        result = Path(artifact["path"])
                        self.assertTrue(result.is_file())
                        self.assertGreater(result.stat().st_size, 1000)

if __name__ == "__main__":
    unittest.main()
