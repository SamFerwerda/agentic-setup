import logging
import uuid

from agents import Agent, InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered, RunContextWrapper, Runner, trace
from fastapi import FastAPI, HTTPException, Request
from opentelemetry import trace as otel_trace

from common.contract import OUT_OF_SCOPE, ApprovalRequest, ChatRequest, ChatResponse, Message
from common.guardrails import BLOCKED_REPLY
from common.runtime import setup
from common.tracing import incoming_request

SCOPE_POLICY = f"If a request is outside your domain, reply with exactly {OUT_OF_SCOPE} and nothing else."
logger = logging.getLogger("uvicorn.error")  # uvicorn's handler, so it shows in `docker compose logs`


def tool_error(ctx: RunContextWrapper, error: Exception) -> str:
    """`failure_error_function` for domain tools: record the real error, and tell the model what went wrong.

    The SDK's default hides the exception from the model ("An error occurred while running the tool"),
    so neither the user nor Phoenix learns why a tool failed.
    """
    span = otel_trace.get_current_span()  # the failing tool's span
    span.record_exception(error)  # exception event with type, message and stack trace in Phoenix
    span.set_attributes({"tool.error.type": type(error).__name__, "tool.error.message": str(error)})
    logger.warning("Tool failed: %s: %s", type(error).__name__, error, exc_info=error)
    return f"The tool failed with {type(error).__name__}: {error}"


def create_domain_app(agent: Agent) -> FastAPI:
    """Expose a domain agent over POST /chat using the shared supervisor contract."""
    tracer = setup(agent.name)
    agent.instructions = f"{agent.instructions}\n{SCOPE_POLICY}"
    app = FastAPI(title=agent.name, telemetry={"tracing": False})  # our agent span is the meaningful one
    # Runs paused on a tool that needs approval, by approval id. Kept here rather than sent to the
    # supervisor, so a caller can never hand back a tampered run state. (In-process: one replica.)
    paused = {}

    @app.post("/chat")
    async def chat(body: ChatRequest, request: Request) -> ChatResponse:
        # Join the supervisor's trace and conversation so the whole request is one trace in Phoenix.
        with incoming_request(request.headers), tracer.start_as_current_span(agent.name, openinference_span_kind="agent") as span:
            span.set_input(body.messages[-1].content if body.messages else "")
            run_input = [m.model_dump() for m in body.messages]
            if body.approval:  # resume the paused run with the user's decision
                if not (pending := paused.pop(body.approval.id, None)):
                    raise HTTPException(404, "Unknown or expired approval id")
                run_input, item = pending
                if body.approval.approved:
                    run_input.approve(item)
                else:
                    run_input.reject(item)
                span.set_attribute("approval.approved", body.approval.approved)
            try:
                # The Agents SDK instrumentation traces the run, its LLM calls, tool calls and guardrails.
                # Start a fresh SDK trace: on resume the SDK would otherwise reattach the paused run's trace
                # without telling the trace processors, so Phoenix would drop every span of the resumed run.
                with trace(f"{agent.name} run"):
                    result = await Runner.run(agent, run_input)
                if result.interruptions:  # a tool needs the user's approval: pause and ask, one call at a time
                    state = result.to_state()
                    item = state.get_interruptions()[0]
                    approval = ApprovalRequest(id=str(uuid.uuid4()), tool=item.name, arguments=_arguments(item))
                    paused[approval.id] = (state, item)
                    span.set_attribute("approval.tool", approval.tool)
                    reply = f"I need your approval to run `{approval.tool}` with {approval.arguments}."
                    span.set_output(reply)
                    return ChatResponse(messages=[Message(role="assistant", content=reply)], approval=approval)
                reply = str(result.final_output)
            except (InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered) as tripped:
                span.set_attribute("guardrail.triggered", type(tripped).__name__)
                reply = BLOCKED_REPLY
            span.set_attribute("agent.out_of_scope", reply == OUT_OF_SCOPE)
            span.set_output(reply)
        return ChatResponse(messages=[Message(role="assistant", content=reply)])

    return app


def _arguments(item) -> str:
    raw = item.raw_item
    return str(raw.get("arguments", "") if isinstance(raw, dict) else getattr(raw, "arguments", ""))
