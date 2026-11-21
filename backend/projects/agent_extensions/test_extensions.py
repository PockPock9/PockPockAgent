"""Unit tests for agent extensions. GitHub, the OpenClaw gateway and MCP servers are faked."""

from __future__ import annotations

import io
import json
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from projects.agent_extensions import mcp_probe
from projects.agent_extensions.service import PROPOSAL_TTL_SECONDS, ExtensionError, ExtensionService
from projects.agent_extensions.sources import Snapshot, SourceError, find_mcp, find_skills, parse_link

COMMIT = "a" * 40


def archive(files: dict[str, str | bytes], root: str = "repo-main", links: tuple[str, ...] = ()) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.comment = COMMIT.encode()
        for name, content in files.items():
            info = zipfile.ZipInfo(f"{root}/{name}")
            if name in links:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(info, content)
    return buffer.getvalue()


SKILL = "---\nname: PDF Tools\ndescription: >\n  Work with PDF files.\n  Second line.\n---\nBody\n"


class FakeGateway:
    def __init__(self):
        self.servers: dict[str, dict] = {}
        self.requests: list[dict] = []
        self.offline = False
        self.disabled_skills: set[str] = set()
        self.skills = [
            {"name": "weather", "key": "weather", "description": "Forecasts", "source": "openclaw-bundled", "eligible": True, "missing": []},
            {"name": "github", "key": "github", "description": "GitHub CLI", "source": "openclaw-bundled", "eligible": False, "missing": ["gh"]},
        ]

    def run(self, request):
        self.requests.append(request)
        if self.offline:
            raise ExtensionError("gateway_offline", "The OpenClaw gateway is not running.", 503)
        if request["op"] == "mcp_list":
            return {"ok": True, "servers": {name: {"transport": "stdio", "command": server.get("command", ""), "args": server.get("args", []), "url": server.get("url", ""), "enabled": server.get("enabled", True)} for name, server in self.servers.items()}}
        if request["op"] == "skills_list":
            # Like OpenClaw, a switched-off skill is reported as not eligible.
            return {"ok": True, "skills": [dict(skill, disabled=skill["key"] in self.disabled_skills, eligible=skill["eligible"] and skill["key"] not in self.disabled_skills) for skill in self.skills]}
        if request["op"] == "skill_enable":
            (self.disabled_skills.discard if request["enabled"] else self.disabled_skills.add)(request["name"])
        if request["op"] == "mcp_enable":
            if request["name"] not in self.servers:
                raise ExtensionError("not_found", "no such server", 404)
            self.servers[request["name"]]["enabled"] = request["enabled"]
        if request["op"] == "mcp_set":
            if request["name"] in self.servers and not request.get("replace"):
                raise ExtensionError("exists", "already there", 409)
            self.servers[request["name"]] = request["server"]
        if request["op"] == "mcp_remove":
            self.servers.pop(request["name"], None)
        return {"ok": True}


class LinkTests(unittest.TestCase):
    def test_github_forms(self):
        link = parse_link("https://github.com/anthropics/skills")
        self.assertEqual((link.kind, link.owner, link.repo, link.ref, link.path), ("github", "anthropics", "skills", "", ""))
        link = parse_link("https://github.com/o/r.git")
        self.assertEqual(link.repo, "r")
        link = parse_link("https://github.com/o/r/tree/main/skills/pdf")
        self.assertEqual((link.ref, link.path), ("main", "skills/pdf"))
        link = parse_link("https://github.com/o/r/blob/v1.2/skills/pdf/SKILL.md")
        self.assertEqual((link.ref, link.path), ("v1.2", "skills/pdf"))

    def test_remote_links(self):
        self.assertEqual(parse_link("https://mcp.example.com/mcp").kind, "remote")
        self.assertEqual(parse_link("http://localhost:3000/mcp").kind, "remote")

    def test_rejected_links(self):
        for bad in [
            "", "not a link", "ftp://github.com/o/r", "http://github.com/o/r", "http://example.com/mcp",
            "https://user:pw@example.com/mcp", "https://github.com/o", "https://github.com/o/r/issues/3",
            "https://github.com/o/r/tree/main/../../etc", "https://github.com/o/r/tree/main/.git/hooks",
            "https://github.com/o/r two", "https://example.com/" + "a" * 600, "https://example.com:99999/x",
        ]:
            with self.assertRaises(SourceError, msg=bad):
                parse_link(bad)


