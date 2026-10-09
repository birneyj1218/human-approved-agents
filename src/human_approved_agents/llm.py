"""LLM clients. Anything that speaks the OpenAI chat-completions API works:
OpenAI, a local llama.cpp server, Ollama (``/v1``), vLLM, LM Studio...

``FakeLLM`` is deterministic and offline, for tests and the demo.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, TypedDict


class Message(TypedDict):
    role: str
    content: str


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    def complete(self, messages: Sequence[Message], *, temperature: float = 0.3) -> str: ...


class OpenAICompatibleClient:
    """Minimal chat-completions client over httpx, with retry on 429/5xx."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_s: float = 60,
        max_retries: int = 2,
        transport: object | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        import httpx

        headers = {"Content-Type": "application/json"}
        if api_key:  # local servers usually need none
            headers["Authorization"] = f"Bearer {api_key}"
        kwargs: dict[str, object] = {"timeout": timeout_s, "headers": headers}
        if transport is not None:
            kwargs["transport"] = transport
        self._http = httpx.Client(base_url=base_url.rstrip("/"), **kwargs)  # type: ignore[arg-type]
        self.model = model
        self.max_retries = max_retries
        self._sleep = sleep

    def complete(self, messages: Sequence[Message], *, temperature: float = 0.3) -> str:
        import httpx

        payload = {"model": self.model, "messages": list(messages), "temperature": temperature}
        last_error = "no attempt made"
        for attempt in range(self.max_retries + 1):
            try:
                r = self._http.post("/chat/completions", json=payload)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}"
            else:
                if r.status_code == 200:
                    try:
                        content = r.json()["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError, ValueError) as exc:
                        raise LLMError("unexpected response shape from LLM server") from exc
                    if not isinstance(content, str) or not content.strip():
                        raise LLMError("LLM returned an empty message")
                    return content.strip()
                last_error = f"HTTP {r.status_code}"
                if r.status_code not in {408, 429} and r.status_code < 500:
                    break  # a 4xx other than rate limit will not fix itself
            if attempt < self.max_retries:
                self._sleep(2**attempt)
        # Never include the request or headers in the error: they may hold a key.
        raise LLMError(f"LLM request failed: {last_error}")


# --------------------------------------------------------------------------
# Fake


def _section(prompt: str, name: str) -> list[str]:
    """Lines under ``NAME:`` up to the next blank line, as bullet-free strings."""
    m = re.search(rf"^{name}:\n((?:.+\n?)*)", prompt, re.MULTILINE)
    if not m:
        return []
    return [ln.lstrip("- ").strip() for ln in m.group(1).splitlines() if ln.strip()]


def _field(prompt: str, name: str) -> str:
    m = re.search(rf"^{name}: (.*)$", prompt, re.MULTILINE)
    return m.group(1).strip() if m else ""


@dataclass
class FakeLLM:
    """Offline stand-in for an LLM.

    With ``script`` it returns those strings in order. Otherwise it builds a
    short, plain reply from the prompt sections the Drafter writes (contact,
    title, facts, sign-off) so the demo produces believable text without a
    model. ``calls`` records every prompt for assertions.
    """

    script: list[str] | None = None
    calls: list[list[Message]] = field(default_factory=list)

    def complete(self, messages: Sequence[Message], *, temperature: float = 0.3) -> str:
        self.calls.append(list(messages))
        if self.script is not None:
            if not self.script:
                raise LLMError("FakeLLM script exhausted")
            return self.script.pop(0)
        return self.template_reply("\n".join(m["content"] for m in messages))

    @staticmethod
    def template_reply(prompt: str) -> str:
        name = _field(prompt, "CONTACT") or "there"
        title = _field(prompt, "TITLE") or "your request"
        facts = _section(prompt, "FACTS")
        lessons = " ".join(_section(prompt, "LESSONS")).lower()
        sign_off = _field(prompt, "SIGN-OFF")
        n_facts = 1 if "shortened" in lessons else 2
        chosen = " ".join(facts[:n_facts])
        first = name.split()[0]
        body = (
            f'Hi {first},\n\nThanks for the details on "{title}". {chosen}\n\n'
            "Would a short call this week work to confirm the scope?"
        )
        return f"{body}\n\n{sign_off}".strip()
