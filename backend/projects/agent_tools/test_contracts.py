import unittest

from projects.agent_tools import registered_tool_contracts, tool_names_for_task_capabilities
from projects.agent_tools.contracts import ToolContractError, validate_tool_input, validate_tool_output


class ToolContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = registered_tool_contracts()

    def test_all_current_tools_have_versioned_metadata_and_schemas(self):
        self.assertEqual(len(self.registry), 14)
        self.assertTrue(all(contract.contract_version == 1 for contract in self.registry.values()))
        self.assertTrue(all(contract.timeout_seconds > 0 for contract in self.registry.values()))
        self.assertTrue(all(contract.max_input_bytes > 0 and contract.max_output_bytes > 0 for contract in self.registry.values()))

    def test_input_rejects_missing_fields_wrong_types_and_unknown_fields(self):
        contract = self.registry["save_text_artifact"]
        for invalid in ({"filename": "notes.md"}, {"filename": 42, "content": "text"}, {"filename": "a.md", "content": "x", "extra": True}):
            with self.subTest(invalid=invalid), self.assertRaises(ToolContractError):
                validate_tool_input(contract, invalid)

    def test_zero_for_optional_one_based_numbers_means_not_given(self):
        contract = registered_tool_contracts()["read_project_file"]
        self.assertEqual(validate_tool_input(contract, {"path": "index.html", "start_line": 0, "end_line": 0}), {"path": "index.html"})
        self.assertEqual(validate_tool_input(contract, {"path": "index.html", "start_line": 5}), {"path": "index.html", "start_line": 5})
        with self.assertRaises(ToolContractError):
            validate_tool_input(contract, {"path": "index.html", "start_line": -3})

    def test_input_and_output_byte_limits_are_enforced(self):
        contract = self.registry["save_text_artifact"]
        with self.assertRaisesRegex(ToolContractError, "byte limit"):
            validate_tool_input(contract, {"filename": "a.md", "content": "x" * contract.max_input_bytes})
        with self.assertRaisesRegex(ToolContractError, "output limit"):
            validate_tool_output(contract, {"saved": True, "name": "a.md", "path": "x" * contract.max_output_bytes, "kind": "md"})

    def test_output_schema_is_enforced(self):
        with self.assertRaisesRegex(ToolContractError, "violated its output contract"):
            validate_tool_output(self.registry["list_project_files"], {"files": [1]})

    def test_task_capabilities_limit_tools_to_approved_scope(self):
        research_tools = tool_names_for_task_capabilities(self.registry, ["public_research"])
        self.assertEqual(research_tools, {"search_public_site", "scrape_public_page"})

        code_tools = tool_names_for_task_capabilities(
            self.registry,
            ["workspace_read", "workspace_write", "project_validation"],
        )
        self.assertIn("list_project_files", code_tools)
        self.assertIn("propose_project_patch", code_tools)
        self.assertIn("validate_project", code_tools)
        self.assertNotIn("search_public_site", code_tools)


if __name__ == "__main__":
    unittest.main()
