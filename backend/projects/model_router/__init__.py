"""Provider-neutral model contracts and local provider adapters."""

from .client import (
    ChatCompletionProvider,
    ChatCompletionRequest,
    ModelProviderError,
    OllamaChatCompletionAdapter,
)

__all__ = [
    "ChatCompletionProvider",
    "ChatCompletionRequest",
    "ModelProviderError",
    "OllamaChatCompletionAdapter",
]