class DiscoveryTests(unittest.TestCase):
    def snapshot(self, files, url="https://github.com/o/repo"):
        return Snapshot(archive(files), parse_link(url))

    def test_finds_skills_and_reads_frontmatter(self):
        snapshot = self.snapshot({"skills/pdf/SKILL.md": SKILL, "skills/pdf/scripts/run.py": "x", "skills/docx/SKILL.md": "no header", "README.md": "hi"})
        skills = {skill.slug: skill for skill in find_skills(snapshot)}
        self.assertEqual(set(skills), {"pdf-tools", "docx"})
        self.assertEqual(skills["pdf-tools"].description, "Work with PDF files. Second line.")
        self.assertTrue(skills["pdf-tools"].has_scripts)
        self.assertFalse(skills["docx"].has_scripts)
        self.assertEqual(snapshot.commit, COMMIT)

    def test_subpath_limits_discovery(self):
        files = {"skills/pdf/SKILL.md": SKILL, "skills/docx/SKILL.md": SKILL}
        skills = find_skills(self.snapshot(files, "https://github.com/o/repo/tree/main/skills/docx"))
        self.assertEqual([skill.path for skill in skills], ["skills/docx"])
        with self.assertRaises(SourceError):
            self.snapshot(files, "https://github.com/o/repo/tree/main/missing")

    def test_skill_at_repository_root_and_duplicate_names(self):
        skills = find_skills(self.snapshot({"SKILL.md": "---\nname: \"Root\"\n---\n", "a/SKILL.md": "---\nname: Root\n---\n"}))
        self.assertEqual(sorted(skill.slug for skill in skills), ["root", "root-2"])

    def test_mcp_from_readme_prefers_npx_and_drops_env_values(self):
        readme = (
            "Docker:\n```json\n{\"mcpServers\": {\"x\": {\"command\": \"docker\", \"args\": [\"run\", \"img\"]}}}\n```\n"
            "NPX:\n```json\n{\"mcpServers\": {\"x\": {\"command\": \"npx\", \"args\": [\"-y\", \"@scope/server\"], \"env\": {\"API_KEY\": \"sk-real-looking\"}}}}\n```\n"
        )
        mcp = find_mcp(self.snapshot({"README.md": readme}))
        self.assertEqual((mcp.command, mcp.args, mcp.env), ("npx", ("-y", "@scope/server"), {"API_KEY": ""}))
        self.assertEqual(mcp.name, "repo")

    def test_mcp_refuses_unknown_launcher(self):
        readme = "```json\n{\"mcpServers\": {\"x\": {\"command\": \"powershell\", \"args\": [\"-c\", \"evil\"]}}}\n```"
        self.assertIsNone(find_mcp(self.snapshot({"README.md": readme})))

    def test_mcp_from_package_and_pyproject(self):
        mcp = find_mcp(self.snapshot({"package.json": json.dumps({"name": "@scope/tool-mcp", "bin": {"tool": "cli.js"}})}))
        self.assertEqual((mcp.command, mcp.args), ("npx", ("-y", "@scope/tool-mcp")))
        self.assertIsNone(find_mcp(self.snapshot({"package.json": json.dumps({"name": "app", "bin": "x.js", "private": True})})))
        self.assertIsNone(find_mcp(self.snapshot({"package.json": json.dumps({"name": "library"})})))
        mcp = find_mcp(self.snapshot({"pyproject.toml": "[project]\nname = \"tool-mcp\"\n[project.scripts]\ntool = \"tool:main\"\n"}))
        self.assertEqual((mcp.command, mcp.args), ("uvx", ("tool-mcp",)))

    def test_remote_url_in_readme(self):
        mcp = find_mcp(self.snapshot({"README.md": "```json\n{\"mcpServers\": {\"x\": {\"url\": \"https://mcp.example.com/mcp\"}}}\n```"}))
        self.assertEqual((mcp.transport, mcp.url), ("streamable-http", "https://mcp.example.com/mcp"))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.gateway = FakeGateway()
        self.files: dict[str, str | bytes] = {"skills/pdf/SKILL.md": SKILL, "skills/pdf/ref/notes.md": "notes"}
        self.links: tuple[str, ...] = ()
        self.fetched = 0
        self.probes: list[tuple] = []
        self.now = 1000.0
        self.service = ExtensionService(
            state_dir=self.state, fetch=self.fetch, gateway=self.gateway,
            probe_stdio=self.probe_stdio, probe_http=self.probe_http, clock=lambda: self.now,
        )

    def fetch(self, link):
        self.fetched += 1
        return archive(self.files, links=self.links)

    def probe_stdio(self, command, args, env):
        self.probes.append((command, args, env))
        return [{"name": "shout", "description": "Upper case"}]

    def probe_http(self, url, headers):
        self.probes.append((url, headers))
        return [{"name": "search", "description": ""}]

    def test_inspect_installs_nothing(self):
        proposal = self.service.inspect("https://github.com/o/repo")
        self.assertEqual(proposal["kind"], "skills")
        self.assertEqual(proposal["skills"][0]["slug"], "pdf-tools")
        self.assertEqual(proposal["commit"], COMMIT)
        self.assertFalse((self.state / "skills").exists())
        self.assertEqual(self.probes, [])

    def test_install_skill_then_list_and_remove(self):
        proposal = self.service.inspect("https://github.com/o/repo")
        result = self.service.install(proposal["id"], ["pdf-tools"])
        self.assertEqual(result["installed"], [{"slug": "pdf-tools", "name": "PDF Tools"}])
        self.assertTrue((self.state / "skills" / "pdf-tools" / "SKILL.md").is_file())
        self.assertTrue((self.state / "skills" / "pdf-tools" / "ref" / "notes.md").is_file())
        listed = self.service.list()
        self.assertEqual([skill["slug"] for skill in listed["skills"]], ["pdf-tools"])
        self.assertFalse(listed["skills"][0]["missing"])
        self.service.remove("skill", "pdf-tools")
        self.assertFalse((self.state / "skills" / "pdf-tools").exists())
        self.assertEqual(self.service.list()["skills"], [])

    def test_proposal_is_single_use_and_expires(self):
        proposal = self.service.inspect("https://github.com/o/repo")
        self.service.install(proposal["id"])
        with self.assertRaises(ExtensionError) as caught:
            self.service.install(proposal["id"])
        self.assertEqual(caught.exception.status_code, 410)
        proposal = self.service.inspect("https://github.com/o/repo")
        self.now += PROPOSAL_TTL_SECONDS + 1
        with self.assertRaises(ExtensionError):
            self.service.install(proposal["id"])
        with self.assertRaises(ExtensionError):
            self.service.install("unknown")

    def test_install_uses_previewed_archive_not_a_new_download(self):
        proposal = self.service.inspect("https://github.com/o/repo")
        self.files = {"skills/pdf/SKILL.md": "---\nname: PDF Tools\n---\nCHANGED AFTER PREVIEW"}
        self.service.install(proposal["id"])
        self.assertEqual(self.fetched, 1)
        self.assertIn("Body", (self.state / "skills" / "pdf-tools" / "SKILL.md").read_text())

    def test_unknown_selection_and_foreign_skill_are_refused(self):
        proposal = self.service.inspect("https://github.com/o/repo")
        with self.assertRaises(ExtensionError):
            self.service.install(proposal["id"], ["other"])
        with self.assertRaises(ExtensionError):
            self.service.install(proposal["id"], [])
        foreign = self.state / "skills" / "pdf-tools"
        foreign.mkdir(parents=True)
        (foreign / "SKILL.md").write_text("mine")
        self.assertTrue(self.service.inspect("https://github.com/o/repo")["skills"][0]["conflict"])
        with self.assertRaises(ExtensionError) as caught:
            self.service.install(proposal["id"])
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual((foreign / "SKILL.md").read_text(), "mine")
        with self.assertRaises(ExtensionError):
            self.service.remove("skill", "pdf-tools")
        self.assertTrue(foreign.exists())

    def test_symlink_and_traversal_are_refused(self):
        self.files = {"s/SKILL.md": SKILL, "s/link": "/etc/passwd"}
        self.links = ("s/link",)
        proposal = self.service.inspect("https://github.com/o/repo")
        with self.assertRaises(ExtensionError):
            self.service.install(proposal["id"])
        self.assertFalse((self.state / "skills" / "pdf-tools").exists())
        self.links = ()
        self.files = {"s/SKILL.md": SKILL, "s/../../escape.txt": "x"}
        proposal = self.service.inspect("https://github.com/o/repo")
        with self.assertRaises(ExtensionError):
            self.service.install(proposal["id"])
        self.assertFalse((self.state / "escape.txt").exists())
        self.assertEqual([path.name for path in (self.state / "skills").iterdir()], [])

    def test_unrecognized_repository(self):
        self.files = {"README.md": "just a library"}
        with self.assertRaises(ExtensionError) as caught:
            self.service.inspect("https://github.com/o/repo")
        self.assertEqual(caught.exception.status_code, 422)

    def test_mcp_stdio_probe_then_save(self):
        self.files = {"README.md": "```json\n{\"mcpServers\": {\"x\": {\"command\": \"npx\", \"args\": [\"-y\", \"pkg\", \"/path/to/dir\"], \"env\": {\"API_KEY\": \"<key>\"}}}}\n```"}
        proposal = self.service.inspect("https://github.com/o/repo")
        self.assertEqual(proposal["mcp"]["env_keys"], ["API_KEY"])
        self.assertEqual(self.gateway.requests, [])
        result = self.service.install(proposal["id"], args=["-y", "pkg", "C:/data"], env={"API_KEY": " secret "})
        self.assertEqual(self.probes, [("npx", ["-y", "pkg", "C:/data"], {"API_KEY": "secret"})])
        self.assertEqual(self.gateway.servers["repo"], {"command": "npx", "args": ["-y", "pkg", "C:/data"], "env": {"API_KEY": "secret"}})
        self.assertEqual(result["tools"][0]["name"], "shout")
        listed = self.service.list()["mcp"]
        self.assertEqual((listed[0]["name"], listed[0]["managed"]), ("repo", True))
        self.assertNotIn("secret", json.dumps(self.service.list()))
        self.service.remove("mcp", "repo")
        self.assertEqual(self.gateway.servers, {})

    def test_mcp_failed_probe_saves_nothing(self):
        self.files = {"README.md": "```json\n{\"mcpServers\": {\"x\": {\"command\": \"npx\", \"args\": [\"pkg\"]}}}\n```"}

        def failing(command, args, env):
            raise mcp_probe.ProbeError("The server stopped before answering.")

        self.service.probe_stdio = failing
        proposal = self.service.inspect("https://github.com/o/repo")
        with self.assertRaises(ExtensionError) as caught:
            self.service.install(proposal["id"])
        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(self.gateway.servers, {})
        self.assertEqual(self.service.list()["mcp"], [])

    def test_mcp_rejects_bad_args_and_unrequested_env(self):
        self.files = {"README.md": "```json\n{\"mcpServers\": {\"x\": {\"command\": \"npx\", \"args\": [\"pkg\"]}}}\n```"}
        for kwargs in ({"args": ["ok", ""]}, {"args": ["x" * 501]}, {"args": ["a"] * 41}, {"env": {"PATH": "evil"}}):
            proposal = self.service.inspect("https://github.com/o/repo")
            with self.assertRaises(ExtensionError):
                self.service.install(proposal["id"], **kwargs)
        self.assertEqual(self.probes, [])

    def test_existing_foreign_server_is_not_replaced_or_removed(self):
        self.gateway.servers["repo"] = {"command": "node", "args": ["mine.js"]}
        self.files = {"README.md": "```json\n{\"mcpServers\": {\"x\": {\"command\": \"npx\", \"args\": [\"pkg\"]}}}\n```"}
        proposal = self.service.inspect("https://github.com/o/repo")
        with self.assertRaises(ExtensionError) as caught:
            self.service.install(proposal["id"])
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.gateway.servers["repo"]["command"], "node")
        self.assertFalse(self.service.list()["mcp"][0]["managed"])
        with self.assertRaises(ExtensionError):
            self.service.remove("mcp", "repo")

    def test_remote_server_with_authorization(self):
        proposal = self.service.inspect("https://mcp.example.com/mcp")
        self.assertEqual(self.fetched, 0)
        self.assertEqual((proposal["mcp"]["transport"], proposal["mcp"]["name"]), ("streamable-http", "example"))
        self.service.install(proposal["id"], authorization="Bearer abc")
        self.assertEqual(self.probes, [("https://mcp.example.com/mcp", {"Authorization": "Bearer abc"})])
        self.assertEqual(self.gateway.servers["example"], {"url": "https://mcp.example.com/mcp", "transport": "streamable-http", "headers": {"Authorization": "Bearer abc"}})

    def test_sse_server_is_saved_unverified(self):
        proposal = self.service.inspect("https://mcp.example.com/sse")
        result = self.service.install(proposal["id"])
        self.assertEqual((result["verified"], self.probes), (False, []))

    def test_list_reports_gateway_offline(self):
        self.gateway.offline = True
        listed = self.service.list()
        self.assertFalse(listed["openclaw_ready"])
        self.assertIn("not running", listed["detail"])

    def test_repository_with_both_kinds_offers_the_other(self):
        readme = "```json\n" + json.dumps({"mcpServers": {"x": {"command": "npx", "args": ["pkg"]}}}) + "\n```"
        self.files = {"README.md": readme, "skills/a/SKILL.md": SKILL, "skills/b/SKILL.md": SKILL, "skills/c/SKILL.md": SKILL}
        proposal = self.service.inspect("https://github.com/o/repo")
        self.assertEqual((proposal["kind"], proposal["also"]), ("mcp", "skills"))
        proposal = self.service.inspect("https://github.com/o/repo", "skills")
        self.assertEqual((proposal["kind"], proposal["also"]), ("skills", "mcp"))
        self.assertEqual([skill["slug"] for skill in proposal["skills"]], ["pdf-tools", "pdf-tools-2", "pdf-tools-3"])
        self.files = {"package.json": json.dumps({"name": "tool", "bin": "x.js"}), "skills/a/SKILL.md": SKILL}
        self.assertEqual(self.service.inspect("https://github.com/o/repo")["kind"], "skills")

    def test_toggle_skills_and_servers(self):
        listed = self.service.list()
        self.assertEqual([(skill["name"], skill["ready"], skill["enabled"]) for skill in listed["builtin_skills"]], [("weather", True, True), ("github", False, True)])
        self.assertEqual(listed["builtin_skills"][1]["needs"], ["gh"])
        self.service.set_enabled("skill", "weather", False)
        switched_off = self.service.list()["builtin_skills"][0]
        self.assertEqual((switched_off["name"], switched_off["enabled"], switched_off["ready"]), ("weather", False, True))
        self.service.set_enabled("skill", "weather", True)
        self.assertTrue(self.service.list()["builtin_skills"][0]["enabled"])
        for kind, name in (("skill", "unknown"), ("mcp", "unknown"), ("plugin", "weather"), ("skill", "../x")):
            with self.assertRaises(ExtensionError):
                self.service.set_enabled(kind, name, False)
        self.gateway.servers["files"] = {"command": "node", "args": []}
        self.service.set_enabled("mcp", "files", False)
        self.assertFalse(self.service.list()["mcp"][0]["enabled"])

    def test_installed_skill_is_matched_to_openclaws_name(self):
        proposal = self.service.inspect("https://github.com/o/repo")
        self.service.install(proposal["id"])
        self.gateway.skills.append({"name": "PDF Tools", "key": "PDF Tools", "description": "", "source": "openclaw-managed", "eligible": True, "missing": []})
        self.gateway.disabled_skills.add("PDF Tools")
        listed = self.service.list()
        self.assertEqual((listed["skills"][0]["key"], listed["skills"][0]["enabled"]), ("PDF Tools", False))
        self.assertNotIn("PDF Tools", [skill["name"] for skill in listed["builtin_skills"]])
        self.service.remove("skill", "pdf-tools")
        self.gateway.skills.append({"name": "pdf-tools", "key": "pdf-tools", "description": "", "source": "openclaw-managed", "eligible": True, "missing": []})
        names = [skill["name"] for skill in self.service.list()["builtin_skills"]]
        self.assertNotIn("pdf-tools", names)  # still reported by OpenClaw, but its folder is gone
        self.assertNotIn("pdf-tools", self.gateway.disabled_skills)

    def test_cancel_discards_the_preview(self):
        proposal = self.service.inspect("https://github.com/o/repo")
        self.service.cancel(proposal["id"])
        with self.assertRaises(ExtensionError):
            self.service.install(proposal["id"])


