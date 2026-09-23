from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .models import ToolSpec, WorkbenchError


class ModelProtocolError(WorkbenchError):
    """Raised when a provider returns an invalid structured response."""


class ModelProviderError(WorkbenchError):
    """Raised when a provider fails before returning a response."""


class RetryableModelProviderError(ModelProviderError):
    """Raised for transient provider failures that may be retried."""


class ModelCircuitOpen(ModelProviderError):
    """Raised when the provider circuit breaker is rejecting calls."""


class ModelBudgetExceeded(WorkbenchError):
    """Raised when observed model usage exceeds a configured budget."""


class ModelLoopLimitExceeded(WorkbenchError):
    """Raised when an agent does not produce a final answer in time."""


@dataclass(frozen=True)
class ModelMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ModelToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int
    cost_usd: float | None


@dataclass(frozen=True)
class ModelResponse:
    kind: Literal["final", "tool_calls"]
    usage: ModelUsage
    content: str | None = None
    tool_calls: tuple[ModelToolCall, ...] = ()
    data: dict[str, Any] | None = None
    continuation: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ModelBudget:
    max_calls: int = 8
    max_input_tokens: int = 100_000
    max_output_tokens: int = 20_000
    max_cost_usd: float = 1.0

    def __post_init__(self) -> None:
        if self.max_calls < 1:
            raise ValueError("max_calls must be positive.")
        if self.max_input_tokens < 0 or self.max_output_tokens < 0:
            raise ValueError("token budgets cannot be negative.")
        if self.max_cost_usd < 0:
            raise ValueError("max_cost_usd cannot be negative.")


@dataclass
class ModelUsageTotals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = 0.0

    def add(self, usage: ModelUsage, budget: ModelBudget) -> None:
        self.calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        if usage.cost_usd is None:
            self.cost_usd = None
        elif self.cost_usd is not None:
            self.cost_usd += usage.cost_usd
        if self.calls > budget.max_calls:
            raise ModelBudgetExceeded(f"Model-call budget of {budget.max_calls} exceeded.")
        if self.input_tokens > budget.max_input_tokens:
            raise ModelBudgetExceeded(
                f"Input-token budget of {budget.max_input_tokens} exceeded."
            )
        if self.output_tokens > budget.max_output_tokens:
            raise ModelBudgetExceeded(
                f"Output-token budget of {budget.max_output_tokens} exceeded."
            )
        if self.cost_usd is not None and self.cost_usd > budget.max_cost_usd:
            raise ModelBudgetExceeded(
                f"Model cost budget of ${budget.max_cost_usd:.6f} exceeded."
            )

    def as_dict(self) -> dict[str, int | float | None]:
        return {
            "calls": self.calls,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "costUSD": None if self.cost_usd is None else round(self.cost_usd, 8),
        }


class ModelProvider(Protocol):
    name: str

    def complete(
        self,
        messages: tuple[ModelMessage, ...],
        tools: tuple[ToolSpec, ...],
    ) -> object: ...


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ModelProtocolError(f"{field_name} must be a non-negative integer.")
    return value


def _usage(value: object) -> ModelUsage:
    if not isinstance(value, dict) or set(value) != {
        "input_tokens",
        "output_tokens",
        "cost_usd",
    }:
        raise ModelProtocolError(
            "usage requires exactly input_tokens, output_tokens and cost_usd."
        )
    cost = value["cost_usd"]
    if cost is not None and (
        isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0
    ):
        raise ModelProtocolError("cost_usd must be null or a non-negative number.")
    return ModelUsage(
        input_tokens=_non_negative_int(value["input_tokens"], "input_tokens"),
        output_tokens=_non_negative_int(value["output_tokens"], "output_tokens"),
        cost_usd=None if cost is None else float(cost),
    )


def _json_object(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ModelProtocolError(f"{field_name} must be a JSON object.")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ModelProtocolError(f"{field_name} must contain JSON values.") from error
    return value


def parse_model_response(payload: object) -> ModelResponse:
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        raise ModelProtocolError("Model response must be a JSON object.")
    kind = payload.get("type")
    usage = _usage(payload.get("usage"))
    if kind == "final":
        if not set(payload).issubset({"type", "content", "data", "usage"}):
            raise ModelProtocolError("Final response contains unsupported fields.")
        content = payload.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelProtocolError("Final response content must be non-empty text.")
        data_value = payload.get("data")
        data = None if data_value is None else _json_object(data_value, "data")
        return ModelResponse("final", usage, content=content, data=data)
    if kind == "tool_calls":
        if not set(payload).issubset({"type", "tool_calls", "usage", "continuation"}) or not {
            "type",
            "tool_calls",
            "usage",
        }.issubset(payload):
            raise ModelProtocolError(
                "Tool response requires type, tool_calls and usage."
            )
        raw_calls = payload.get("tool_calls")
        if not isinstance(raw_calls, list) or not raw_calls:
            raise ModelProtocolError("tool_calls must be a non-empty array.")
        calls: list[ModelToolCall] = []
        seen_ids: set[str] = set()
        for raw_call in raw_calls:
            if not isinstance(raw_call, dict) or set(raw_call) != {
                "id",
                "name",
                "arguments",
            }:
                raise ModelProtocolError(
                    "Each tool call requires exactly id, name and arguments."
                )
            call_id = raw_call["id"]
            name = raw_call["name"]
            if not isinstance(call_id, str) or not call_id.strip():
                raise ModelProtocolError("Tool call id must be non-empty text.")
            if call_id in seen_ids:
                raise ModelProtocolError(f"Duplicate tool call id: {call_id}")
            if not isinstance(name, str) or not name.strip():
                raise ModelProtocolError("Tool name must be non-empty text.")
            seen_ids.add(call_id)
            calls.append(
                ModelToolCall(
                    call_id,
                    name,
                    _json_object(raw_call["arguments"], "tool arguments"),
                )
            )
        raw_continuation = payload.get("continuation", [])
        if not isinstance(raw_continuation, list):
            raise ModelProtocolError("continuation must be an array.")
        continuation = tuple(
            _json_object(item, "continuation item") for item in raw_continuation
        )
        return ModelResponse(
            "tool_calls", usage, tool_calls=tuple(calls), continuation=continuation
        )
    raise ModelProtocolError("Model response type must be final or tool_calls.")


class ScriptedModelProvider:
    """Offline provider used to test the model boundary without API access."""

    name = "scripted-fake"

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.requests: list[tuple[ModelMessage, ...]] = []

    def complete(
        self,
        messages: tuple[ModelMessage, ...],
        tools: tuple[ToolSpec, ...],
    ) -> object:
        del tools
        self.calls += 1
        self.requests.append(messages)
        if not self._responses:
            raise RuntimeError("Scripted model has no response remaining.")
        return self._responses.pop(0)
