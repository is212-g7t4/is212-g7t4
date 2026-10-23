"""SCRUM-45: As an Event Organiser, I want to receive an in-app notification
when the Lead Coordinator approves or rejects my event request, so that I know
the outcome and who is responsible for coordinating my event.
AC2/AC3/DR9: unmocked browser decision -> actual delivery -> inbox -> linked details.
"""
import json
import subprocess

import httpx
import pytest

from tests.integration.system import HEADERS, LEAD, ORGANISER, ROOT, free_port, wait

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]


def test_lead_rejection_reaches_organiser_inbox_and_linked_details_in_real_browser(system, tmp_path):
    """AC2/AC3: Playwright uses actual UI/HTTP services, PostgreSQL and RabbitMQ.
    Lead is the legitimately assigned coordinator; organiser opens persisted
    rejection from inbox and reads reason. No page.route, API stubs or secrets.
    """
    s = system
    # Fixture establishes pre-story assignment without emitting unrelated work.
    s["sql"]("events", 'UPDATE public."Event" SET coordinator_id=%s WHERE event_id=%s', (LEAD, s["event"]))
    s["env"]["CALENDAR_DEV_MODE"] = "true"
    port = free_port()
    s["urls"]["venue-availability-service"] = f"http://127.0.0.1:{port}"
    s["start"]("venue-availability-service", ["-m", "flask", "--app", "app", "run", "--host", "127.0.0.1", "--port", str(port)], "availability")
    wait(lambda: s["http"]("venue-availability-service", "GET", "/health").status_code == 200)
    ui = ROOT / "frontend/event-management-ui"
    frontend_env = {**s["env"],
        "VITE_USER_SERVICE_URL": s["urls"]["user-service"],
        "VITE_EVENT_SERVICE_URL": s["urls"]["event-service"],
        "VITE_NOTIFICATION_SERVICE_URL": s["urls"]["notification-service"],
        "VITE_COORDINATOR_ASSIGNMENT_SERVICE_URL": s["urls"]["coordinator-assignment-service"],
        "VITE_VENUE_AVAILABILITY_SERVICE_URL": s["urls"]["venue-availability-service"]}
    # Programmatic Vite config explicitly uses an EMPTY external envDir; never
    # load root/service/frontend .env, and never bind the user's manual UI port.
    config = tmp_path / "vite.config.mjs"
    config.write_text("export default {envDir: " + json.dumps(str(tmp_path)) + "}")
    with (tmp_path / "vite.log").open("w") as logfile:
        vite = subprocess.Popen(["node", str(ui / "node_modules/vite/bin/vite.js"),
            "--config", str(config), "--host", "localhost", "--port", s["urls"]["frontend"].rsplit(":", 1)[1],
            "--strictPort"], cwd=ui, env=frontend_env, stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True)
        s["processes"].append(vite)
        wait(lambda: httpx.get(s["urls"]["frontend"], timeout=2).status_code == 200)
        s["start"]("notification-service", ["-m", "app.consumer"], "notifications")
        dispatcher = s["start"]("event-workflow-service", ["-m", "app.dispatcher"])
        result = subprocess.run(["node", str(ui / "e2e-real/scrum45-journey.mjs")], cwd=ui,
            env={**frontend_env, "SCRUM45_FRONTEND": s["urls"]["frontend"],
                 "SCRUM45_EVENT": s["event"], "SCRUM45_LEAD": LEAD,
                 "SCRUM45_ORGANISER": ORGANISER, "SCRUM45_ARTIFACTS": str(tmp_path)},
            capture_output=True, text=True, timeout=90)
        (tmp_path / "browser.log").write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        assert dispatcher.poll() is None
    # Independent owner/inbox reads verify persisted side effects after browser assertions.
    event = s["http"]("event-service", "GET", f"/events/{s['event']}?organiserId={ORGANISER}")
    assert event.status_code == 200
    assert event.json()["decision"]["status"] == "Rejected"
    assert event.json()["decision"]["reason"] == "Browser journey requires a safety plan."
    inbox = s["http"]("notification-service", "GET", "/notifications", headers={
        "X-Dev-User-Id": ORGANISER, "X-Dev-Role": "Event Organiser"}).json()["notifications"]
    assert len(inbox) == 1
    assert inbox[0]["type"] == "event.rejection"
    assert inbox[0]["readAt"] is not None
    assert s["http"]("event-service", "POST", "/internal/notification-outbox/claim", headers=HEADERS, json={}).json()["jobs"] == []
