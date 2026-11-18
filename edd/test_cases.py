"""Run each case as a fresh conversation against the supervisor, then judge it from its Phoenix traces."""
import uuid
from datetime import datetime, timedelta, timezone

import conftest
from cases import Case
from checks import evaluate


def test_case(case: Case, supervisor, phoenix):
    conversation_id = str(uuid.uuid4())
    since = datetime.now(timezone.utc) - timedelta(seconds=5)  # margin for clock differences with Phoenix
    report = []
    failed = False

    for n, turn in enumerate(case.turns, start=1):
        body = {"conversation_id": conversation_id}
        body.update({"message": turn.message} if turn.message is not None else {"approved": turn.approve})
        response = supervisor.post("/chat", json=body)
        response.raise_for_status()

        trace = phoenix.wait_for_turn(conversation_id, n, since)
        conftest.SEEN_INTENTS.update(trace.intents)
        failures = evaluate(trace, turn.expect, response.json())
        failed |= bool(failures)
        said = turn.message if turn.message is not None else ("<approve>" if turn.approve else "<reject>")
        report.append(f"turn {n} {'FAIL' if failures else 'ok'}: {said!r}\n    {trace.summary()}")
        report += [f"    - {f}" for f in failures]

    assert not failed, "\n".join([case.description, *report, f"trace: {conftest.phoenix_link(conversation_id)}"])
