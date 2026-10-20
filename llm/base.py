"""Provider-agnostic interface for talking to any LLM backend.
Every concrete provider (Lemonade today; OpenAI/Anthropic later) implements
this same interface, so the rest of the agent never needs to know which
backend is actually running.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    tool_call_id: Optional[str] = None
    # An assistant turn that requested tools must carry them, or the
    # following tool-role message references a call the model cannot see.
    tool_calls: Optional[list[dict[str, Any]]] = None


class ChatResponse(BaseModel):
    content: str
    finish_reason: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None
    raw: dict[str, Any] = {}
    # Stage 12a answer-checker metadata (set by agent_loop, not the provider).
    check_meta: Optional[dict[str, Any]] = None


class LLMProvider(ABC):
    """Base interface every LLM backend must implement."""

    @abstractmethod
    def chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Send a conversation, get back one response.
        Deliberately one method, not separate generate/chat/tool_call
        methods: the OpenAI-compatible APIs we're targeting (Lemonade,
        OpenAI, Anthropic-via-adapter) all unify these into one
        chat-completion call with an optional `tools` list. Streaming
        gets added as a parameter here later, once an actual use case
        needs it.
        """
        raise NotImplementedError
