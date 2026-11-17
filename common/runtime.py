from functools import cache

from agents import set_default_openai_api, set_default_openai_client
from openai import AsyncOpenAI
from phoenix.otel import register

from common.config import LLM_API_KEY, LLM_BASE_URL, PHOENIX_PROJECT


@cache
def llm_client() -> AsyncOpenAI:
    """The OpenAI-compatible client, shared by agents and plain completion calls."""
    return AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)


def setup(service_name: str):
    """Point the Agents SDK at our LLM and send every agent span to Phoenix."""
    set_default_openai_client(llm_client(), use_for_tracing=False)
    if LLM_BASE_URL:
        set_default_openai_api("chat_completions")  # most OpenAI-compatible providers lack the Responses API
    # auto_instrument picks up openinference-instrumentation-openai-agents.
    provider = register(project_name=PHOENIX_PROJECT, batch=True, auto_instrument=True)
    return provider.get_tracer(service_name)
