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
from pockpock_server import require_local_agent_request



class ResearchToolTests(unittest.TestCase):
        def test_extracts_only_explicit_task_hosts(self):
            self.assertEqual(
                explicit_task_hosts(
                    "Summarize https://example.com/reports, docs.example.org/page, and http://help.example.net."
                ),
                {"example.com", "docs.example.org", "help.example.net"},
            )

        def test_normalizes_bare_public_hostnames(self):
            self.assertEqual(normalize_public_url("example.org"), "https://example.org/")
            self.assertEqual(
                normalize_public_url("example.org/policies?type=returns"),
                "https://example.org/policies?type=returns",
            )
            self.assertEqual(
                explicit_task_hosts("Contact team@example.org about https://docs.example.org/start"),
                {"docs.example.org"},
            )

        def test_detects_bulk_media_download_requests(self):
            self.assertTrue(is_bulk_media_download_request("Find a way to download all anime videos"))
            self.assertFalse(is_bulk_media_download_request("Summarize the public video page"))
            self.assertFalse(is_bulk_media_download_request("Download my own project archive"))

        def test_detects_explicit_deliverable_formats(self):
            examples = (
                ("Scrape https://example.com and create a Markdown brief.", ".md"),
                ("Write a Word document with the findings.", ".docx"),
                ("Build an Excel spreadsheet from these values.", ".xlsx"),
                ("Create presentation slides from the report.", ".pptx"),
                ("Save the output as a CSV file.", ".csv"),
                ("Explain how to create a spreadsheet.", None),
                ("Generate an image of a tree.", None),
            )
            for task, expected in examples:
                with self.subTest(task=task):
                    self.assertEqual(requested_artifact_extension(task), expected)

        def test_rejects_private_and_unapproved_urls(self):
            with self.assertRaises(AgentToolError):
                _validate_public_url("http://127.0.0.1/private", {"127.0.0.1"})
            with self.assertRaises(AgentToolError):
                _validate_public_url("https://other.example/path", {"example.com"})
            with self.assertRaises(AgentToolError):
                _validate_public_url("https://example.com:8443/path", {"example.com"})
            with self.assertRaises(AgentToolError):
                _validate_public_url("https://example.com:80/path", {"example.com"})

        def test_https_context_keeps_certificate_validation_enabled(self):
            context = website_ssl_context()
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

        def test_extracts_readable_html_without_script_content(self):
            parser = _PageTextParser()
            parser.feed(
                '<title>Brief</title><nav><a href="/nav">Navigation</a></nav>'
                '<h1>Findings</h1><script>ignore()</script>'
                '<p><a href="/guide"><strong>Useful</strong> guide</a></p>'
            )
            self.assertEqual(parser.title, "Brief")
            self.assertIn("Findings", parser.text)
            self.assertIn("Useful guide", parser.text)
            self.assertNotIn("Navigation", parser.text)
            self.assertNotIn("ignore", parser.text)
            self.assertEqual(parser.links, [("/guide", "Useful guide")])

        def test_searches_only_a_bounded_set_of_same_host_text_pages(self):
            with tempfile.TemporaryDirectory() as temporary:
                context = AgentToolContext("e" * 32, {"example.org"}, {}, Path(temporary))
                visited = []
    
                async def fake_scrape(url, allowed_hosts, *, include_links=False):
                    visited.append(url)
                    links = []
                    if url == "https://example.org/":
                        links = [
                            ("/other", "Other page"),
                            ("/guide", "Guide"),
                            ("https://outside.example/secret", "External"),
                            ("/trailer.m3u8", "Media"),
                        ]
                    elif url == "https://example.org/guide":
                        links = [("/nested", "Nested page")]
                    return {
                        "url": url,
                        "title": url.rsplit("/", 1)[-1],
                        "text": f"Text from {url}",
                        "links": links if include_links else [],
                    }
    
                with patch("projects.agent_tools.research.scrape_public_page", new=AsyncMock(side_effect=fake_scrape)):
                    result = asyncio.run(search_public_site("example.org", "guide details", context))
    
                self.assertEqual(
                    visited,
                    [
                        "https://example.org/",
                        "https://example.org/guide",
                        "https://example.org/other",
                        "https://example.org/nested",
                    ],
                )
                self.assertEqual(result["pages_scanned"], 4)
                self.assertEqual(len(result["pages"]), 4)
                self.assertEqual(context.scrape_count, 4)
                self.assertTrue(all("outside.example" not in page["url"] for page in result["pages"]))
                self.assertTrue(all("m3u8" not in page["url"] for page in result["pages"]))

        def test_site_search_stops_at_five_pages(self):
            with tempfile.TemporaryDirectory() as temporary:
                context = AgentToolContext("f" * 32, {"example.org"}, {}, Path(temporary))
    
                async def fake_scrape(url, allowed_hosts, *, include_links=False):
                    index = int(url.rsplit("/", 1)[-1]) if url.rsplit("/", 1)[-1].isdigit() else 0
                    links = [(f"/{index + 1}", f"Page {index + 1}")] if index < 8 else []
                    return {"url": url, "title": "", "text": "Text", "links": links}
    
                with patch("projects.agent_tools.research.scrape_public_page", new=AsyncMock(side_effect=fake_scrape)):
                    result = asyncio.run(search_public_site("example.org", "page", context))
    
                self.assertEqual(result["pages_scanned"], 5)
                self.assertEqual(context.scrape_count, 5)
                with self.assertRaises(AgentToolError):
                    asyncio.run(search_public_site("example.org", "again", context))

if __name__ == "__main__":
    unittest.main()
