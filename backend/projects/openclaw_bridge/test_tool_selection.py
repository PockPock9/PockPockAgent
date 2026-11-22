import os
import unittest
from unittest import mock

from projects.openclaw_bridge.tool_selection import OpenClawToolSelector

SKILLS = [
    {"key": "pdf", "name": "pdf-reader", "description": "Read text and tables from PDF files"},
    {"key": "sheets", "name": "spreadsheet-edit", "description": "Change xlsx and csv spreadsheet files"},
    {"key": "gh", "name": "github", "description": "GitHub CLI for issues, pull requests and CI logs"},
    {"key": "browser", "name": "browser-automation", "description": "Control web pages with the browser tool"},
    {"key": "diagram", "name": "diagram-maker", "description": "Create SVG diagrams for architecture and flows"},
    {"key": "health", "name": "healthcheck", "description": "Audit hosts: firewall, updates, disk encryption"},
    {"key": "meme", "name": "meme-maker", "description": "Search meme templates and generate memes"},
    {"key": "canvas", "name": "canvas", "description": "Present hosted widget documents on a macOS panel"},
    {"key": "clawhub", "name": "clawhub", "description": "Search ClawHub for plugins and skills"},
]
SERVERS = [{"name": "postgres", "target": "npx -y postgres-mcp"}, {"name": "notes", "target": "node notes-server.js"}]


class FakeEmbedder:
    """Vectors by keyword family, so a paraphrase ("chart") lands near the diagram skill."""
    FAMILIES = [("diagram", "chart", "flowchart", "svg"), ("pdf",), ("github", "pull")]

    def available(self):
        return True

    def embed(self, texts):
        return [[1.0 if any(word in text.lower() for word in family) else 0.0 for family in self.FAMILIES] + [0.1] for text in texts]


class SelectionTests(unittest.TestCase):
    def selector(self, skills=SKILLS, servers=SERVERS, embedder=None):
        return OpenClawToolSelector(lambda: {"skills": skills, "mcp": servers}, embedder=embedder)

    def test_matching_skills_are_offered_and_the_rest_hidden(self):
        result = self.selector().select("pockpock-a", "summarise the tables in report.pdf")
        hidden = result["toolOverrides"]["skills"]
        self.assertNotIn("pdf", hidden)
        self.assertIn("meme", hidden)
        self.assertTrue(all(value is False for value in hidden.values()), "the overlay only hides")
        self.assertEqual(result["skills_offered"] + len(hidden), len(SKILLS))
        self.assertGreater(result["tokens_saved"], 0)

    def test_a_follow_up_keeps_what_the_conversation_used(self):
        selector = self.selector()
        selector.select("pockpock-a", "open the pull request on github")
        follow_up = selector.select("pockpock-a", "and the other one too")
        self.assertNotIn("gh", follow_up["toolOverrides"]["skills"])
        other = selector.select("pockpock-b", "and the other one too")
        self.assertIn("gh", other["toolOverrides"]["skills"], "sticky choices are per conversation")

    def test_mcp_servers_are_filtered_only_when_there_are_several(self):
        result = self.selector().select("pockpock-a", "list the tables in my postgres database")
        self.assertEqual(result["toolOverrides"]["mcpServers"], {"notes": False})
        single = self.selector(servers=SERVERS[:1]).select("pockpock-a", "hello")
        self.assertNotIn("mcpServers", single["toolOverrides"] or {})

    def test_few_skills_are_not_filtered(self):
        result = self.selector(skills=SKILLS[:5], servers=[]).select("pockpock-a", "read the pdf")
        self.assertIsNone(result["toolOverrides"])

    def test_embeddings_find_a_paraphrase(self):
        keyword_only = self.selector().select("pockpock-a", "draw a flowchart of the login")
        hybrid = self.selector(embedder=FakeEmbedder()).select("pockpock-a", "draw a flowchart of the login")
        self.assertIn("diagram", keyword_only["toolOverrides"]["skills"])
        self.assertNotIn("diagram", hybrid["toolOverrides"]["skills"])
        self.assertEqual(hybrid["method"], "hybrid")

    def test_failures_and_the_switch_give_openclaw_everything(self):
        def broken():
            raise RuntimeError("OpenClaw is not reachable")
        self.assertIsNone(OpenClawToolSelector(broken).select("pockpock-a", "read the pdf")["toolOverrides"])
        with mock.patch.dict(os.environ, {"POCKPOCK_OPENCLAW_TOOL_RETRIEVAL": "0"}):
            self.assertEqual(self.selector().select("pockpock-a", "read the pdf"), {"toolOverrides": None, "reason": "off"})

    def test_the_catalog_is_read_once_for_a_while(self):
        calls = []
        selector = OpenClawToolSelector(lambda: calls.append(1) or {"skills": SKILLS, "mcp": []})
        selector.select("pockpock-a", "pdf")
        selector.select("pockpock-a", "github")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
