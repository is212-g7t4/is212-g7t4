"""# SCRUM-173 — Receive Venue Disruption Notifications

As an Event Coordinator, I want to receive an in-app notification when a venue booking for an event assigned to me is affected, so that I know that alternative arrangements are required.
AC1: Given a rejection is ready for notification, then the notification is addressed to the coordinator assigned to that event when the notification is created.
AC2: The notification contains the event name, affected venue, closure start/end, rejection reason, and a link to the venue rejection.
AC3: Given a temporary system failure occurs during notification dispatch, the system must ensure the notification is eventually delivered to the assigned coordinator without generating multiple duplicate alerts.

## AC1 / AC2 / AC3 — real opt-in integration adapter
Runs the established real HTTP/PostgreSQL/RabbitMQ acceptance harness under pytest.
Not a mocked replacement: creates four owned databases and actual service/worker
processes. setup() and finally cleanup() belong to this test, including failures.
Default pytest excludes this marker and does not import the optional driver.
The 22 verification groups are recorded separately, not counted as 22 direct ACs.
"""
import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_isolated_notification_delivery_and_recovery(tmp_path):
    """## AC1 / AC2 / AC3 + supporting infrastructure
    Actual closure, frozen current recipient/content, broker/database outages,
    lease/unknown-outcome recovery and deduplicated read-preserving inbox delivery.
    Expected: every harness assertion and owned-resource teardown succeeds.
    """
    source = Path(__file__).with_name("verify_scrum173_backend.py")
    spec = importlib.util.spec_from_file_location("scrum173_real_harness", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the owned integration harness")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evidence = Path(os.environ.get("SCRUM173_INTEGRATION_EVIDENCE", str(tmp_path / "real")))
    harness = module.Harness(evidence)
    try:
        harness.setup()
        module.exercise(harness)
    finally:
        harness.cleanup()
