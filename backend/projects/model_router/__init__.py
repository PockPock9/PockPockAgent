"""Provider-neutral model contracts and local provider adapters."""

from .client import (
    ChatCompletionProvider,
    ChatCompletionRequest,
    ModelProviderError,
    OllamaChatCompletionAdapter,
    model_thinks_by_default,
    resolve_think,
)

__all__ = [
    "ChatCompletionProvider",
    "ChatCompletionRequest",
    "ModelProviderError",
    "OllamaChatCompletionAdapter",
    "model_thinks_by_default",
    "resolve_think",
]
