"""Infra: SCRUM-45 retained manual-sandbox lifecycle safety tests.

Supporting DR3 (retry/recovery) requires verification resources to be cleaned up
honestly; these are not additional acceptance criteria or delivery tests.
Real: cleanup/wait helpers; the final test starts only its own local process group.
Doubled: process signalling, clock-adjacent waits and Docker calls in other cases.
Not proven: notification delivery, real Docker removal, shared-stack safety or any
service's business rules. The process regression checks exact owned-group absence.
"""
from unittest.mock import Mock, patch
import subprocess

from scripts.scrum45_support.system import cleanup_owned_resources, wait_group_gone


def test_group_absence_wait_retries_transient_permission_without_claiming_success():
    """Boundary: simulate permission denied followed by process-group absence; the wait succeeds
    only after absence is observed, avoiding a false cleanup claim during macOS reaping.
    """
    with patch("scripts.scrum45_support.system.os.killpg", side_effect=[PermissionError(), ProcessLookupError()]):
        assert wait_group_gone(905, seconds=1)


def test_group_absence_wait_never_treats_persistent_permission_as_absence():
    """Failure: simulate persistent permission denied with an expired wait budget; the wait returns
    false rather than treating an inaccessible group as removed.
    """
    with patch("scripts.scrum45_support.system.os.killpg", side_effect=PermissionError()):
        assert not wait_group_gone(905, seconds=0)


def test_cleanup_attempts_all_resources_despite_process_log_and_container_failures():
    """Failure: inject process-wait, log-close and container-removal errors; cleanup attempts every
    resource and returns all three diagnostics, so one failure cannot hide later leaks.
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
    with patch("scripts.scrum45_support.system.wait_group_gone", return_value=True), patch("scripts.scrum45_support.system.os.killpg") as kill, patch("scripts.scrum45_support.system.subprocess.run", side_effect=docker):
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
    """Conflict: return success from removal but still list the exact owned container; cleanup
    reports unverified absence, so command success cannot masquerade as resource removal.
    """
    results = [subprocess.CompletedProcess([], 0, "owned", ""),
               subprocess.CompletedProcess([], 0, "owned\n", "")]
    with patch("scripts.scrum45_support.system.subprocess.run", side_effect=results):
        failures = cleanup_owned_resources([], [], ["owned"])
    assert len(failures) == 1
    assert "absence unverified owned" in failures[0]


def test_cleanup_kills_timed_out_process_group_and_continues_after_missing_group():
    """Failure: simulate an absent group and a timed-out owned process; cleanup escalates only the
    owned group and still verifies container absence, preserving bounded and complete teardown.
    """
    processes = [Mock(pid=903), Mock(pid=904)]
    processes[0].wait.side_effect = [subprocess.TimeoutExpired("owned", 10), 0]
    with patch("scripts.scrum45_support.system.wait_group_gone", side_effect=[True, False, True]), patch("scripts.scrum45_support.system.os.killpg", side_effect=[ProcessLookupError(), None, None]) as kill, patch(
        "scripts.scrum45_support.system.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")
    ) as docker:
        assert cleanup_owned_resources(processes, [], ["owned"]) == []
    assert [call.args[0] for call in kill.call_args_list] == [904, 903, 903]
    assert docker.call_count == 2


def test_cleanup_removes_term_ignoring_child_after_group_leader_exits(tmp_path):
    """Failure: start an owned group whose parent exits on TERM while its ready child ignores TERM;
    cleanup must remove the entire group, not merely reap the leader. A bounded emergency kill
    prevents leakage if the assertion fails.
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
    # Publish readiness atomically: existence must imply a complete child PID.
    ready_file = Path(sys.argv[1])
    pending = ready_file.with_suffix('.pending')
    pending.write_text(str(os.getpid()))
    pending.replace(ready_file)
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
