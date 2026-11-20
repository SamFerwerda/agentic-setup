"""Live terminal output for EDD runs: every turn as it happens, plus a P/F progress line kept at the bottom.

pytest captures output while a test runs and only prints one letter per test. This plugin writes past
the capture instead, so you see each message go out, the wait for the reply, and the verdict per turn.
On a terminal the progress line is redrawn in place at the bottom; without one (CI, piped output) it is
printed once at the end.
"""
import contextlib
import sys
import time

import pytest

CLEAR_LINE = "\r\x1b[2K"
LETTER_MARKUP = {"P": {"green": True, "bold": True}, "F": {"red": True, "bold": True},
                 "E": {"red": True, "bold": True}, "S": {"yellow": True, "bold": True}}

Part = str | tuple[str, dict]  # plain text, or (text, markup) such as ("PASSED", {"green": True})


class LiveReporter:
    def __init__(self, config: pytest.Config):
        self.config = config
        self.tty = sys.__stdout__.isatty()
        self.total = 0
        self.letters: list[str] = []
        self.waiting = ""  # what the running test waits on; shown next to the progress
        self._status_drawn = False
        self._case_started = 0.0
        self._turn_started = 0.0

    # --- called from the test -------------------------------------------------------------------

    def start_case(self, name: str, description: str) -> None:
        self._case_started = time.monotonic()
        self.line()
        self.line((name, {"bold": True, "cyan": True}), (f"  {description}" if description else "", {"light": True}))

    def send(self, turn: int, said: str) -> None:
        self._turn_started = time.monotonic()
        self.line(f"  turn {turn} ", ("→ ", {"bold": True}), _one_line(said))
        self.wait(f"turn {turn}: waiting for response")

    def wait(self, what: str) -> None:
        self.waiting = what
        if self.tty:
            self._write(self._draw_status)
        else:
            self.line("         … ", (what, {"light": True}))

    def turn_result(self, reply: str, failures: list[str], summary: str) -> None:
        self.waiting = ""
        took = time.monotonic() - self._turn_started
        self.line("         ", ("← ", {"bold": True}), _one_line(reply or "<no reply>"), (f"  ({took:.1f}s)", {"light": True}))
        verdict = ("FAIL", {"red": True, "bold": True}) if failures else ("ok  ", {"green": True, "bold": True})
        self.line("         ", verdict, " ", (summary, {"light": True}))
        for failure in failures:
            self.line("           ", ("- " + failure, {"red": True}))

    # --- pytest hooks ---------------------------------------------------------------------------

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.total = len(session.items)

    @pytest.hookimpl(tryfirst=True)
    def pytest_report_teststatus(self, report: pytest.TestReport):
        """Keep pytest from writing its own letters; this plugin draws the progress instead."""
        if report.when == "call" or report.failed or report.skipped:
            category = "error" if report.failed and report.when != "call" else report.outcome
            return category, "", category.upper()
        return None

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        letter = None
        if report.failed:
            letter = "F" if report.when == "call" else "E"
        elif report.skipped:
            letter = "S"
        elif report.when == "call":
            letter = "P"
        if letter is None:
            return
        self.waiting = ""
        self.letters.append(letter)
        word = {"P": "PASSED", "F": "FAILED", "E": "ERROR", "S": "SKIPPED"}[letter]
        name = report.nodeid.partition("[")[2].removesuffix("]") or report.nodeid
        took = time.monotonic() - self._case_started if self._case_started else report.duration
        self.line((word, LETTER_MARKUP[letter]), f" {name}", (f"  ({took:.1f}s)", {"light": True}))
        self._case_started = 0.0

    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionfinish(self) -> None:
        """Leave the final progress line on screen, above pytest's own summary."""
        self.waiting = ""
        def finish(tw):
            self._draw_status(tw, force=True)
            tw.line()
            self._status_drawn = False
        self._write(finish)

    # --- drawing --------------------------------------------------------------------------------

    def line(self, *parts: Part) -> None:
        def write(tw):
            if self._status_drawn:
                tw.write(CLEAR_LINE)
                self._status_drawn = False
            for part in parts:
                text, markup = (part, {}) if isinstance(part, str) else part
                tw.write(text, **markup)
            tw.line()
            self._draw_status(tw)
        self._write(write)

    def _draw_status(self, tw, force: bool = False) -> None:
        if not (self.tty or force):
            return
        if self._status_drawn:
            tw.write(CLEAR_LINE)
        width = max(tw.fullwidth - 1, 20)
        count = f" {len(self.letters)}/{self.total}"
        waiting = f"  │ {self.waiting}" if self.waiting else ""
        room = max(width - len("progress ") - len(count) - len(waiting), 10)
        pending = max(self.total - len(self.letters), 0)
        cells = self.letters + ["."] * pending
        if len(cells) > room:  # long runs: show the most recent results that fit
            cells = ["…"] + cells[-(room - 1):]
        tw.write("progress ", bold=True)
        for cell in cells:
            tw.write(cell, **LETTER_MARKUP.get(cell, {"light": True}))
        tw.write(count, bold=True)
        tw.write(waiting[: max(width - len("progress ") - len(cells) - len(count), 0)], yellow=True)
        tw.flush()
        self._status_drawn = True

    def _write(self, draw) -> None:
        reporter = self.config.pluginmanager.getplugin("terminalreporter")
        if reporter is None:
            return
        capman = self.config.pluginmanager.getplugin("capturemanager")
        with capman.global_and_fixture_disabled() if capman else contextlib.nullcontext():
            draw(reporter._tw)
            reporter._tw.flush()


def _one_line(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
