"""A file the executor printed as text is saved for the step (report 2026-11-25, restaurant website)."""

import unittest

from projects.plan_sequence.runner import printed_file_call, retry_instruction

STEP = {
    "id": "create-html",
    "goal": "Create index.html",
    "tools_allowed": ["save_text_artifact"],
    "done_condition": {"type": "file_exists", "path": "index.html"},
}
HTML = "<!DOCTYPE html>\n<html><body><h1>Trattoria</h1></body></html>\n"


class PrintedFileTests(unittest.TestCase):
    def test_a_matching_code_block_becomes_the_write_call(self):
        reply = "Here is the page:\n\n```html\n" + HTML + "```\n\nAnd some CSS:\n```css\nh1 { color: red }\n```"
        call = printed_file_call(STEP, reply)
        self.assertEqual(call, {"name": "save_text_artifact", "arguments": {"filename": "index.html", "content": HTML}})

    def test_the_only_block_is_used_when_its_language_is_not_named(self):
        call = printed_file_call(STEP, "```\n" + HTML + "```")
        self.assertEqual(call["arguments"]["content"], HTML)

    def test_a_bare_html_document_is_used_for_an_html_file(self):
        call = printed_file_call(STEP, "  " + HTML)
        self.assertEqual(call["arguments"]["content"], HTML.strip())

    def test_a_workspace_step_uses_the_project_write_tool(self):
        step = {**STEP, "tools_allowed": ["read_project_file", "propose_project_patch"]}
        call = printed_file_call(step, "```html\n" + HTML + "```")
        self.assertEqual(call["name"], "propose_project_patch")
        self.assertEqual(call["arguments"]["path"], "index.html")
        self.assertEqual(call["arguments"]["summary"], "Create index.html")

    def test_nothing_is_written_when_it_would_be_a_guess(self):
        self.assertIsNone(printed_file_call(STEP, "I will create the page now."))
        self.assertIsNone(printed_file_call(STEP, "```css\na{}\n```\n```js\nx()\n```"), "two blocks, neither HTML")
        self.assertIsNone(printed_file_call({**STEP, "tools_allowed": ["read_project_file"]}, "```html\n" + HTML + "```"), "no write tool")
        self.assertIsNone(printed_file_call({**STEP, "done_condition": {"type": "tool_succeeded", "tool": "x"}}, "```html\n" + HTML + "```"))

    def test_a_missing_file_retry_names_the_exact_call(self):
        text = retry_instruction(STEP, "file does not exist: index.html")
        self.assertIn('Call save_text_artifact now with filename "index.html"', text)
        self.assertIn("only a tool call saves it", text)
        self.assertEqual(retry_instruction(STEP, "tool timed out"), "\n\nThe previous attempt failed: tool timed out. Fix only that.")


class TextArtifactTypesTests(unittest.TestCase):
    def test_web_and_code_files_can_be_saved_to_the_task_folder(self):
        from projects.agent_tools.artifacts import TEXT_ARTIFACT_EXTENSIONS
        from projects.plan_sequence import contracts

        for extension in (".html", ".css", ".js", ".svg", ".py", ".md"):
            self.assertIn(extension, TEXT_ARTIFACT_EXTENSIONS)
        self.assertIs(contracts._TEXT_EXTENSIONS, TEXT_ARTIFACT_EXTENSIONS, "the plan checker and the tool agree")


if __name__ == "__main__":
    unittest.main()
