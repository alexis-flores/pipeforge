"""Test-session plumbing: requirement-traceability capture (§9).

Running ``pytest --rtm-out=docs/rtm.csv`` regenerates the requirement
traceability matrix from ``@pytest.mark.req("ID")`` markers and live
outcomes.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

_results: dict[str, list[tuple[str, str]]] = {}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--rtm-out",
        default=None,
        help="write the requirement traceability matrix CSV to this path",
    )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when != "call" and not (report.when == "setup" and report.skipped):
        return
    keywords = dict(report.keywords)
    if "req" not in keywords:
        return
    # marker args are not in keywords; stored via user_properties instead
    for name, value in report.user_properties:
        if name == "req":
            outcome = "skipped" if report.skipped else report.outcome
            _results.setdefault(str(value), []).append((report.nodeid, outcome))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):  # type: ignore[no-untyped-def]
    for marker in item.iter_markers(name="req"):
        if marker.args:
            prop = ("req", str(marker.args[0]))
            if prop not in item.user_properties:
                item.user_properties.append(prop)
    yield


def pytest_sessionfinish(session: pytest.Session) -> None:
    out = session.config.getoption("--rtm-out")
    if not out:
        return
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["requirement", "test_id", "status"])
        for req in sorted(_results):
            for nodeid, outcome in sorted(set(_results[req])):
                writer.writerow([req, nodeid, outcome])
