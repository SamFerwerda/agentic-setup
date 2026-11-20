"""Create a domain agent and register it with the supervisor in one command.

    python scripts/new_agent.py weather              # with Python (standard library only, nothing to install)
    docker compose run --rm new-agent weather        # or without Python, in a container

It asks for the agent's instructions and the description the supervisor routes on, then:
  1. writes agents/domain_<name>/main.py
  2. adds the agent to DOMAIN_AGENTS in common/config.py (the supervisor's intents)
  3. adds a domain_<name> service to docker-compose.yaml and to the supervisor's depends_on
  4. creates edd/cases/<name>.yaml for its eval cases
Pass --instructions "..." and --description "..." to skip the questions.
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

AGENT_TEMPLATE = '''\
from agents import Agent, function_tool

from common.config import AI_MODEL
from common.domain_app import create_domain_app, tool_error
from common.guardrails import block_input, block_output


# Give the agent tools: the docstring tells the model what the tool does and when to use it.
# @function_tool(failure_error_function=tool_error)
# def my_tool(question: str) -> str:
#     """Describe what this tool does, e.g. 'Look up the opening hours of a shop.'"""
#     return "..."


agent = Agent(
    name="{name}_agent",
    model=AI_MODEL,
    instructions={instructions},
    tools=[],  # e.g. [my_tool]
    input_guardrails=[],  # e.g. [block_input(r"\\b(forbidden|words)\\b")]
    output_guardrails=[],  # e.g. [block_output(r"\\bsecret\\b")]
)

app = create_domain_app(agent)
'''

CASES_TEMPLATE = """\
# Eval cases for the {name} domain agent.
# Each case runs as a fresh conversation against the supervisor and is judged from its Phoenix trace.
# See edd/README.md for the case format and every `expect` key. Uncomment and adapt:

# - id: {case_id}-basic
#   description: A plain {name} question goes straight to the {name} agent.
#   message: <a typical question for this agent>
#   expect:
#     action: route
#     agent: {name}
#     min_probability: 0.7
"""


# --- Text helpers that keep each file's line endings -----------------------------------------------
def read(path: Path) -> tuple[str, str]:
    raw = path.read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n"), eol


def write(path: Path, text: str, eol: str = "\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", eol).encode("utf-8"))


def py_string(value: str) -> str:
    """A double-quoted Python string literal (JSON string escapes are valid Python)."""
    return json.dumps(value, ensure_ascii=False)


# --- Repository edits ------------------------------------------------------------------------------
def add_to_config(config: str, name: str, description: str) -> str:
    match = re.search(r"^DOMAIN_AGENTS = \{\n(.*?)^\}", config, re.M | re.S)
    if not match:
        raise SystemExit("Could not find the `DOMAIN_AGENTS = {...}` block in common/config.py.")
    if re.search(rf'^\s*"{name}"\s*:', match.group(1), re.M):
        raise SystemExit(f"'{name}' is already in DOMAIN_AGENTS in common/config.py.")
    entry = f'    "{name}": ("http://domain_{name}:8000", {py_string(description)}),\n'
    return config[: match.end(1)] + entry + config[match.end(1):]


def add_to_compose(compose: str, name: str) -> str:
    service = f"domain_{name}"
    if re.search(rf"^  {service}:", compose, re.M):
        raise SystemExit(f"docker-compose.yaml already has a '{service}' service.")

    # Hook the new agent into the supervisor's depends_on, so it starts before the supervisor.
    supervisor = re.search(r"^  supervisor:\n(?:(?: {4}.*)?\n)*?( {4}depends_on: \[)([^\]]*)\]", compose, re.M)
    if not supervisor:
        raise SystemExit("Could not find the supervisor's `depends_on: [...]` in docker-compose.yaml.")
    deps = [d.strip() for d in supervisor.group(2).split(",") if d.strip()] + [service]
    compose = compose[: supervisor.start(2)] + ", ".join(deps) + compose[supervisor.end(2):]

    # Add the service right after the last domain agent's service.
    lines = compose.split("\n")
    domain_starts = [i for i, line in enumerate(lines) if re.match(r"^  domain_\w+:", line)]
    if not domain_starts:
        raise SystemExit("Could not find an existing domain_* service in docker-compose.yaml to add the new one after.")
    end = domain_starts[-1] + 1
    while end < len(lines) and (lines[end].startswith("    ") or not lines[end].strip()):
        end += 1
    while not lines[end - 1].strip():  # step back over blank lines
        end -= 1
    block = [
        "",
        f"  {service}:",
        "    <<: *agent",
        f"    build: {{ context: ., dockerfile: agents/Dockerfile, args: {{ AGENT: {service} }} }}",
    ]
    return "\n".join(lines[:end] + block + lines[end:])


# --- Prompts ---------------------------------------------------------------------------------------
def ask(question: str, hint: str) -> str:
    print(f"\n{question}\n  {hint}")
    while True:
        try:
            answer = input("> ").strip()
        except EOFError:
            raise SystemExit("\nCancelled.")
        if answer:
            return answer
        print("  Please type something (Ctrl+C to cancel).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a domain agent and register it with the supervisor.")
    parser.add_argument("name", help="Short name, e.g. weather (becomes agents/domain_weather)")
    parser.add_argument("--instructions", help="The agent's instructions; asked for when left out")
    parser.add_argument("--description", help="The supervisor's description of the agent; asked for when left out")
    args = parser.parse_args()

    name = args.name.strip().lower().replace("-", "_").removeprefix("domain_")
    if not NAME_PATTERN.match(name):
        raise SystemExit(f"'{args.name}' is not a valid agent name: use letters, digits and underscores, starting with a letter (e.g. weather).")

    agent_dir = ROOT / "agents" / f"domain_{name}"
    config_path, compose_path = ROOT / "common" / "config.py", ROOT / "docker-compose.yaml"
    cases_path = ROOT / "edd" / "cases" / f"{name}.yaml"
    if agent_dir.exists():
        raise SystemExit(f"agents/domain_{name} already exists.")

    # Check the files we edit before asking anything, so a problem shows up front.
    config, config_eol = read(config_path)
    compose, compose_eol = read(compose_path)
    add_to_config(config, name, "check")
    add_to_compose(compose, name)

    print(f"Creating the '{name}' agent.")
    instructions = args.instructions or ask(
        "What are the agent's instructions (its system prompt)?",
        "e.g. You give weather forecasts for any city. Keep answers short and mention the temperature in Celsius.",
    )
    description = args.description or ask(
        "How should the supervisor describe this agent? It routes requests on this description.",
        "e.g. Answers questions about the weather and forecasts for a place.",
    )

    # Compute every change first, then write, so a failure leaves the repository untouched.
    new_config = add_to_config(config, name, description)
    new_compose = add_to_compose(compose, name)
    write(agent_dir / "main.py", AGENT_TEMPLATE.format(name=name, instructions=py_string(instructions)))
    write(config_path, new_config, config_eol)
    write(compose_path, new_compose, compose_eol)
    created_cases = not cases_path.exists()
    if created_cases:
        write(cases_path, CASES_TEMPLATE.format(name=name, case_id=name.replace("_", "-")))

    print(f"\nDone! The '{name}' agent is ready:")
    print(f"  created  agents/domain_{name}/main.py")
    print("  updated  common/config.py  (DOMAIN_AGENTS: the supervisor now routes to it)")
    print(f"  updated  docker-compose.yaml  (service domain_{name})")
    if created_cases:
        print(f"  created  edd/cases/{name}.yaml  (eval cases)")
    print("\nNext: add tools to main.py, then run `docker compose up --build`.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("\nCancelled.")
