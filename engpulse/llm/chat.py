"""Chat clients behind one protocol.

* ``OllamaChatClient`` — live, via the OpenAI-compatible ``/chat/completions``.
* ``ScriptedChatClient`` — returns a fixed sequence of responses (tests
  retry/repair on schema violations).
* ``FakeChatClient`` — deterministic: extracts the ``[REF:...]`` ids from the
  prompt and returns a schema-valid insight that cites them, so the synthesis
  pipeline runs offline and still produces *grounded* output.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

import httpx

from engpulse.config import get_settings

_REF_RE = re.compile(r"\[REF:([^\]]+)\]")


class ChatClient(Protocol):
    def complete(self, messages: list[dict]) -> str: ...


class OllamaChatClient:
    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self._model = model or settings.ollama_chat_model

    def complete(self, messages: list[dict]) -> str:
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"{self._base_url}/chat/completions",
                json={
                    "model": self._model,
                    "messages": messages,
                    "temperature": 0,
                    "stream": False,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]


class ScriptedChatClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def complete(self, messages: list[dict]) -> str:
        self.calls += 1
        if not self._responses:
            return "{}"
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]


class FakeChatClient:
    """Deterministic grounded output: cites the evidence refs found in the prompt."""

    def complete(self, messages: list[dict]) -> str:
        # Read only the evidence (user) turns — never the system prompt, whose
        # literal "[REF:<id>]" placeholder is not real evidence.
        text = "\n".join(
            m.get("content", "") for m in messages if m.get("role") != "system"
        )
        refs: list[str] = []
        for r in _REF_RE.findall(text):
            if r not in refs:
                refs.append(r)
        top = refs[:2] or refs
        claims = [
            {"text": f"Supported by {r}.", "evidence_refs": [r]} for r in top
        ]
        # Includes both insight fields and an `answer` field so the same fake
        # validates against GeneratedInsight and GeneratedAnswer schemas.
        payload = {
            "summary": "Synthesized from the supplied evidence.",
            "likely_cause": "Concentration of activity indicated by the evidence.",
            "recommended_action": "Review with the responsible owner and de-risk.",
            "answer": "Based on the cited evidence: " + "; ".join(top) + ".",
            "claims": claims,
            "confidence": 0.8,
        }
        return json.dumps(payload)


def build_chat_client(source: str = "fake") -> ChatClient:
    if source == "ollama":
        return OllamaChatClient()
    if source == "fake":
        return FakeChatClient()
    raise ValueError(f"Unknown chat source '{source}' (expected 'ollama' or 'fake')")
