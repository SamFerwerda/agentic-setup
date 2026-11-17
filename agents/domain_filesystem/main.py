from pathlib import Path

from agents import Agent, function_tool

from common.config import AI_MODEL, MAX_FILE_CHARS, WORKSPACE
from common.domain_app import create_domain_app, tool_error
from common.guardrails import SECRETS, block_input, block_output


def safe_path(path: str) -> Path:
    """Policy: the agent can only touch files inside the workspace."""
    full = (WORKSPACE / path.lstrip("/")).resolve()
    if not full.is_relative_to(WORKSPACE):
        raise ValueError(f"'{path}' is outside the workspace")
    return full


@function_tool(failure_error_function=tool_error)
def list_files(path: str = ".") -> list[str]:
    """List the files and folders in a workspace directory."""
    return sorted(p.name + ("/" if p.is_dir() else "") for p in safe_path(path).iterdir())


@function_tool(failure_error_function=tool_error)
def read_file(path: str) -> str:
    """Read a text file from the workspace."""
    return safe_path(path).read_text()[:MAX_FILE_CHARS]


@function_tool(failure_error_function=tool_error)
def write_file(path: str, content: str) -> str:
    """Create or overwrite a text file in the workspace."""
    target = safe_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"Wrote {len(content)} characters to {path}"


@function_tool(needs_approval=True, failure_error_function=tool_error)  # human in the loop: the run pauses until the user approves
def delete_file(path: str) -> str:
    """Delete a file from the workspace. The user is asked to approve first."""
    target = safe_path(path)
    if not target.exists():
        raise FileNotFoundError(f"There is no '{path}' in the workspace; use list_files to find the exact name")
    if not target.is_file():
        raise IsADirectoryError(f"'{path}' is a folder, not a file")
    target.unlink()
    return f"Deleted {path}"


agent = Agent(
    name="filesystem_agent",
    model=AI_MODEL,
    instructions=(
        "You manage files in the user's workspace. Use your tools to list, read, write and delete files. "
        "Before deleting, use list_files to get the file's exact name, including its extension. "
        "Deleting a file asks the user for approval; if they reject it, say so and do not retry."
    ),
    tools=[list_files, read_file, write_file, delete_file],
    input_guardrails=[block_input(r"\b(rm -rf|wipe)\b")],  # no bulk wipes; single deletes need approval
    output_guardrails=[block_output(SECRETS)],  # never leak credentials found in files
)

app = create_domain_app(agent)
