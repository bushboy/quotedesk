import json
import logging
from typing import Any, Protocol

_log = logging.getLogger(__name__)

from quotedesk.application.dto.agent import ModelReply, ToolCall, TurnPrompt
from quotedesk.application.dto.tool_inputs import (
    AcceptQuoteInput,
    CheckAvailabilityInput,
    CreateDepositLinkInput,
    GetQuoteInput,
    HoldSlotInput,
    RequestChangeInput,
    UpdateCaseInput,
)
from quotedesk.application.errors import ModelTimeout, ToolArgumentsInvalid

_TOOL_TEXT = {
    "update_case": (
        "Record facts the customer stated or that an extraction supports. "
        "A new job includes job_type. "
        "This does not set a price."
    ),
    "get_quote": "Price the job from the case. The result is the only total and the only card link.",
    "request_change": "Ask to change an existing quote. The result says whether the request is waiting.",
    "check_availability": "Read the earliest date. This does not book the day.",
    "accept_quote": "Record that the customer accepts the current issued quote.",
    "create_deposit_link": "Return the deposit link for an accepted quote. The result is the only link.",
    "hold_slot": "Hold a day for a quote. The result says whether the day is held.",
}
_TOOLS = tuple(
    {
        "type": "function",
        "name": name,
        "description": _TOOL_TEXT[name],
        "parameters": model.model_json_schema(),
    }
    for name, model in (
        ("update_case", UpdateCaseInput),
        ("get_quote", GetQuoteInput),
        ("request_change", RequestChangeInput),
        ("check_availability", CheckAvailabilityInput),
        ("accept_quote", AcceptQuoteInput),
        ("create_deposit_link", CreateDepositLinkInput),
        ("hold_slot", HoldSlotInput),
    )
)


class Transport(Protocol):
    def post(self, url: str, body: dict[str, Any]) -> dict[str, Any]: ...


class SdkTransport:
    """Posts one Responses request through the OpenAI SDK. The test replaces this."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        from openai import APIStatusError, APITimeoutError, OpenAI

        base = url.removesuffix("/responses")
        client = OpenAI(api_key=self._api_key, base_url=base)
        try:
            payload = client.post("/responses", cast_to=object, body=body)
        except APITimeoutError as exc:
            raise TimeoutError from exc
        except APIStatusError as exc:
            _log.error("Spark call failed status=%s body=%s", exc.status_code, exc.body)
            raise
        except Exception as exc:
            _log.error("Spark call failed %s: %s", type(exc).__name__, exc)
            raise
        if isinstance(payload, dict):
            return payload
        _log.error("Spark call returned %s", type(payload).__name__)
        raise TypeError("The model response was not a JSON object.")


class SparkTurn:
    def __init__(self, *, model_id: str, base_url: str, transport: Transport) -> None:
        self._model_id = model_id
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    def complete(self, prompt: TurnPrompt) -> ModelReply:
        body = {
            "model": self._model_id,
            "instructions": prompt.task,
            "input": [{"role": "user", "content": _context(prompt)}],
            "tools": list(_TOOLS),
        }
        _log.info("Spark call model=%s", self._model_id)
        try:
            payload = self._transport.post(f"{self._base_url}/responses", body)
        except TimeoutError as exc:
            _log.warning("Spark call model=%s timed out", self._model_id)
            raise ModelTimeout() from exc
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if isinstance(status, int) and status >= 500:
                _log.warning("Spark call model=%s status=%s", self._model_id, status)
                raise ModelTimeout() from exc
            _log.exception("Spark call model=%s failed", self._model_id)
            raise
        reply = _reply(payload)
        tools = ", ".join(call.name for call in reply.tool_calls) or "none"
        _log.info("AI response text=%s tools=%s", reply.text, tools)
        return reply


def _context(prompt: TurnPrompt) -> str:
    dumped = prompt.model_dump(mode="json")
    context = {
        "messages": dumped["messages"],
        "case": dumped["case"],
        "rate_card": dumped["rate_card"],
        "extractions": dumped["extractions"],
        "tool_payloads": dumped["tool_payloads"],
        "business": dumped["business"],
    }
    return json.dumps(context, ensure_ascii=False)


def _reply(payload: dict[str, Any]) -> ModelReply:
    calls: list[ToolCall] = []
    texts: list[str] = []
    for item in payload.get("output") or []:
        if item.get("type") == "function_call":
            arguments = _arguments(item.get("arguments"))
            if arguments is None:
                raise ToolArgumentsInvalid()
            calls.append(ToolCall(name=str(item.get("name", "")), arguments=arguments))
        elif item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    texts.append(str(part.get("text") or ""))
    return ModelReply(text="".join(texts), tool_calls=tuple(calls))


def _arguments(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    return value
