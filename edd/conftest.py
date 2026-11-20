"""pytest wiring: one test per case in edd/cases/*.yaml, plus a coverage note for intents without cases."""
import os
import time

import httpx
import pytest

from cases import load_cases
from live import LiveReporter
from traces import Phoenix

SUPERVISOR_URL = os.getenv("SUPERVISOR_URL", "http://localhost:8000")
SUPERVISOR_PUBLIC_URL = os.getenv("SUPERVISOR_PUBLIC_URL", "http://localhost:8000")  # for Phoenix links in reports
PHOENIX_URL = os.getenv("PHOENIX_URL", "http://localhost:6006")
PHOENIX_PROJECT = os.getenv("PHOENIX_PROJECT", "multi-agent-setup")
TRACE_TIMEOUT_SECONDS = float(os.getenv("EDD_TRACE_TIMEOUT", "60"))
STARTUP_TIMEOUT_SECONDS = 180  # first `docker compose run` also builds and starts the stack

CASES = load_cases()
SEEN_INTENTS: set[str] = set()  # every intent the supervisor classified against during this run


def pytest_configure(config):
    config.pluginmanager.register(LiveReporter(config), "edd-live")


@pytest.fixture(scope="session")
def live(pytestconfig) -> LiveReporter:
    return pytestconfig.pluginmanager.get_plugin("edd-live")


def pytest_generate_tests(metafunc):
    if "case" in metafunc.fixturenames:
        metafunc.parametrize("case", CASES, ids=[f"{c.file.removesuffix('.yaml')}:{c.id}" for c in CASES])


@pytest.fixture(scope="session")
def supervisor() -> httpx.Client:
    client = httpx.Client(base_url=SUPERVISOR_URL, timeout=180)
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while True:
        try:
            if client.get("/openapi.json").status_code == 200:
                return client
        except httpx.TransportError:
            pass
        if time.monotonic() > deadline:
            pytest.exit(f"Supervisor not reachable at {SUPERVISOR_URL}; is `docker compose up` running?", returncode=2)
        time.sleep(2)


@pytest.fixture(scope="session")
def phoenix() -> Phoenix:
    return Phoenix(PHOENIX_URL, PHOENIX_PROJECT, TRACE_TIMEOUT_SECONDS)


def phoenix_link(conversation_id: str) -> str:
    return f"{SUPERVISOR_PUBLIC_URL}/conversations/{conversation_id}/phoenix"


def pytest_terminal_summary(terminalreporter):
    covered = {agent for case in CASES for agent in case.agents}
    if missing := sorted(SEEN_INTENTS - covered):
        terminalreporter.write_sep("-", "intents without eval cases", yellow=True)
        for name in missing:
            terminalreporter.write_line(f"{name}: no case expects this agent; add edd/cases/{name}.yaml")
