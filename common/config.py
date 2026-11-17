"""All configuration in one place: environment variables, endpoints, thresholds and limits.

Question wording and prompts stay next to the code that uses them (routing.py, safety.py).
Variables only one service needs are read with a default, so the other services still start.
"""
import os
from pathlib import Path

# --- Models -------------------------------------------------------------------------------------
AI_MODEL = os.environ["AI_MODEL"]  # LLM used by every agent
LLM_API_KEY = os.environ["LLM_API_KEY"]
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or None  # unset = OpenAI; set for an OpenAI-compatible provider
JEV_API_KEY = os.getenv("JEV_API_KEY", "")  # supervisor only

# --- Observability ------------------------------------------------------------------------------
PHOENIX_PROJECT = "multi-agent-setup"
PHOENIX_INTERNAL_URL = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix:6006")  # reachable from the containers
PHOENIX_PUBLIC_URL = os.getenv("PHOENIX_PUBLIC_URL", "http://localhost:6006")  # reachable from the browser

# --- Supervisor ---------------------------------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SESSION_TTL_SECONDS = 3600  # how long a conversation's memory lives in Redis
FRONTEND_ORIGINS = ["http://localhost:3000"]  # allowed by CORS
AGENT_TIMEOUT_SECONDS = 120  # per call to a domain agent

# Domain agents: name -> (URL, description). The description is the intent Jev classifies against.
DOMAIN_AGENTS = {
    "filesystem": ("http://domain_filesystem:8000", "Lists, reads, writes and deletes files in the user's workspace."),
    "animals": ("http://domain_animals:8000", "Answers questions and shares facts about animals."),
}

# Routing thresholds (see the decision table in agents/supervisor/routing.py)
ROUTE_THRESHOLD = 0.7  # top intent must be above this to route without asking
CLOSE_MARGIN = 0.2  # intents within this distance of the top one count as competing candidates
NO_FIT_THRESHOLD = 0.3  # "does any intent fit" below this means no intent covers the request
MAX_CLARIFICATIONS = 2  # after this many follow-up questions, fall back to web search
CONTINUE_THRESHOLD = 0.7  # above this, the user is continuing with the agent that answered last

# Safety guardrail: "llm" (the OpenAI-compatible LLM) or "jev"
GUARDRAIL_PROVIDER = os.getenv("GUARDRAIL_PROVIDER", "llm").lower()
if GUARDRAIL_PROVIDER not in ("llm", "jev"):
    raise ValueError(f"GUARDRAIL_PROVIDER must be 'llm' or 'jev', not {GUARDRAIL_PROVIDER!r}")
UNSAFE_THRESHOLD = 0.7  # with Jev, any safety check above this blocks the message

# --- Filesystem agent ---------------------------------------------------------------------------
WORKSPACE = Path("/workspace")  # the only folder the agent may touch
MAX_FILE_CHARS = 20_000  # read_file returns at most this many characters
