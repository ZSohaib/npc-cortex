"""LLM providers (spec 3.11)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

__all__ = ["HttpProvider", "ChatCompletionsProvider"]


class ChatCompletionsProvider:
    """OpenAI-compatible ``POST {endpoint}`` chat provider.

    Sends ``{"model", "messages": [{role, content}]}`` with a Bearer key
    (``NPC_CORTEX_API_KEY``) and returns the assistant content string.
    Fits Meta Model API (``.../v1/chat/completions``) and any compatible
    endpoint. ``timeout`` bounds one call; failures raise RuntimeError.
    ``reasoning_effort`` is sent when set (Meta's reasoning models need
    it, else they burn the whole budget thinking); pass None for
    endpoints that reject the field.
    """

    def __init__(self, endpoint: str, model: str, timeout: float = 20.0,
                 max_tokens: int = 800, reasoning_effort="low") -> None:
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort

    def complete(self, prompt: str) -> str:
        key = os.environ.get("NPC_CORTEX_API_KEY", "") or os.environ.get(
            "NPC_LLM_API_KEY", "")
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
        }
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + key,
            },
        )
        try:
            with urllib.request.urlopen(request,
                                        timeout=self.timeout) as response:
                status = int(getattr(response, "status", response.getcode()))
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise RuntimeError("provider returned HTTP %d" % exc.code) from exc
        if not 200 <= status < 300:
            raise RuntimeError("provider returned HTTP %d" % status)
        try:
            data = json.loads(body)
            return data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("provider returned unexpected body") from exc


class HttpProvider:
    def __init__(self, endpoint: str, model: str) -> None:
        self.endpoint = endpoint
        self.model = model

    def complete(self, prompt: str) -> str:
        # NPC_LLM_API_KEY is the pre-rename fallback, honoured for
        # backward compatibility with existing deployments.
        key = os.environ.get("NPC_CORTEX_API_KEY", "") or os.environ.get(
            "NPC_LLM_API_KEY", "")
        payload = json.dumps({"model": self.model, "prompt": prompt}).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + key,
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                status = int(getattr(response, "status", response.getcode()))
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise RuntimeError("provider returned HTTP %d" % exc.code) from exc
        if not 200 <= status < 300:
            raise RuntimeError("provider returned HTTP %d" % status)
        return body
