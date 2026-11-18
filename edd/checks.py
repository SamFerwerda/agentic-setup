"""Compare one turn's trace (and the supervisor's reply) with what the case expects."""
from traces import Trace


def evaluate(trace: Trace, expect: dict, response: dict) -> list[str]:
    """Every expectation the turn missed, as readable lines; empty when the turn passed."""
    failures = []

    if (want := expect.get("action")) and trace.action != want:
        failures.append(f"action: expected {want!r}, got {trace.action!r}")

    if agent := expect.get("agent"):
        intents = trace.intents
        if intents and agent not in intents:
            failures.append(f"agent: {agent!r} is not an intent the supervisor knows (intents: {sorted(intents)})")
        if trace.routed_to != agent:
            failures.append(f"agent: expected routing to {agent!r}, got {trace.routed_to!r}")
        elif trace.out_of_scope:
            failures.append(f"agent: {agent!r} replied OUT_OF_SCOPE")
        if (minimum := expect.get("min_probability")) is not None and agent in intents and intents[agent] < minimum:
            failures.append(f"min_probability: {agent!r} classified at {intents[agent]:.2f}, expected at least {minimum:.2f}")

    called = trace.tools_called
    for tool in expect.get("tools_called", []):
        if tool not in called:
            failures.append(f"tools_called: {tool!r} was not called (called: {called or 'none'})")
    for tool in expect.get("tools_not_called", []):
        if tool in called:
            failures.append(f"tools_not_called: {tool!r} was called")

    reply = response.get("reply") or ""
    for text in expect.get("reply_contains", []):
        if text.lower() not in reply.lower():
            failures.append(f"reply_contains: {text!r} not in reply {reply[:200]!r}")

    if "approval" in expect:
        got = (response.get("approval") or {}).get("tool")
        if got != expect["approval"]:
            failures.append(f"approval: expected an approval request for {expect['approval']!r}, got {got!r}")

    return failures
