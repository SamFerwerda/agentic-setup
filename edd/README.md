# Evaluation-driven development (EDD)

Test cases describe what the system **should** do with a query. The runner sends each query to the running supervisor, reads the resulting traces back from Phoenix, and compares what actually happened with what was expected. That covers how Jev classified the query, which agent it was routed to, which tools ran, and what the reply said.

Change a prompt, an intent description, a threshold or a tool, then rerun the evals to see whether the system still behaves as intended.

## Run

Start the stack first (`docker compose up --build`), then in a second terminal:

```sh
docker compose run --rm edd
```

`edd/` is mounted into the container, so edits to cases take effect without a rebuild.

To run without Docker (Python 3.13):

```sh
pip install -r edd/requirements.txt
pytest edd
```

| Variable | Default | Purpose |
|---|---|---|
| `SUPERVISOR_URL` | `http://localhost:8000` | Where the runner sends messages |
| `PHOENIX_URL` | `http://localhost:6006` | Where the runner reads traces |
| `PHOENIX_PROJECT` | `multi-agent-setup` | Phoenix project the agents write to |
| `SUPERVISOR_PUBLIC_URL` | `http://localhost:8000` | Base of the trace links in failure reports |
| `EDD_TRACE_TIMEOUT` | `60` | Seconds to wait for a turn's spans to reach Phoenix |

Every case runs as its own conversation and shows up in Phoenix under **Sessions** like a normal chat.

## Cases

Cases live in `edd/cases/*.yaml`, one file per domain agent. The runner picks up every file in that folder, so no runner code names a specific agent.

```yaml
- id: red-fox-facts                 # unique across all files
  description: A plain animal question goes straight to the animals agent.
  message: Tell me something about the red fox.
  expect:
    action: route                   # supervisor.action
    agent: animals                  # the domain agent it was routed to (supervisor.intent)
    min_probability: 0.7            # Jev's probability for `agent` must be at least this
    tools_called: [lookup_animal]   # each must appear as a TOOL span in the turn's trace
    reply_contains: [fox]           # case-insensitive substrings of the reply
```

A case with several turns uses `turns`. Each turn is either a `message` or an `approve: true|false` answer to a pending tool approval. Each turn is judged on its own trace:

```yaml
- id: delete-with-approval
  description: Deleting a file asks for approval and deletes it once approved.
  turns:
    - message: Create a file called edd-check.txt containing hello.
      expect: { agent: filesystem, tools_called: [write_file] }
    - message: Now delete edd-check.txt.
      expect: { agent: filesystem, approval: delete_file }
    - approve: true
      expect: { action: approval, tools_called: [delete_file] }
```

### `expect` keys

All keys are optional. Unknown keys are rejected, so a typo can't silently skip a check.

| Key | Passes when |
|---|---|
| `action` | `supervisor.action` equals it: `route`, `clarify`, `web_search`, `blocked`, `approval`, or a fallback such as `web_search_after_out_of_scope` |
| `agent` | The supervisor routed to this domain agent, the name is one of Jev's intents, and the agent did not reply `OUT_OF_SCOPE` |
| `min_probability` | Jev's probability for `agent` is at least this (needs `agent`) |
| `tools_called` | Every listed tool ran during the turn |
| `tools_not_called` | None of the listed tools ran during the turn |
| `reply_contains` | Every listed text appears in the reply (case-insensitive) |
| `approval` | The reply asks the user to approve this tool |

### What the runner reads from Phoenix

Each user message is one trace rooted at the supervisor span, and every span carries `session.id` = the conversation id. The runner finds the trace of turn *n* by `session.id` and `conversation.turn`, and waits until it stops growing, because agents export spans in batches. It then reads:

- `supervisor.action` and `supervisor.intent` on the `supervisor` span
- `jev.intent.<agent>` on the `jev: classify intent` span
- every span of kind `TOOL`, from any agent in the trace
- `agent.out_of_scope` on the domain agent's span

## Adding a domain agent

1. Add the agent as usual (`DOMAIN_AGENTS` in `common/config.py`, `docker-compose.yaml`).
2. Rerun the evals. The existing cases must still pass. A new agent with an overlapping description takes probability from the others, and the `min_probability` checks catch that.
3. Add `edd/cases/<agent>.yaml` with at least one case. Until you do, the run ends with an **intents without eval cases** note naming the agent.

## Failure report

A failing case lists each turn with what happened and why the check failed, plus a link that opens the conversation in Phoenix:

```text
turn 1 FAIL: 'Which files are in my workspace?'
    action=route routed_to=animals | jev: animals=0.93, filesystem=0.05, fits_any=0.98 | tools: lookup_animal
    - agent: expected routing to 'filesystem', got 'animals'
    - min_probability: 'filesystem' classified at 0.05, expected at least 0.70
    - tools_called: 'list_files' was not called (called: ['lookup_animal'])
trace: http://localhost:8000/conversations/<id>/phoenix
```

The runs use the real LLM, Jev and tools, so results can vary between runs and each run costs tokens.
