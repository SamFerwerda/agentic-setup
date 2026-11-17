"""Conversation-scoped tracing shared by the supervisor and domain agents.

Every span carries `session.id` (the frontend's conversation id), so Phoenix groups a whole
conversation into one session, and each request is one trace across all agents.
"""
from contextlib import contextmanager
from typing import Iterator, Mapping

from openinference.instrumentation import using_session
from opentelemetry import baggage, context
from opentelemetry.propagate import extract, inject

CONVERSATION_KEY = "conversation.id"  # W3C baggage key that carries the id between agents


@contextmanager
def conversation(conversation_id: str) -> Iterator[None]:
    """Tag every span started inside this block with the conversation id, and propagate it."""
    token = context.attach(baggage.set_baggage(CONVERSATION_KEY, conversation_id))
    try:
        with using_session(conversation_id):
            yield
    finally:
        context.detach(token)


def outgoing_headers() -> dict[str, str]:
    """`traceparent` + `baggage` headers so the callee's spans join this trace and conversation."""
    headers: dict[str, str] = {}
    inject(headers)
    return headers


@contextmanager
def incoming_request(headers: Mapping[str, str]) -> Iterator[None]:
    """Continue the caller's trace and conversation from its request headers."""
    ctx = extract(headers)
    token = context.attach(ctx)
    try:
        conversation_id = baggage.get_baggage(CONVERSATION_KEY, ctx)
        if conversation_id:
            with using_session(str(conversation_id)):
                yield
        else:
            yield
    finally:
        context.detach(token)