class IssueFixTests(unittest.TestCase):
    """Fixes from the 2026-11 issue review (#63, #64, #65, #87, #88, #89)."""

    # Same fixtures as ServiceTests, without running its tests a second time.
    setUp = ServiceTests.setUp
    fetch = ServiceTests.fetch
    probe_stdio = ServiceTests.probe_stdio
    probe_http = ServiceTests.probe_http

    def test_a_skill_without_a_header_gets_one(self):
        # Issue #87: OpenClaw silently skips a SKILL.md without name and description.
        self.files = {"skills/probe/SKILL.md": "# Probe skill\n\nAnswer with PROBE-OK when asked.\n"}
        proposal = self.service.inspect("https://github.com/o/repo")
        skill = proposal["skills"][0]
        self.assertTrue(skill["adds_header"])
        self.assertEqual(skill["description"], "Answer with PROBE-OK when asked.")
        self.service.install(proposal["id"], ["probe"])
        text = (self.state / "skills" / "probe" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith('---\nname: "probe"\ndescription: "Answer with PROBE-OK when asked."\n---\n'))
        self.assertIn("# Probe skill", text)

    def test_a_skill_with_a_header_is_left_alone(self):
        proposal = self.service.inspect("https://github.com/o/repo")
        self.assertFalse(proposal["skills"][0]["adds_header"])
        self.service.install(proposal["id"], ["pdf-tools"])
        self.assertEqual((self.state / "skills" / "pdf-tools" / "SKILL.md").read_text(encoding="utf-8"), SKILL)

    def test_a_header_missing_only_the_description_is_completed(self):
        self.files = {"skills/x/SKILL.md": "---\nname: x-tool\n---\nUse the x tool.\n"}
        proposal = self.service.inspect("https://github.com/o/repo")
        self.service.install(proposal["id"], [proposal["skills"][0]["slug"]])
        text = (self.state / "skills" / "x-tool" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(text, '---\ndescription: "Use the x tool."\nname: x-tool\n---\nUse the x tool.\n')

    def test_a_repository_of_server_folders_lists_them(self):
        # Issue #64: modelcontextprotocol/servers keeps each server in src/<name>.
        block = lambda pkg: "```json\n" + json.dumps({"mcpServers": {"x": {"command": "npx", "args": ["-y", pkg]}}}) + "\n```"
        self.files = {"README.md": "# Servers\nSee each folder.", "src/fetch/README.md": block("fetch"), "src/git/README.md": block("git"), "src/notes/README.md": "no server here"}
        with self.assertRaises(ExtensionError) as caught:
            self.service.inspect("https://github.com/o/repo")
        self.assertEqual(caught.exception.code, "choose_folder")
        self.assertIn("2 MCP servers", str(caught.exception))
        self.files["skills/pdf/SKILL.md"] = SKILL
        proposal = self.service.inspect("https://github.com/o/repo")
        self.assertEqual(proposal["kind"], "skills")
        self.assertEqual([item["path"] for item in proposal["mcp_folders"]], ["src/fetch", "src/git"])
        self.assertEqual(proposal["mcp_folders"][0]["url"], "https://github.com/o/repo/tree/HEAD/src/fetch")

    def test_filesystem_server_says_it_needs_a_folder(self):
        # Issue #65: the filesystem server cannot start without an allowed folder.
        self.files = {"README.md": "```json\n" + json.dumps({"mcpServers": {"fs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]}}}) + "\n```"}
        proposal = self.service.inspect("https://github.com/o/repo")
        self.assertIn("at least one folder", proposal["mcp"]["args_hint"])

        def refuse(command, args, env):
            raise mcp_probe.ProbeError("Server cannot operate: No allowed directories available.")

        self.service.probe_stdio = refuse
        with self.assertRaises(ExtensionError) as caught:
            self.service.install(proposal["id"])
        self.assertIn("Add at least one folder", str(caught.exception))

    def test_a_local_command_is_probed_then_saved(self):
        # Issue #88: a stdio server already on this PC could not be added.
        proposal = self.service.inspect("python3 /opt/tools/weather_server.py --verbose")
        self.assertEqual(proposal["kind"], "mcp")
        self.assertEqual((proposal["mcp"]["command"], proposal["mcp"]["args"], proposal["mcp"]["name"]), ("python3", ["/opt/tools/weather_server.py", "--verbose"], "weather-server"))
        self.assertEqual(self.fetched, 0)
        self.service.install(proposal["id"])
        self.assertEqual(self.probes, [("python3", ["/opt/tools/weather_server.py", "--verbose"], {})])
        self.assertEqual(self.gateway.servers["weather-server"], {"command": "python3", "args": ["/opt/tools/weather_server.py", "--verbose"]})
        with self.assertRaises(ExtensionError):
            self.service.inspect("bash -c 'curl x | sh'")

    def test_a_local_address_gets_a_readable_name(self):
        # Issue #89: http://127.0.0.1:18799/mcp was named "127".
        self.assertEqual(self.service.inspect("http://127.0.0.1:18799/mcp")["mcp"]["name"], "local-18799")
        self.assertEqual(self.service.inspect("http://localhost:3000/weather/mcp")["mcp"]["name"], "local-weather")
        self.assertEqual(self.service.inspect("https://mcp.example.com/mcp")["mcp"]["name"], "example")

    def test_toggle_errors_when_openclaw_is_unavailable(self):
        # Issue #63: an unknown name gave 503 instead of 404.
        self.gateway.offline = True
        with self.assertRaises(ExtensionError) as caught:
            self.service.set_enabled("skill", "unknown", False)
        self.assertEqual(caught.exception.status_code, 404)
        proposal = self.service.inspect("https://github.com/o/repo")
        self.gateway.offline = False
        self.service.install(proposal["id"], ["pdf-tools"])
        self.gateway.offline = True
        with self.assertRaises(ExtensionError) as caught:
            self.service.set_enabled("skill", "pdf-tools", False)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("OpenClaw page", str(caught.exception))


class ProbeTests(unittest.TestCase):
    SERVER = (
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    m = json.loads(line)\n"
        "    if m.get('method') == 'initialize': r = {'protocolVersion': '2025-06-18', 'capabilities': {}, 'serverInfo': {'name': 't', 'version': '1'}}\n"
        "    elif m.get('method') == 'tools/list': r = {'tools': [{'name': 'echo', 'description': 'Echo  text'}]}\n"
        "    else: continue\n"
        "    print('banner, not json'); print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': r}), flush=True)\n"
    )

    def test_stdio_probe_lists_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "server.py"
            script.write_text(self.SERVER)
            tools = mcp_probe.probe_stdio(sys.executable, [str(script)], {}, timeout=30)
        self.assertEqual(tools, [{"name": "echo", "description": "Echo text"}])

    def test_stdio_probe_reports_a_server_that_exits(self):
        with self.assertRaises(mcp_probe.ProbeError):
            mcp_probe.probe_stdio(sys.executable, ["-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"], {}, timeout=30)

    def test_missing_launcher_and_unsafe_cmd_arguments(self):
        with self.assertRaises(mcp_probe.ProbeError):
            mcp_probe.resolve_command("definitely-not-installed-launcher")
        with self.assertRaises(mcp_probe.ProbeError):
            mcp_probe.check_arguments("C:/x/npx.cmd", ["-y", "pkg & calc"])
        mcp_probe.check_arguments("C:/x/npx.cmd", ["-y", "@scope/pkg", "C:/data dir"])
        mcp_probe.check_arguments("C:/x/node.exe", ["a & b"])


if __name__ == "__main__":
    unittest.main()
