import unittest

from projects.agent_tools.browser import _screenshot_extension
from projects.agent_tools.common import AgentToolError, requests_visible_browser


class BrowserScreenshotTests(unittest.TestCase):
    def test_jpeg_and_png_screenshots_keep_matching_file_extensions(self):
        self.assertEqual(_screenshot_extension("image/jpeg"), ".jpg")
        self.assertEqual(_screenshot_extension("image/png; charset=binary"), ".png")

    def test_unknown_screenshot_format_is_rejected(self):
        with self.assertRaisesRegex(AgentToolError, "unsupported screenshot format"):
            _screenshot_extension("application/octet-stream")


class BrowserVisibilityIntentTests(unittest.TestCase):
    def test_explicit_open_browser_request_selects_visible_mode(self):
        self.assertTrue(requests_visible_browser("Open the browser and navigate to YouTube."))
        self.assertTrue(requests_visible_browser("Show this page in a visible browser window."))
        self.assertTrue(requests_visible_browser("Open a real browser window for YouTube."))
        self.assertTrue(requests_visible_browser("Don't use headless; open the browser."))

    def test_headless_background_and_negated_requests_remain_hidden(self):
        for task in (
            "Read the YouTube page headlessly.",
            "Open the browser in the background.",
            "Do not open a browser; just inspect the public page.",
            "Open the browser but don't show a window.",
        ):
            with self.subTest(task=task):
                self.assertFalse(requests_visible_browser(task))

    def test_unattended_page_observation_stays_headless(self):
        self.assertFalse(requests_visible_browser("Check the public page title and summarize it."))


if __name__ == "__main__":
    unittest.main()
