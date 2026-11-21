import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "projects"))

from planner.contracts import SubtaskPlan, TaskBrief, normalized_plan_steps, normalized_subtask_plan, normalized_task_brief


class TaskBriefContractTests(unittest.TestCase):
    def test_normalized_brief_preserves_request_and_caller_permission(self):
        request = "Create a playable browser game and verify the files."
        brief = normalized_task_brief({
            "desired_outcome": "A playable browser game",
            "required_capabilities": ["workspace_write", "project_validation", "browser_read"],
            "permission_level": "full-access",
            "milestones": [{"id": "build", "title": "Build game", "completion_check": "Run the game."}],
            "success_checks": ["Open the game and verify controls."],
        }, original_request=request, plan=["Build game"], permission_level="auto-review")
        self.assertEqual(brief["contract_version"], 1)
        self.assertEqual(brief["original_request"], request)
        self.assertEqual(brief["permission_level"], "auto-review")
        # A person-only check ("open the game") is replaced with checks the agent can evidence from files.
        self.assertEqual(brief["success_checks"], [
            "The requested source files exist in the task workspace.",
            "The source files implement the requested features.",
        ])
        self.assertIn("browser_read", brief["required_capabilities"])

    def test_missing_structured_fields_get_bounded_compatibility_defaults(self):
        brief = normalized_task_brief({}, original_request="Review this task", plan=["Inspect", "Verify"], permission_level="default")
        self.assertEqual([step["id"] for step in brief["milestones"]], ["step-1", "step-2"])
        self.assertEqual(brief["success_checks"], ["Inspect", "Verify"])
        self.assertEqual(brief["desired_outcome"], "Review this task")

    def test_numeric_milestone_ids_are_normalized_to_strings(self):
        brief = normalized_task_brief({
            "milestones": [{"id": 1, "title": "Research", "completion_check": "Source found"}],
            "success_checks": ["A cited finding is returned"],
        }, original_request="Research a topic", plan=["Find sources"], permission_level="default")
        self.assertEqual(brief["milestones"][0]["id"], "1")

    def test_plan_steps_extract_action_text_from_structured_items(self):
        self.assertEqual(
            normalized_plan_steps([
                {"id": 1, "action": "Scrape the page"},
                {"title": "Summarize the result"},
                "Cite the source",
                {"id": 4},
            ]),
            ["Scrape the page", "Summarize the result", "Cite the source"],
        )

    def test_tool_names_in_required_capabilities_are_normalized(self):
        brief = normalized_task_brief({
            "required_capabilities": [
                "scrape_public_page",
                "search_public_site",
                "browse_public_page",
                "create_office_document",
            ],
        }, original_request="Research a page", plan=["Read the page"], permission_level="default")
        self.assertEqual(
            brief["required_capabilities"],
            ["public_research", "browser_read", "artifact_creation"],
        )

    def test_structured_success_checks_are_normalized_to_evidence_text(self):
        brief = normalized_task_brief({
            "success_checks": [
                {"check": "The page is visible", "expected_result": "True"},
                {"criterion": "A screenshot is captured", "expected_result": "True"},
            ],
        }, original_request="Inspect a page", plan=["Open the page"], permission_level="default")
        self.assertEqual(
            brief["success_checks"],
            ["The page is visible", "A screenshot is captured"],
        )

    def test_browser_action_is_removed_unless_the_user_requests_interaction(self):
        read_only = normalized_task_brief({
            "required_capabilities": ["browser_read", "browser_action", "public_research"],
        }, original_request="Open https://example.com and capture a screenshot", plan=["Inspect the page"], permission_level="default")
        self.assertEqual(read_only["required_capabilities"], ["browser_read"])

        interactive = normalized_task_brief({
            "required_capabilities": ["browser_read", "browser_action"],
        }, original_request="Open https://example.com and click the Help link", plan=["Inspect the page"], permission_level="default")
        self.assertEqual(interactive["required_capabilities"], ["browser_read", "browser_action"])

    def test_a_requested_file_gets_the_artifact_tools(self):
        # Issue #92: the planner returned no capabilities for a plain "save a file" task.
        brief = normalized_task_brief({"required_capabilities": []}, original_request=(
            "Save a text artifact named probe-result.md. Its first line must be exactly SKILL-MCP-PROBE-OK."
        ), plan=["Save the file"], permission_level="auto-review")
        self.assertEqual(brief["required_capabilities"], ["artifact_creation"])
        for request in ("Write a memo about the offsite", "Export the table as a spreadsheet"):
            brief = normalized_task_brief({"required_capabilities": []}, original_request=request, plan=["Do it"], permission_level="default")
            self.assertIn("artifact_creation", brief["required_capabilities"], request)
        for request in ("Hello there", "What is 2 plus 2?"):
            brief = normalized_task_brief({"required_capabilities": []}, original_request=request, plan=["Answer"], permission_level="default")
            self.assertEqual(brief["required_capabilities"], [], request)

    def test_reading_files_in_the_open_folder_gets_the_read_tools(self):
        # R&D validation 2026-11-21: "read the reports in this folder" planned artifact_creation only.
        request = ("Read all ten files report-01.txt to report-10.txt in this folder, then save a text "
                   "artifact named codewords.md listing each file's codeword.")
        brief = normalized_task_brief({"required_capabilities": ["artifact_creation"]}, original_request=request,
                                      plan=["Read", "Save"], permission_level="auto-review", has_workspace=True)
        self.assertEqual(brief["required_capabilities"], ["artifact_creation", "workspace_read"])
        for request in ("Summarize the notes in my folder", "Review the project files and list open TODOs", "Check data.csv for empty rows"):
            brief = normalized_task_brief({"required_capabilities": []}, original_request=request,
                                          plan=["Do it"], permission_level="default", has_workspace=True)
            self.assertIn("workspace_read", brief["required_capabilities"], request)
            self.assertNotIn("workspace_write", brief["required_capabilities"], request)

    def test_read_tools_are_not_added_without_an_open_folder_or_a_read_request(self):
        request = "Summarize the notes in my folder"
        brief = normalized_task_brief({"required_capabilities": []}, original_request=request, plan=["Do it"], permission_level="default")
        self.assertNotIn("workspace_read", brief["required_capabilities"])
        for request in ("Hello there", "What is 2 plus 2?"):
            brief = normalized_task_brief({"required_capabilities": []}, original_request=request, plan=["Answer"],
                                          permission_level="default", has_workspace=True)
            self.assertEqual(brief["required_capabilities"], [], request)

    def test_public_research_is_not_added_to_single_page_visual_inspection(self):
        brief = normalized_task_brief({
            "required_capabilities": ["browser_read", "public_research"],
        }, original_request="Inspect https://example.com and summarize the visible page", plan=["Open the page"], permission_level="default")
        self.assertEqual(brief["required_capabilities"], ["browser_read"])

    def test_scalar_text_fields_are_normalized_to_single_item_lists(self):
        brief = normalized_task_brief({
            "constraints": "Only download images",
            "assumptions": "The website is publicly accessible",
            "required_capabilities": "public_research",
            "deliverables": "A list of image URLs",
            "success_checks": "Every URL points to an image",
            "requires_clarification": True,
            "clarifying_questions": "Should images be saved locally?",
        }, original_request="Collect images from a website", plan=["Inspect", "Collect"], permission_level="default")

        self.assertEqual(brief["constraints"], ["Only download images"])
        self.assertEqual(brief["assumptions"], ["The website is publicly accessible"])
        self.assertEqual(brief["required_capabilities"], ["public_research"])
        self.assertEqual(brief["deliverables"], ["A list of image URLs"])
        self.assertEqual(brief["success_checks"], ["Every URL points to an image"])
        self.assertEqual(brief["clarifying_questions"], ["Should images be saved locally?"])

    def test_build_requests_always_get_workspace_write_and_lose_unrequested_web_access(self):
        brief = normalized_task_brief({
            "required_capabilities": ["browser_read", "workspace_read"],
        }, original_request="build a flappy bird webapp game", plan=["Build"], permission_level="full-access")
        self.assertEqual(brief["required_capabilities"], ["workspace_read", "workspace_write", "project_validation"])

    def test_build_checks_keep_verifiable_items_and_replace_runtime_ones(self):
        brief = normalized_task_brief({
            "success_checks": ["The game runs successfully in the browser.", "index.html defines a canvas element"],
        }, original_request="build a flappy bird webapp game", plan=["Build"], permission_level="default")
        self.assertEqual(brief["success_checks"], [
            "index.html defines a canvas element",
            "The requested source files exist in the task workspace.",
            "The source files implement the requested features.",
        ])

    def test_behaviour_only_checks_are_replaced_but_file_checks_stay(self):
        brief = normalized_task_brief({
            "success_checks": [
                "The bird should fall and the pipes should move.",
                "The bird can be made to jump by clicking",
                "game.js implements a jump on click",
            ],
        }, original_request="build a flappy bird webapp game", plan=["Build"], permission_level="default")
        self.assertEqual(brief["success_checks"], [
            "game.js implements a jump on click",
            "The requested source files exist in the task workspace.",
            "The source files implement the requested features.",
        ])

    def test_non_build_checks_are_left_alone(self):
        brief = normalized_task_brief({
            "success_checks": ["The summary displays three findings."],
        }, original_request="Research the latest TypeScript release notes", plan=["Search"], permission_level="default")
        self.assertEqual(brief["success_checks"], ["The summary displays three findings."])

    def test_requests_without_web_cues_drop_web_capabilities(self):
        brief = normalized_task_brief({
            "required_capabilities": ["public_research"],
        }, original_request="hi", plan=["Reply"], permission_level="default")
        self.assertEqual(brief["required_capabilities"], [])

    def test_web_capabilities_stay_when_the_request_mentions_the_web(self):
        brief = normalized_task_brief({
            "required_capabilities": ["public_research"],
        }, original_request="Research the latest TypeScript release notes", plan=["Search"], permission_level="default")
        self.assertEqual(brief["required_capabilities"], ["public_research"])

    def test_build_tasks_drop_environment_setup_checks(self):
        # Real planner output for "build a flappy bird webapp game"; the agent skipped the two setup checks.
        brief = normalized_task_brief(
            {"success_checks": [
                "Workspace directory exists and is writable.",
                "Required libraries are installed in the workspace.",
                "index.html file exists with basic structure.",
                "script.js file exists with game logic.",
            ]},
            original_request="build a flappy bird webapp game",
            plan=["Write the game"],
            permission_level="auto-review",
        )
        self.assertEqual(brief["success_checks"], [
            "index.html file exists with basic structure.",
            "script.js file exists with game logic.",
            "The requested source files exist in the task workspace.",
            "The source files implement the requested features.",
        ])

    def test_clarification_flag_requires_questions(self):
        with self.assertRaisesRegex(ValueError, "at least one question"):
            TaskBrief(
                original_request="Do it",
                desired_outcome="Complete it",
                permission_level="default",
                milestones=[{"id": "one", "title": "Do it", "completion_check": "Done"}],
                success_checks=["Done"],
                requires_clarification=True,
            )

    def test_unknown_capabilities_and_contract_versions_fail_validation(self):
        base = {
            "original_request": "Build an app", "desired_outcome": "An app", "permission_level": "default",
            "milestones": [{"id": "one", "title": "Build", "completion_check": "App works"}],
            "success_checks": ["App works"],
        }
        with self.assertRaises(ValueError):
            TaskBrief(**{**base, "required_capabilities": ["shell_access"]})
        with self.assertRaises(ValueError):
            TaskBrief(**{**base, "contract_version": 2})

    def test_delegation_plan_is_bounded_and_requires_topological_dependencies(self):
        plan = normalized_subtask_plan({"subtasks": [
            {"id": "research", "role": "researcher", "purpose": "Find official source", "expected_result": "Cited notes", "allowed_tools": ["search_public_site"], "max_tool_calls": 4, "max_duration_seconds": 120},
            {"id": "report", "role": "writer", "purpose": "Summarize evidence", "expected_result": "Short report", "depends_on": ["research"], "allowed_tools": ["save_text_artifact"]},
        ]})
        self.assertEqual(plan["subtasks"][1]["depends_on"], ["research"])
        with self.assertRaises(ValueError):
            SubtaskPlan(subtasks=[
                {"id": "later", "role": "worker", "purpose": "A", "expected_result": "A", "depends_on": ["earlier"], "allowed_tools": ["search_public_site"]},
                {"id": "earlier", "role": "worker", "purpose": "B", "expected_result": "B", "allowed_tools": ["search_public_site"]},
            ])
        with self.assertRaises(ValueError):
            normalized_subtask_plan({"subtasks": [{"id": "bad", "role": "worker", "purpose": "A", "expected_result": "A", "allowed_tools": ["shell"]}]})


if __name__ == "__main__":
    unittest.main()
