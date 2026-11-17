import re

from agents import GuardrailFunctionOutput, input_guardrail, output_guardrail

SECRETS = r"(api[_-]?key|password|secret|token)\s*[:=]"
BLOCKED_REPLY = "Sorry, I can't help with that request."


def _last_user_message(data) -> str:
    return data if isinstance(data, str) else str(data[-1].get("content", ""))


def block_input(pattern: str):
    """Input guardrail that trips when the latest user message matches `pattern`."""
    @input_guardrail(name=f"block_input:{pattern}")
    async def guard(ctx, agent, data):
        return GuardrailFunctionOutput(output_info=pattern, tripwire_triggered=bool(re.search(pattern, _last_user_message(data), re.I)))
    return guard


def block_output(pattern: str):
    """Output guardrail that trips when the agent's reply matches `pattern`."""
    @output_guardrail(name=f"block_output:{pattern}")
    async def guard(ctx, agent, output):
        return GuardrailFunctionOutput(output_info=pattern, tripwire_triggered=bool(re.search(pattern, str(output), re.I)))
    return guard
