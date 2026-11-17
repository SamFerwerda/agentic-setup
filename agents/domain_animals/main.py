from urllib.parse import quote

import httpx
from agents import Agent, function_tool

from common.config import AI_MODEL
from common.domain_app import create_domain_app, tool_error
from common.guardrails import block_input, block_output


@function_tool(failure_error_function=tool_error)
async def lookup_animal(name: str) -> str:
    """Look up an encyclopedia summary about an animal, e.g. 'Red fox'."""
    async with httpx.AsyncClient(headers={"User-Agent": "multi-agent-setup-demo"}, follow_redirects=True) as client:
        response = await client.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(name)}")
    return response.json().get("extract", "No information found.")


agent = Agent(
    name="animals_agent",
    model=AI_MODEL,
    instructions="You share fun, accurate facts about animals. Use lookup_animal to ground your answers.",
    tools=[lookup_animal],
    input_guardrails=[block_input(r"\b(hunt|poach|trap|poison)\w*")],  # no harming animals
    output_guardrails=[block_output(r"\b\d+\s?(mg|ml)\b")],  # no medication dosages; that's for a vet
)

app = create_domain_app(agent)
