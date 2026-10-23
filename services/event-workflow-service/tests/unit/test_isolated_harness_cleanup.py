"""SCRUM-45: As an Event Organiser, I want to receive an in-app notification
when the Lead Coordinator approves or rejects my event request, so that I know
the outcome and who is responsible for coordinating my event.
DR3 verification infrastructure: isolated fixtures must report cleanup honestly.
"""
from unittest.mock import Mock, patch
import subprocess

from tests.integration.system import cleanup_owned_resources


def test_cleanup_attempts_all_resources_despite_process_log_and_container_failures():
    """DR3 isolation: inject boundary failures and observe all process/log/container
    attempts, exact container readback and returned diagnostics, not silent cleanup.
    """
    processes = [Mock(pid=901), Mock(pid=902)]
    processes[1].wait.side_effect = RuntimeError("wait failed")
    logs = [Mock(), Mock()]
    logs[0].close.side_effect = OSError("close failed")
    calls = []
    def docker(args, **kwargs):
        calls.append(args)
        if args[:3] == ["docker", "rm", "-fv"] and args[-1] == "owned-two":
            return subprocess.CompletedProcess(args, 1, "", "removal refused")
        return subprocess.CompletedProcess(args, 0, "", "")
    with patch("tests.integration.system.wait_group_gone", return_value=True), patch("tests.integration.system.os.killpg") as kill, patch("tests.integration.system.subprocess.run", side_effect=docker):
        failures = cleanup_owned_resources(processes, logs, ["owned-one", "owned-two"])
    assert [call.args[0] for call in kill.call_args_list] == [902, 901]
    assert all(log.close.call_count == 1 for log in logs)
    assert [call[-1] for call in calls if call[:3] == ["docker", "rm", "-fv"]] == ["owned-two", "owned-one"]
    assert len([call for call in calls if call[:3] == ["docker", "container", "ls"]]) == 2
    assert len(failures) == 3
    assert "wait failed" in failures[0]
    assert "close failed" in failures[1]
    assert "removal refused" in failures[2]


def test_cleanup_reports_remaining_container_even_after_successful_removal_response():
    """DR3 isolation: successful docker rm is not proof; exact readback that still
    finds the owned container must be reported rather than claiming removal.
    """
    results = [subprocess.CompletedProcess([], 0, "owned", ""),
               subprocess.CompletedProcess([], 0, "owned\n", "")]
    with patch("tests.integration.system.subprocess.run", side_effect=results):
        failures = cleanup_owned_resources([], [], ["owned"])
    assert len(failures) == 1
    assert "absence unverified owned" in failures[0]


def test_cleanup_kills_timed_out_process_group_and_continues_after_missing_group():
    """DR3 isolation: timeout escalates only owned process group; already absent
    group is harmless and container cleanup still executes and verifies absence.
    """
    processes = [Mock(pid=903), Mock(pid=904)]
    processes[0].wait.side_effect = [subprocess.TimeoutExpired("owned", 10), 0]
    with patch("tests.integration.system.wait_group_gone", side_effect=[True, False, True]), patch("tests.integration.system.os.killpg", side_effect=[ProcessLookupError(), None, None]) as kill, patch(
        "tests.integration.system.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")
    ) as docker:
        assert cleanup_owned_resources(processes, [], ["owned"]) == []
    assert [call.args[0] for call in kill.call_args_list] == [904, 903, 903]
    assert docker.call_count == 2


def test_cleanup_removes_term_ignoring_child_after_group_leader_exits(tmp_path):
    """DR3: create only our own session; parent exits on TERM while its ready
    child ignores TERM. Require ESRCH for the whole group, not leader exit.
    A bounded emergency kill in finally keeps a RED run from leaking the child.
    """
    import os
    import signal
    import sys
    import time

    ready = tmp_path / "child-ready"
    script = """
import os, signal, sys, time
from pathlib import Path
if os.fork() == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    Path(sys.argv[1]).write_text(str(os.getpid()))
    time.sleep(60)
else:
    time.sleep(60)
"""
    process = subprocess.Popen([sys.executable, "-c", script, str(ready)], start_new_session=True)

    def group_absent():
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return True
        return False

    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "owned child did not install its TERM handler"
        child = int(ready.read_text())
        assert os.getpgid(child) == process.pid
        assert cleanup_owned_resources([process], [], []) == []
        assert process.returncode == -signal.SIGTERM
        assert group_absent(), "leader exited but owned process group still exists"
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        deadline = time.monotonic() + 5
        while not group_absent() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert group_absent(), "owned group remains (possibly unreaped orphan zombies)"
