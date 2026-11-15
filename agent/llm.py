"""LLM access point for the SealCall agent engine.

Phase 2 deliberately wires NO real model key. This module defines the
interface a future LLM-backed analyst will use, plus an unconfigured
stub that fails loudly instead of silently falling back. The active
analyst today is the rule-based placeholder in analyst.py, which does
not call an LLM at all.
"""

from __future__ import annotations

from typing import Optional, Protocol


class LLMNotConfigured(RuntimeError):
    """Raised when an LLM-backed path is used without a configured client."""


class LLMClient(Protocol):
    """Minimal chat-completion surface an LLM analyst would need."""

    def complete(self, system: str, user: str) -> str:
        """Return the model's text completion for one prompt pair."""
        ...


class UnconfiguredLLM:
    """Placeholder LLMClient: present so wiring exists, refuses to run."""

    def __init__(self, reason: str = "no model key configured (phase 2 placeholder)"):
        self.reason = reason

    def complete(self, system: str, user: str) -> str:
        raise LLMNotConfigured(self.reason)


def get_llm() -> Optional[LLMClient]:
    """Return a configured LLM client, or None when none is configured.

    Phase 2 always returns None: no API key is read from the environment
    and no network call to a model provider is made. A future phase can
    construct a real client here (env-key based) without touching the
    analyst or engine code.
    """
    return None
