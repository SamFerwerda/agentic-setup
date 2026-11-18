"""Load eval cases from edd/cases/*.yaml.

Every YAML file is a list of cases; by convention one file per domain agent. A case is one fresh
conversation: one or more turns, each with the outcome the system should reach for that turn.
"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CASES_DIR = Path(__file__).parent / "cases"

# Everything a turn can expect; see edd/README.md. Unknown keys fail loudly, so a typo can't silently skip a check.
EXPECT_KEYS = {"action", "agent", "min_probability", "tools_called", "tools_not_called", "reply_contains", "approval"}


@dataclass(frozen=True)
class Turn:
    message: str | None  # a user message, or
    approve: bool | None  # the user's answer to a pending tool approval
    expect: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Case:
    id: str
    file: str
    description: str
    turns: list[Turn]

    @property
    def agents(self) -> set[str]:
        return {t.expect["agent"] for t in self.turns if "agent" in t.expect}


def load_cases(directory: Path = CASES_DIR) -> list[Case]:
    cases = [_case(raw, path.name) for path in sorted(directory.glob("*.yaml")) for raw in yaml.safe_load(path.read_text(encoding="utf-8")) or []]
    seen = set()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"Duplicate case id {case.id!r}; ids must be unique across all files in {directory}")
        seen.add(case.id)
    return cases


def _case(raw: dict, file: str) -> Case:
    where = f"{file}, case {raw.get('id', '<no id>')!r}"
    if "id" not in raw:
        raise ValueError(f"{where}: every case needs an `id`")
    # Single-turn shorthand: `message`/`approve` and `expect` directly on the case.
    raw_turns = raw.get("turns") or [{k: raw[k] for k in ("message", "approve", "expect") if k in raw}]
    turns = []
    for n, t in enumerate(raw_turns, start=1):
        if ("message" in t) == ("approve" in t):
            raise ValueError(f"{where}, turn {n}: needs exactly one of `message` or `approve`")
        expect = t.get("expect") or {}
        if unknown := set(expect) - EXPECT_KEYS:
            raise ValueError(f"{where}, turn {n}: unknown expect keys {sorted(unknown)}; allowed: {sorted(EXPECT_KEYS)}")
        if "min_probability" in expect and "agent" not in expect:
            raise ValueError(f"{where}, turn {n}: `min_probability` needs `agent`, the intent it applies to")
        turns.append(Turn(message=t.get("message"), approve=t.get("approve"), expect=expect))
    return Case(id=raw["id"], file=file, description=raw.get("description", ""), turns=turns)
