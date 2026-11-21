import unittest
from unittest.mock import AsyncMock, patch

from projects.model_router import ChatCompletionRequest, OllamaChatCompletionAdapter


class LoadedContextReuseTests(unittest.IsolatedAsyncioTestCase):
    """A loaded model is reused at its context size instead of being reloaded (R&D validation 2026-11-21)."""

    async def fitted(self, loaded: dict[str, int], **request_fields) -> int | None:
        adapter = OllamaChatCompletionAdapter("http://127.0.0.1:11434")
        request = ChatCompletionRequest(model="qwen3.5:9b", messages=[{"role": "user", "content": "hi"}], **request_fields)
        with patch.object(adapter, "_loaded_contexts", AsyncMock(return_value=loaded)):
            return (await adapter._fit_loaded_context(request)).context_window

    async def test_a_bigger_loaded_context_is_reused(self):
        # The planner asked for 8K while the model was loaded at 16K; Ollama reloaded it.
        self.assertEqual(await self.fitted({"qwen3.5:9b": 16384}, context_window=8192), 16384)
        self.assertEqual(await self.fitted({"qwen3.5:9b": 32768}), 32768)

    async def test_a_smaller_or_huge_loaded_context_is_not_reused(self):
        self.assertEqual(await self.fitted({"qwen3.5:9b": 4096}, context_window=8192), 8192)
        self.assertEqual(await self.fitted({"qwen3.5:9b": 131072}, context_window=8192), 8192)
        with patch.dict("os.environ", {"OLLAMA_CONTEXT_LENGTH": ""}):
            self.assertEqual(await self.fitted({}, context_window=8192), 8192)
            self.assertEqual(await self.fitted({"other:7b": 32768}, context_window=8192), 8192)

    async def test_an_unloaded_model_loads_at_ollamas_default_size(self):
        # Tool calls use Ollama's default size (OLLAMA_CONTEXT_LENGTH); loading smaller meant a reload.
        with patch.dict("os.environ", {"OLLAMA_CONTEXT_LENGTH": "32768"}):
            self.assertEqual(await self.fitted({}, context_window=8192), 32768)
        with patch.dict("os.environ", {"OLLAMA_CONTEXT_LENGTH": ""}):
            self.assertEqual(await self.fitted({}, context_window=8192), 8192)

    async def test_ollama_being_unreachable_changes_nothing(self):
        adapter = OllamaChatCompletionAdapter("http://127.0.0.1:9")
        self.assertEqual(await adapter._loaded_contexts(), {})


if __name__ == "__main__":
    unittest.main()
