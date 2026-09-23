from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .modeling import (
    ModelCircuitOpen,
    ModelMessage,
    ModelProtocolError,
    ModelProvider,
    ModelProviderError,
    RetryableModelProviderError,
)
from .models import ToolSpec

JsonTransport = Callable[[str, dict[str, str], bytes, float], object]


def _default_transport(
    url: str, headers: dict[str, str], body: bytes, timeout: float
) -> object:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        if error.code in {408, 409, 429} or error.code >= 500:
            raise RetryableModelProviderError(
                f"Provider returned transient HTTP status {error.code}."
            ) from error
        raise ModelProviderError(f"Provider returned HTTP status {error.code}.") from error
    except (TimeoutError, socket.timeout, urllib.error.URLError) as error:
        raise RetryableModelProviderError(
            f"Provider transport failed with {type(error).__name__}."
        ) from error
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelProtocolError("Provider returned invalid JSON.") from error


class OpenAIResponsesProvider:
    """Translate the workbench model protocol to the OpenAI Responses API."""

    name = "openai-responses"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30.0,
        transport: JsonTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key cannot be empty.")
        if not model.strip():
            raise ValueError("model cannot be empty.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        self._api_key = api_key
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._transport = transport or _default_transport

    @staticmethod
    def _tool(tool: ToolSpec) -> dict[str, Any]:
        properties = tool.parameters.get("properties")
        required = tool.parameters.get("required")
        if (
            tool.parameters.get("type") != "object"
            or tool.parameters.get("additionalProperties") is not False
            or not isinstance(properties, dict)
            or set(required or []) != set(properties)
        ):
            raise ModelProtocolError(
                f"Tool {tool.name} does not satisfy strict function schema requirements."
            )
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
            "strict": True,
        }

    @staticmethod
    def _input(messages: tuple[ModelMessage, ...]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for message in messages:
            if message.role in {"system", "user"}:
                role = "developer" if message.role == "system" else "user"
                items.append({"role": role, "content": message.content})
                continue
            if message.role == "tool":
                if not message.tool_call_id:
                    raise ModelProtocolError("Tool result is missing tool_call_id.")
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id,
                        "output": message.content,
                    }
                )
                continue
            try:
                value = json.loads(message.content)
            except json.JSONDecodeError:
                items.append({"role": "assistant", "content": message.content})
                continue
            calls = value.get("tool_calls") if isinstance(value, dict) else None
            if not isinstance(calls, list):
                items.append({"role": "assistant", "content": message.content})
                continue
            continuation = value.get("continuation")
            if isinstance(continuation, list) and continuation:
                if any(not isinstance(item, dict) for item in continuation):
                    raise ModelProtocolError("Provider continuation items must be objects.")
                items.extend(continuation)
                continue
            for call in calls:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call["id"],
                        "name": call["name"],
                        "arguments": json.dumps(
                            call["arguments"], ensure_ascii=False, separators=(",", ":")
                        ),
                    }
                )
        return items

    @staticmethod
    def _usage(payload: dict[str, Any]) -> dict[str, int | float | None]:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            raise ModelProtocolError("Responses payload is missing usage.")
        return {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cost_usd": None,
        }

    @classmethod
    def _response(cls, payload: object) -> object:
        if not isinstance(payload, dict):
            raise ModelProtocolError("Responses payload must be a JSON object.")
        output = payload.get("output")
        if not isinstance(output, list):
            raise ModelProtocolError("Responses payload output must be an array.")
        calls: list[dict[str, Any]] = []
        text_parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                raise ModelProtocolError("Responses output items must be objects.")
            if item.get("type") == "function_call":
                arguments = item.get("arguments")
                try:
                    parsed_arguments = json.loads(arguments)
                except (TypeError, json.JSONDecodeError) as error:
                    raise ModelProtocolError(
                        "Function call arguments must be encoded JSON."
                    ) from error
                calls.append(
                    {
                        "id": item.get("call_id"),
                        "name": item.get("name"),
                        "arguments": parsed_arguments,
                    }
                )
            elif item.get("type") == "message":
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        text = part.get("text")
                        if isinstance(text, str):
                            text_parts.append(text)
        usage = cls._usage(payload)
        if calls:
            return {
                "type": "tool_calls",
                "tool_calls": calls,
                "usage": usage,
                "continuation": output,
            }
        content = "\n".join(text_parts).strip()
        if not content:
            raise ModelProtocolError("Responses payload has no final text or function call.")
        return {"type": "final", "content": content, "usage": usage}

    def complete(
        self,
        messages: tuple[ModelMessage, ...],
        tools: tuple[ToolSpec, ...],
    ) -> object:
        payload = {
            "model": self.model,
            "input": self._input(messages),
            "tools": [self._tool(tool) for tool in tools],
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        }
        response = self._transport(
            f"{self.base_url}/responses",
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            self.timeout_seconds,
        )
        return self._response(response)


class DeepSeekResponsesProvider(OpenAIResponsesProvider):
    """DeepSeek's stateless OpenAI-compatible Responses API."""

    name = "deepseek-responses"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 30.0,
        transport: JsonTransport | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )


@dataclass(frozen=True)
class ReliabilityPolicy:
    max_attempts: int = 3
    initial_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 2.0
    failure_threshold: int = 3
    cooldown_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.failure_threshold < 1:
            raise ValueError("attempt and failure limits must be positive.")
        if min(
            self.initial_backoff_seconds,
            self.max_backoff_seconds,
            self.cooldown_seconds,
        ) < 0:
            raise ValueError("reliability durations cannot be negative.")


class ResilientModelProvider:
    """Add bounded transient retries and a process-local circuit breaker."""

    def __init__(
        self,
        provider: ModelProvider,
        *,
        policy: ReliabilityPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.provider = provider
        self.name = provider.name
        self.policy = policy or ReliabilityPolicy()
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._open_until = 0.0
        self._probe_in_flight = False

    def _before_call(self) -> bool:
        with self._lock:
            now = self._clock()
            if self._open_until > now:
                raise ModelCircuitOpen("Model provider circuit is open.")
            if self._open_until:
                if self._probe_in_flight:
                    raise ModelCircuitOpen("Model provider circuit is half-open.")
                self._probe_in_flight = True
                return True
            return False

    def _succeeded(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._open_until = 0.0
            self._probe_in_flight = False

    def _failed(self) -> None:
        with self._lock:
            self._probe_in_flight = False
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.policy.failure_threshold:
                self._open_until = self._clock() + self.policy.cooldown_seconds

    def complete(
        self,
        messages: tuple[ModelMessage, ...],
        tools: tuple[ToolSpec, ...],
    ) -> object:
        self._before_call()
        for attempt in range(1, self.policy.max_attempts + 1):
            try:
                result = self.provider.complete(messages, tools)
            except RetryableModelProviderError:
                if attempt == self.policy.max_attempts:
                    self._failed()
                    raise
                delay = min(
                    self.policy.initial_backoff_seconds * (2 ** (attempt - 1)),
                    self.policy.max_backoff_seconds,
                )
                self._sleep(delay)
            except Exception:
                with self._lock:
                    self._probe_in_flight = False
                raise
            else:
                self._succeeded()
                return result
        raise AssertionError("unreachable")
