"""Tests for the Phase 1 tool retriever (BM25 + deterministic routing)."""

import unittest

from projects.agent_tools.tool_retriever import (
    CORE_TOOL_NAMES,
    ToolRetriever,
    estimate_tokens,
    tool_retrieval_enabled,
)


class ToolRetrieverTests(unittest.TestCase):
    def setUp(self):
        # Keyword-only: no Ollama dependency in unit tests.
        self.retriever = ToolRetriever(dense_enabled=False)

    def test_index_comes_from_the_registry(self):
        names = {doc.name for doc in self.retriever.docs}
        self.assertEqual(len(names), len(self.retriever.docs))
        for expected in (
            "search_public_site",
            "save_text_artifact",
            "list_project_files",
            "validate_project",
        ):
            self.assertIn(expected, names)

    def test_one_line_index_covers_every_tool(self):
        lines = [doc.one_line for doc in self.retriever.docs]
        self.assertEqual(len(lines), len(self.retriever.docs))
        for doc, line in zip(self.retriever.docs, lines):
            self.assertIn(doc.name, line)
            self.assertIn(doc.category, line)

    def test_retrieves_the_right_tool_for_sample_queries(self):
        cases = {
            "research the pricing on example.com and cite sources": "search_public_site",
            "save the results as a markdown file": "save_text_artifact",
            "make a PowerPoint deck for the team meeting": "create_office_document",
            "generate an image of a lighthouse": "generate_local_image",
            "what files are in this project": "list_project_files",
            "find where the login handler is defined in the code": "search_project",
            "fix the crash when the list is empty": "propose_project_edit",
            "build a snake game I can play in the browser": "propose_project_patch",
            "check the project is valid before I finish": "validate_project",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                result = self.retriever.retrieve(query)
                self.assertIn(expected, result.selected_names[:5], result.selected_names)

    def test_deterministic_routing_pins_high_confidence_intents(self):
        result = self.retriever.retrieve("make a Word document of the report")
        self.assertEqual(result.method, "deterministic")
        self.assertEqual(result.selected_names[0], "create_office_document")

    def test_deterministic_routing_pins_named_code_files(self):
        # Real-request misses from the eval (scenarios-1000 #282, #296):
        # a write/fix verb aimed at a named code file pins the patch/edit.
        patch = self.retriever.retrieve(
            "In my workspace, write csv2json.py: it reads a CSV file given on the "
            "command line, converts it to JSON with numbers as numbers, and writes "
            "it to an output file. Handle empty values as null."
        )
        self.assertEqual(patch.selected_names[0], "propose_project_patch")
        edit = self.retriever.retrieve(
            "In my workspace, fix parser.py: names with accented letters and emoji "
            "are mangled on a parse/export round trip."
        )
        self.assertEqual(edit.selected_names[0], "propose_project_edit")

    def test_fetch_api_is_not_a_scrape_verb(self):
        # "Fetch API" is a product name, not the verb "fetch" — it must not
        # pin scrape_public_page (scenarios-1000 #405). BM25 may still rank
        # the single-page tool first; that ranking miss is recorded in the
        # eval, not hidden by a pin.
        result = self.retriever.retrieve(
            "Using developer.mozilla.org, summarize what the Fetch API does and cite the page."
        )
        self.assertNotEqual(result.method, "deterministic")

    def test_core_tools_are_always_included_when_permitted(self):
        result = self.retriever.retrieve("research the docs on example.com")
        for core in CORE_TOOL_NAMES:
            self.assertIn(core, result.selected_names)

    def test_low_confidence_query_falls_back_to_the_full_list(self):
        result = self.retriever.retrieve("zzzqqq wobble florp")
        self.assertEqual(result.method, "fallback-full")
        self.assertEqual(len(result.selected_names), len(self.retriever.docs))

    def test_permitted_filter_restricts_the_selection(self):
        result = self.retriever.retrieve(
            "save the results as a markdown file",
            permitted=["save_text_artifact", "search_public_site"],
        )
        self.assertEqual(set(result.selected_names), {"save_text_artifact", "search_public_site"})

    def test_default_mode_filters_out_full_access_tools_before_ranking(self):
        # "fix the bug in counter.py" matches propose_project_edit strongly;
        # in default mode the workspace tools must never appear — not in the
        # selection, not in the scores, not in the one-line index.
        result = self.retriever.retrieve(
            "fix the bug in counter.py: the loop counts 1 to 10 but should count 0 to 9",
            permission_mode="default",
        )
        self.assertNotIn("propose_project_edit", result.selected_names)
        self.assertNotIn("propose_project_edit", result.scores)
        self.assertTrue(
            all("propose_project_edit" not in line for line in result.index_lines)
        )
        self.assertIn("propose_project_edit", result.filtered_out)
        self.assertIn("permission", result.filtered_out["propose_project_edit"])
        for name in ("list_project_files", "search_project", "read_project_file",
                     "propose_project_patch", "validate_project"):
            self.assertNotIn(name, result.selected_names, name)
            self.assertIn(name, result.filtered_out, name)

    def test_high_risk_tools_need_an_explicit_allowance(self):
        query = "fix the bug in counter.py and check the project still builds"
        allowed = self.retriever.retrieve(query, permission_mode="full-access")
        self.assertIn("propose_project_edit", allowed.selected_names)
        self.assertIn("validate_project", allowed.selected_names)
        denied = self.retriever.retrieve(query, permission_mode="full-access", allow_high_risk=False)
        self.assertNotIn("propose_project_edit", denied.selected_names)
        self.assertNotIn("validate_project", denied.selected_names)
        self.assertIn("propose_project_edit", denied.filtered_out)
        self.assertIn("risk", denied.filtered_out["propose_project_edit"])
        # Auto-review allows high-risk tools: the executor approval-gates them.
        review = self.retriever.retrieve(query, permission_mode="auto-review")
        self.assertIn("propose_project_edit", review.selected_names)

    def test_read_only_tools_survive_default_mode_filtering(self):
        result = self.retriever.retrieve(
            "research the docs on example.com and cite your sources",
            permission_mode="default",
        )
        self.assertIn("search_public_site", result.selected_names)
        # Workspace tools are filtered in default mode, by permission —
        # but the research tool itself must never be filtered out.
        self.assertNotIn("search_public_site", result.filtered_out)
        self.assertIn("permission", result.filtered_out["propose_project_edit"])

    def test_filter_helper_reports_reasons(self):
        from projects.agent_tools.tool_retriever import filter_permitted_tools

        allowed, filtered = filter_permitted_tools(
            self.retriever.contracts_by_name, permission_mode="default"
        )
        self.assertIn("search_public_site", allowed)
        self.assertIn("save_text_artifact", allowed)
        self.assertNotIn("propose_project_edit", allowed)
        self.assertEqual(
            set(filtered),
            {"list_project_files", "search_project", "read_project_file",
             "propose_project_edit", "propose_project_patch", "validate_project"},
        )

    def test_unknown_side_effect_fails_closed_to_high_risk(self):
        from projects.agent_tools.contracts import ToolContract, risk_level_for_side_effect

        self.assertEqual(risk_level_for_side_effect("teleport_to_mars"), "high")
        self.assertEqual(risk_level_for_side_effect("workspace_read"), "read")
        self.assertEqual(risk_level_for_side_effect("task_artifact_write"), "write")
        contract = ToolContract(
            name="mystery_tool", capability="workspace_read",
            required_permission="default", side_effect="teleport_to_mars",
            timeout_seconds=10, max_input_bytes=1000, max_output_bytes=1000,
            description="mystery tool", input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object", "properties": {}},
        )
        self.assertEqual(contract.risk_level, "high")

    def test_select_tools_returns_schemas_and_index(self):
        from projects.agent_tools import registered_tool_specs

        specs, retrieval = self.retriever.select_tools(
            "save the results as a markdown file", registered_tool_specs()
        )
        names = [spec["function"]["name"] for spec in specs]
        self.assertIn("save_text_artifact", names)
        # Top 8 + 2 core tools + the search_tools escape hatch.
        self.assertLessEqual(len(names), 11)
        self.assertEqual(len(retrieval.index_lines), len(registered_tool_specs()))
        self.assertLess(retrieval.tokens_after, retrieval.tokens_before)

    def test_search_tools_is_always_included_but_never_ranked(self):
        # "search the codebase" must rank search_project, not the meta-tool.
        result = self.retriever.retrieve("search the codebase for this error message")
        self.assertIn("search_tools", result.selected_names)
        self.assertNotIn("search_tools", result.scores)
        self.assertIn("search_project", result.selected_names[:5])
        # It is appended beyond top-k, like the core tools.
        self.assertEqual(result.selected_names[-1], "search_tools")

    def test_hydrate_tools_adds_only_permitted_new_tools(self):
        from projects.agent_tools import registered_tool_specs
        from projects.agent_tools.tool_retriever import hydrate_tools

        current, _ = self.retriever.select_tools(
            "save the results as a markdown file", registered_tool_specs()
        )
        search_result = {
            "query": "click the login link on the page",
            "results": [
                {"name": "browser_action", "one_line": "x", "score": 0.9},
                {"name": "save_text_artifact", "one_line": "x", "score": 0.8},
                {"name": "teleport_to_mars", "one_line": "x", "score": 1.0},
            ],
            "method": "keyword",
        }
        added = hydrate_tools(current, search_result, registered_tool_specs())
        added_names = [spec["function"]["name"] for spec in added]
        self.assertEqual(added_names, ["browser_action"])
        # Idempotent: a second hydration adds nothing already present.
        self.assertEqual(
            hydrate_tools(current + added, search_result, registered_tool_specs()), []
        )
        self.assertEqual(hydrate_tools(current, None, registered_tool_specs()), [])
        self.assertEqual(hydrate_tools(current, {"results": "nope"}, registered_tool_specs()), [])

    def test_status_reports_keyword_only_fallback(self):
        status = self.retriever.status()
        self.assertEqual(status["tools"], len(self.retriever.docs))
        self.assertIs(status["dense_available"], False)
        self.assertIn("keyword-only", status["fallback_note"])
        self.assertIn("nomic-embed-text-v2-moe", status["fallback_note"])

    def test_retrieval_is_fast(self):
        result = self.retriever.retrieve("research the docs on example.com")
        self.assertLess(result.latency_ms, 50.0)

    def test_flag_defaults_on_and_env_can_switch_it_off(self):
        import os

        self.assertTrue(tool_retrieval_enabled())
        os.environ["POCKPOCK_TOOL_RETRIEVAL_ENABLED"] = "0"
        try:
            self.assertFalse(tool_retrieval_enabled())
        finally:
            del os.environ["POCKPOCK_TOOL_RETRIEVAL_ENABLED"]

    def test_estimate_tokens_scales_with_length(self):
        self.assertLess(estimate_tokens("x" * 40), estimate_tokens("x" * 400))


if __name__ == "__main__":
    unittest.main()
