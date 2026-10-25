"""Model and agent interfaces, clients, and registries."""

from tasksentry.models.base import ModelClient, ModelResponse
from tasksentry.models.fake_model import FakeModel
from tasksentry.models.ollama import OllamaClient, check_ollama_health
from tasksentry.models.openai_compat import OpenAICompatibleClient
from tasksentry.models.registry import (
    AgentDefinition,
    AgentRegistry,
    ModelRegistry,
    PolicyDefinition,
    ResolvedAgent,
)
from tasksentry.models.router import SemanticModelRouter

__all__ = [
    "AgentDefinition",
    "AgentRegistry",
    "FakeModel",
    "ModelClient",
    "ModelRegistry",
    "ModelResponse",
    "OllamaClient",
    "OpenAICompatibleClient",
    "PolicyDefinition",
    "ResolvedAgent",
    "SemanticModelRouter",
    "check_ollama_health",
]
