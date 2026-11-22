import tempfile
import unittest
from pathlib import Path

from projects.agent_extensions.directory import (
    CURATED_URL, SITE, SITEMAP_INDEX, Directory, DirectoryError, parse_curated, slugs,
)

README = """# Awesome MCP Servers
## Sponsors
- **[Sponsor](https://example.com)** - Not a server
## Reference Servers
- **[Fetch](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch)** - Web content fetching and conversion
## Official Servers
- **[BrowserStack](https://github.com/browserstack/mcp-server)** – Bring the [Test Platform](https://www.browserstack.com/x) to your AI tools
- **[Hosted](https://hosted.example.com/mcp)** — A remote server with a website link
## Community Servers
- \\*\\*[Spotify Player](https://github.com/vsaez/mcp-spotify-player) – Control Spotify playback. (Python)
- **[Bad](javascript:alert(1))** - Not https
## Clients
- **[A client](https://github.com/x/client)** - Not a server
"""

INDEX = f"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>{SITE}/sitemaps/static.xml</loc></sitemap>
<sitemap><loc>{SITE}/sitemaps/servers/1.xml</loc></sitemap>
<sitemap><loc>{SITE}/sitemaps/skills.xml</loc></sitemap></sitemapindex>"""
SERVERS = f"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{SITE}/servers/modelcontextprotocol/fetch</loc></url>
<url><loc>{SITE}/ja/servers/modelcontextprotocol/fetch</loc></url>
<url><loc>{SITE}/servers/acme/postgres-mcp</loc></url>
<url><loc>{SITE}/servers/acme/postgres-mcp</loc></url></urlset>"""
SKILLS = f"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{SITE}/agent-skills/googleworkspace/gws-sheets</loc></url>
<url><loc>{SITE}/agent-skills/ast-grep/ast-grep</loc></url></urlset>"""


class FakeSite:
    def __init__(self):
        self.calls: list[str] = []
        self.down = False

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        if self.down:
            raise OSError("offline")
        return {CURATED_URL: README, SITEMAP_INDEX: INDEX, f"{SITE}/sitemaps/servers/1.xml": SERVERS, f"{SITE}/sitemaps/skills.xml": SKILLS}[url].encode()


class ParseTests(unittest.TestCase):
    def test_curated_entries_from_server_sections_only(self):
        entries = parse_curated(README)
        self.assertEqual([entry["name"] for entry in entries], ["Fetch", "BrowserStack", "Hosted", "Spotify Player"])
        self.assertEqual(entries[1]["description"], "Bring the Test Platform to your AI tools")
        self.assertEqual(entries[3]["section"], "Community")

    def test_slugs_are_english_unique_and_well_formed(self):
        locations = [f"{SITE}/servers/a/b", f"{SITE}/servers/a/b", f"{SITE}/ja/servers/a/c", f"{SITE}/servers/bad slug/x", f"{SITE}/agent-skills/o/s"]
        self.assertEqual(slugs(locations, "servers"), ["a/b"])
        self.assertEqual(slugs(locations, "agent-skills"), ["o/s"])


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.site = FakeSite()
        self.now = [1_000_000.0]
        self.directory = Directory(Path(self.dir.name) / "cache.json", fetch=self.site, clock=lambda: self.now[0])

    def test_curated_results_first_with_an_install_link_then_the_full_index(self):
        curated_only = self.directory.search("mcp", "fetch")
        self.assertEqual([r["name"] for r in curated_only["results"]], ["Fetch"])
        self.assertFalse(curated_only["index_cached"])
        self.assertNotIn(f"{SITE}/sitemaps/servers/1.xml", self.site.calls, "the big index is not downloaded unless asked")
        found = self.directory.search("mcp", "fetch", full=True)
        first = found["results"][0]
        self.assertEqual((first["name"], first["curated"]), ("Fetch", True))
        self.assertTrue(first["install_url"].startswith("https://github.com/"))
        self.assertIn("mcpservers.org/search?query=Fetch", first["page_url"])
        self.assertEqual(found["results"][1]["page_url"], f"{SITE}/servers/modelcontextprotocol/fetch")
        self.assertIsNone(found["results"][1]["install_url"], "index entries have no description or link")
        self.assertEqual(found["counts"], {"curated": 4, "index": 2})
        self.assertTrue(self.directory.search("mcp", "postgres")["index_cached"], "once downloaded, it is searched every time")
        hosted = self.directory.search("mcp", "remote")["results"][0]
        self.assertIsNone(hosted["install_url"], "only GitHub links go to the install preview")

    def test_skills_search_and_empty_queries(self):
        self.assertEqual(self.directory.search("skills", "sheets")["results"], [], "skills need the index")
        self.assertEqual([r["name"] for r in self.directory.search("skills", "sheets", full=True)["results"]], ["gws-sheets"])
        self.assertEqual(len(self.directory.search("mcp", "")["results"]), 4, "no query: the curated list only")
        with self.assertRaises(DirectoryError):
            self.directory.search("plugins", "x")

    def test_downloads_once_a_day_and_falls_back_to_the_last_list(self):
        self.directory.search("mcp", "fetch", full=True)
        downloads = len(self.site.calls)
        Directory(self.directory.cache_path, fetch=self.site, clock=lambda: self.now[0]).search("mcp", "spotify")
        self.assertEqual(len(self.site.calls), downloads, "a fresh cache file is used, nothing downloaded")
        self.now[0] += 25 * 60 * 60
        self.site.down = True
        found = self.directory.search("mcp", "spotify")
        self.assertEqual(found["results"][0]["name"], "Spotify Player")
        self.assertEqual(self.directory.search("mcp", "postgres")["results"][0]["name"], "postgres-mcp", "the weekly index is still fresh")
        self.assertIn("last download", found["note"])

    def test_nothing_cached_and_offline_is_a_clear_error(self):
        self.site.down = True
        with self.assertRaises(DirectoryError) as caught:
            self.directory.search("mcp", "fetch")
        self.assertIn("could not be reached", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
