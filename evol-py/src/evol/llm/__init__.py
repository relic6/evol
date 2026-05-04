"""LLM Backend abstraction (3 modes: direct / subprocess / host).

See LLM-BACKENDS.md for full design rationale.
"""

from evol.llm.base import (
    DeferredLLMResponse,
    LLMBackendKind,
    LLMClient,
    LLMResponse,
    Message,
)
from evol.llm.detector import detect_backend
from evol.llm.host_client import HostAgentClient
from evol.llm.mock_client import MockLLMClient
from evol.llm.subprocess_client import SubprocessLLMClient

__all__ = [
    "DeferredLLMResponse",
    "HostAgentClient",
    "LLMBackendKind",
    "LLMClient",
    "LLMResponse",
    "Message",
    "MockLLMClient",
    "SubprocessLLMClient",
    "detect_backend",
]
