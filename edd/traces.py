"""Read a conversation's traces back from Phoenix over its REST API.

The supervisor starts one trace per user message (root span `supervisor`, with `conversation.turn`),
and every span carries `session.id` = the conversation id. Domain agents add their spans to the same
trace, so one trace holds the routing decision, the domain agent's run and its tool calls.
"""
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

SUPERVISOR_SPAN = "supervisor"
CLASSIFY_SPAN = "jev: classify intent"


@dataclass(frozen=True)
class Span:
    name: str
    kind: str  # OpenInference span kind, upper case: AGENT, LLM, TOOL, GUARDRAIL, ...
    trace_id: str
    span_id: str
    parent_id: str | None
    attributes: dict  # flat, dotted keys: "jev.intent.animals", "session.id", ...


@dataclass(frozen=True)
class Trace:
    """Every span of one turn (one user message)."""

    spans: list[Span]

    @property
    def root(self) -> Span:
        return next(s for s in self.spans if s.name == SUPERVISOR_SPAN)

    def span(self, name: str) -> Span | None:
        return next((s for s in self.spans if s.name == name), None)

    @property
    def action(self) -> str | None:
        return self.root.attributes.get("supervisor.action")

    @property
    def routed_to(self) -> str | None:
        return self.root.attributes.get("supervisor.intent")

    @property
    def intents(self) -> dict[str, float]:
        """Jev's probability per intent; empty when the turn was not classified (e.g. an approval)."""
        span = self.span(CLASSIFY_SPAN)
        prefix = "jev.intent."
        return {k.removeprefix(prefix): float(v) for k, v in (span.attributes if span else {}).items() if k.startswith(prefix)}

    @property
    def tools_called(self) -> list[str]:
        return [s.attributes.get("tool.name") or s.name for s in self.spans if s.kind == "TOOL"]

    @property
    def out_of_scope(self) -> bool:
        """A domain agent answered OUT_OF_SCOPE during this turn."""
        return any(s.attributes.get("agent.out_of_scope") is True for s in self.spans)

    def summary(self) -> str:
        intents = ", ".join(f"{k}={v:.2f}" for k, v in sorted(self.intents.items(), key=lambda kv: -kv[1])) or "-"
        fits = self.span(CLASSIFY_SPAN)
        fits_any = fits.attributes.get("jev.fits_any") if fits else None
        fits_text = f", fits_any={float(fits_any):.2f}" if fits_any is not None else ""
        return (
            f"action={self.action} routed_to={self.routed_to} | jev: {intents}{fits_text} | "
            f"tools: {', '.join(self.tools_called) or '-'}"
        )


class Phoenix:
    def __init__(self, url: str, project: str, timeout_seconds: float):
        self.client = httpx.Client(base_url=url, timeout=30)
        self.project = project
        self.timeout_seconds = timeout_seconds

    def spans_since(self, since: datetime) -> list[Span]:
        """All spans of the project that started after `since` (a page at a time)."""
        params: dict = {"start_time": since.isoformat(), "limit": 1000}
        spans = []
        while True:
            response = self.client.get(f"/v1/projects/{self.project}/spans", params=params)
            if response.status_code == 404:
                return []  # the project doesn't exist until the first span arrives
            response.raise_for_status()
            body = response.json()
            spans += [_span(raw) for raw in body.get("data", [])]
            if not (cursor := body.get("next_cursor")):
                return spans
            params["cursor"] = cursor

    def wait_for_turn(self, conversation_id: str, turn: int, since: datetime) -> Trace:
        """The trace of turn `turn`, once Phoenix has all its spans.

        Every agent exports spans in batches, so spans arrive over a few seconds. Wait until the
        supervisor's root span is in, then until the trace stops growing.
        """
        deadline = time.monotonic() + self.timeout_seconds
        previous = -1
        while True:
            spans = self.spans_since(since)
            root = next(
                (s for s in spans if s.name == SUPERVISOR_SPAN and s.attributes.get("session.id") == conversation_id
                 and int(s.attributes.get("conversation.turn", 0)) == turn),
                None,
            )
            if root:
                trace = [s for s in spans if s.trace_id == root.trace_id]
                if len(trace) == previous:
                    return Trace(trace)
                previous = len(trace)
            if time.monotonic() > deadline:
                state = f"{previous} spans so far" if root else "no supervisor span yet"
                raise TimeoutError(f"Turn {turn} of conversation {conversation_id} not complete in Phoenix after {self.timeout_seconds}s ({state})")
            time.sleep(2)


def _span(raw: dict) -> Span:
    attributes = _flatten(raw.get("attributes") or {})
    kind = raw.get("span_kind") or attributes.get("openinference.span.kind") or "UNKNOWN"
    context = raw.get("context") or {}
    return Span(
        name=raw.get("name", ""),
        kind=str(kind).upper(),
        trace_id=context.get("trace_id", ""),
        span_id=context.get("span_id", ""),
        parent_id=raw.get("parent_id"),
        attributes=attributes,
    )


def _flatten(value: dict, prefix: str = "") -> dict:
    """Phoenix may return attributes nested ({"jev": {"intent": {...}}}); use flat dotted keys either way."""
    flat = {}
    for key, item in value.items():
        if isinstance(item, dict):
            flat.update(_flatten(item, f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}"] = item
    return flat
