"""The contract every domain agent shares with the supervisor: POST /chat with messages[]."""
from typing import Literal

from pydantic import BaseModel

# A domain agent replies with exactly this when a request is outside its domain,
# so the supervisor can route it to another agent.
OUT_OF_SCOPE = "OUT_OF_SCOPE"


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ApprovalRequest(BaseModel):
    """A tool call the agent paused on until the user approves it (human in the loop)."""
    id: str
    tool: str
    arguments: str  # JSON


class ApprovalDecision(BaseModel):
    id: str  # the ApprovalRequest.id being answered
    approved: bool


class ChatRequest(BaseModel):
    messages: list[Message]  # the conversation so far, oldest first
    approval: ApprovalDecision | None = None  # set to resume a paused run instead of starting a new one


class ChatResponse(BaseModel):
    messages: list[Message]  # the messages the agent added
    approval: ApprovalRequest | None = None  # set when the run is paused waiting for the user
