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
from pockpock_server import is_workspace_edit_request, require_local_agent_request



class AgentToolTests(unittest.TestCase):
        @staticmethod
        def request(headers=(), client=("127.0.0.1", 40000)):
            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}
    
            return Request({
                "type": "http",
                "method": "POST",
                "path": "/api/agents/run",
                "headers": list(headers),
                "client": client,
                "server": ("127.0.0.1", 8766),
                "scheme": "http",
                "query_string": b"",
            }, receive=receive)

        def test_agent_requests_are_local_only(self):
            require_local_agent_request(self.request([(b"origin", b"http://127.0.0.1:5173")]))
            for headers in (
                [(b"origin", b"https://proseth.tailb9c46e.ts.net")],
                [(b"x-forwarded-for", b"100.90.1.2")],
                [(b"x-forwarded-host", b"proseth.tailb9c46e.ts.net")],
            ):
                with self.subTest(headers=headers), self.assertRaises(HTTPException):
                    require_local_agent_request(self.request(headers))

        def test_workspace_edit_detection_ignores_negated_code_mentions(self):
            self.assertFalse(is_workspace_edit_request(
                "Create one CSV artifact from the attachment. Do not make a Word document or attempt to run code."
            ))
            self.assertTrue(is_workspace_edit_request(
                "Create a Python script to summarize the attached data; do not execute the script."
            ))
            self.assertFalse(is_workspace_edit_request("Do not create a website; summarize the attached brief instead."))
            self.assertFalse(is_workspace_edit_request(
                "Open a webpage and summarize it. Do not edit files or create a separate document."
            ))
            self.assertTrue(is_workspace_edit_request(
                "Do not edit the existing site; instead create a new webpage."
            ))
            self.assertIsNone(requested_artifact_extension(
                "Open a webpage and summarize it. Do not edit files or create a separate document."
            ))
            self.assertEqual(
                requested_artifact_extension("Create a Markdown report from the research results."),
                ".md",
            )

        def test_reads_only_the_requested_attached_document(self):
            with tempfile.TemporaryDirectory() as temporary:
                context = AgentToolContext("d" * 32, set(), {"notes.txt": "Selected notes."}, Path(temporary))
                result = asyncio.run(execute_agent_tool("read_selected_file", {"name": "notes.txt"}, context))
                self.assertEqual(result["text"], "Selected notes.")

        def test_rejects_unregistered_tools_and_unattached_files(self):
            with tempfile.TemporaryDirectory() as temporary:
                context = AgentToolContext("b" * 32, set(), {}, Path(temporary))
                with self.assertRaises(AgentToolError):
                    asyncio.run(execute_agent_tool("run_shell", {}, context))
                with self.assertRaises(AgentToolError):
                    asyncio.run(execute_agent_tool("read_selected_file", {"name": "secret.txt"}, context))

if __name__ == "__main__":
    unittest.main()
