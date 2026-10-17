"""Supporting infrastructure: record actual pytest order/outcomes, optional FIRST ordering.

No acceptance assertions live here. Never changes fixtures, clocks or application state.
"""
import inspect
import json
import os
from pathlib import Path
import random


def append(record):
    path = os.environ.get("SCRUM173_PYTEST_EVIDENCE")
    if path:
        with Path(path).open("a") as stream:
            stream.write(json.dumps(record) + "\n")


def pytest_collection_modifyitems(items):
    order = os.environ.get("SCRUM173_TEST_ORDER")
    if order == "reverse":
        items.reverse()
    elif order == "shuffle":
        random.Random(173).shuffle(items)
    for item in items:
        append({"event": "collected", "id": item.nodeid,
                "description": inspect.getdoc(item.obj) or item.name,
                "parameters": repr(getattr(getattr(item, "callspec", None), "params", {}))})


def pytest_runtest_logstart(nodeid, location):
    append({"event": "started", "id": nodeid})


def pytest_runtest_logreport(report):
    append({"event": "result", "id": report.nodeid, "phase": report.when,
            "outcome": report.outcome, "seconds": report.duration,
            "failure": str(report.longrepr) if report.failed else None})
