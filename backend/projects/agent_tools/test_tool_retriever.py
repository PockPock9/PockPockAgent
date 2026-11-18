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

    def test_select_tools_returns_schemas_and_index(self):
        from projects.agent_tools import registered_tool_specs

        specs, retrieval = self.retriever.select_tools(
            "save the results as a markdown file", registered_tool_specs()
        )
        names = [spec["function"]["name"] for spec in specs]
        self.assertIn("save_text_artifact", names)
        self.assertLessEqual(len(names), 10)
        self.assertEqual(len(retrieval.index_lines), len(registered_tool_specs()))
        self.assertLess(retrieval.tokens_after, retrieval.tokens_before)

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
