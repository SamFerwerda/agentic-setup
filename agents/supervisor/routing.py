"""Intent routing with Jev: the questions and decision table live here (thresholds are in common/config.py).

Jev makes the judgments (which intent, does any intent fit); `decide` turns them into an action.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, NoulCriteria

from common.config import CLOSE_MARGIN, CONTINUE_THRESHOLD, MAX_CLARIFICATIONS, NO_FIT_THRESHOLD, ROUTE_THRESHOLD

Handler = Callable[[list[dict]], Awaitable[str]]


@dataclass(frozen=True)
class Intent:
    name: str  # sent to Jev as the option name, so keep it descriptive (e.g. "animal_facts")
    description: str  # what the user wants when this intent applies
    handler: Handler = field(compare=False)  # receives the conversation, returns the reply


class Action(Enum):
    ROUTE = "route"
    CLARIFY = "clarify"
    WEB_SEARCH = "web_search"


@dataclass(frozen=True)
class Decision:
    action: Action
    intent: Intent | None = None  # set for ROUTE
    candidates: list[Intent] = field(default_factory=list)  # set for CLARIFY
    sticky: bool = False  # routed to the active agent because the user continues with it


@dataclass(frozen=True)
class Classification:
    probabilities: dict[str, float]  # intent name -> probability, sums to ~1
    fits_any: float  # probability that one of the intents covers the request at all
    continues_active: float | None = None  # probability the user continues with the active agent; None if none
    model: str = ""  # versioned Jev model that answered, for tracing
    input_tokens: int | None = None
    output_tokens: int | None = None


def _state(history: list[dict]) -> dict:
    # Named speakers and the full thread, so earlier clarifying answers count.
    return {"conversation": [{"from": m["role"], "text": m["content"]} for m in history]}


def _questions(intents: list[Intent], active: Intent | None) -> dict:
    criteria = {i.name: i.description for i in intents}
    covered = "; ".join(i.description for i in intents)
    questions = {
        # Short replies like "yes" or "the second one" only make sense with the earlier turns.
        "intent": Choice(
            instructions="Reading the whole `conversation`, what does the user want help with right now?",
            criteria=criteria,
        ),
        # A Choice always picks something, so ask separately whether anything fits.
        "fits_any": Noul(
            instructions="Reading the whole `conversation`, does what the user wants right now fall under one of these services?",
            criteria=NoulCriteria(
                true=f"What the user wants is covered by one of: {covered}",
                false="The user wants something none of these services handle, such as the weather or news.",
            ),
        ),
    }
    if active:
        # Asked speculatively: code only reads it when an agent answered the previous turn.
        questions["continues_active"] = Noul(
            instructions=f"The last assistant message in `conversation` came from the service that {active.description[0].lower()}{active.description[1:]} "
            "Is the user's latest message part of the same exchange with that service?",
            criteria=NoulCriteria(
                true="The user answers the service's question or follows up on the same subject, such as \"yes\" or \"and where do they live?\".",
                false="The user moves on to a request about a different subject.",
            ),
        )
    return questions


async def classify(client: AsyncTypeSafeClient, history: list[dict], intents: list[Intent], active: Intent | None = None) -> Classification:
    response = await client.system_one(state=_state(history), questions=_questions(intents, active))
    return Classification(
        probabilities=dict(response.choices["intent"].probabilities),
        fits_any=response.nouls["fits_any"].noul,
        continues_active=response.nouls["continues_active"].noul if active else None,
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


def decide(result: Classification, intents: list[Intent], clarifications_asked: int, active: Intent | None = None) -> Decision:
    """Decision table (`active` is the agent that answered the previous turn, if any):

    | continues_active > 0.7 | fits_any < 0.3 | top > 0.7, no runner-up within 0.2 | clarifications < 2 | action          |
    |------------------------|----------------|------------------------------------|--------------------|-----------------|
    | yes                    | -              | -                                  | -                  | route to active |
    | no / no active agent   | yes            | -                                  | -                  | web search      |
    | no / no active agent   | no             | yes                                | -                  | route           |
    | no / no active agent   | no             | no                                 | yes                | clarify         |
    | no / no active agent   | no             | no                                 | no                 | web search      |
    """
    if active and result.continues_active is not None and result.continues_active > CONTINUE_THRESHOLD:
        return Decision(Action.ROUTE, intent=active, sticky=True)
    if result.fits_any < NO_FIT_THRESHOLD:
        return Decision(Action.WEB_SEARCH)

    by_name = {i.name: i for i in intents}
    ranked = sorted(result.probabilities.items(), key=lambda kv: kv[1], reverse=True)
    top_name, top_p = ranked[0]
    close = [name for name, p in ranked[1:] if top_p - p < CLOSE_MARGIN]

    if top_p > ROUTE_THRESHOLD and not close:
        return Decision(Action.ROUTE, intent=by_name[top_name])
    if clarifications_asked >= MAX_CLARIFICATIONS:
        return Decision(Action.WEB_SEARCH)
    # Ask between the top intent and its close competitors; if nothing is close, top two.
    names = [top_name, *close] if close else [name for name, _ in ranked[:2]]
    return Decision(Action.CLARIFY, candidates=[by_name[n] for n in names])
