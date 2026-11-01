"""
SUPPORTING DESIGN CHECKS: Integration test harness cleanup

User Story
----------
Supporting/supplementary design checks. No story or acceptance
criterion describes the behaviour these tests check; it is plumbing
that every story of this service relies on.

Real
----
- The integration harness cleanup helpers (process-group wait, container and
  log cleanup) run for real.
- Assertions are on what is cleaned up and what is reported.

Doubled
-------
- os.killpg, subprocess and docker calls: Stub / Mock - simulate permission
  errors, timeouts and failed removals; calls inspected.

Not proven
----------
- That real containers and process groups are removed (-> CI integration-tests
  job).
- These test test-support code, not app/; they add nothing to the app coverage
  figure.
"""
from unittest.mock import Mock, patch
import subprocess

from scripts.test_support.process_lifecycle import cleanup_owned_resources, wait_group_gone


# --- Supporting/supplementary design checks ----------------------------------
# No Jira acceptance criterion covers these. They check design decisions the
# stories rely on (health check, CORS, configuration and failure handling).


def test_wait_for_group_absence_retries_transient_permission_error(mocker):
    """
    Summary: wait_group_gone retries after one PermissionError from os.killpg and returns True once the group raises ProcessLookupError (gone).
    Supporting design check: the integration harness cleans up after itself
    Double: Stub (os.killpg raises PermissionError, then ProcessLookupError); no processes or containers touched
    """
    mocker.patch("scripts.test_support.process_lifecycle.os.killpg", side_effect=[PermissionError(), ProcessLookupError()])
    assert wait_group_gone(905, seconds=1)


def test_wait_for_group_absence_with_persistent_permission_error_never_succeeds(mocker):
    """
    Summary: wait_group_gone with a zero-second wait returns False when os.killpg keeps raising PermissionError, so the group is not assumed gone.
    Supporting design check: the integration harness cleans up after itself
    Double: Stub (os.killpg always raises PermissionError); no processes or containers touched
    """
    mocker.patch("scripts.test_support.process_lifecycle.os.killpg", side_effect=PermissionError())
    assert not wait_group_gone(905, seconds=0)


def test_cleanup_when_some_steps_fail_still_tries_every_resource(mocker):
    """
    Summary: cleanup_owned_resources kills both process groups, closes both logs and removes both containers although one process wait raises, one log close raises and one docker removal is refused; it returns exactly those 3 failures.
    Supporting design check: the integration harness cleans up after itself
    Double: Stub (second process wait raises RuntimeError; first log close raises OSError; docker rm of owned-two exits 1; wait_group_gone returns True), Mock (os.killpg called for 902 then 901; each log closed once; docker rm called for owned-two then owned-one)
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
    mocker.patch("scripts.test_support.process_lifecycle.wait_group_gone", return_value=True)
    kill = mocker.patch("scripts.test_support.process_lifecycle.os.killpg")
    mocker.patch("scripts.test_support.process_lifecycle.subprocess.run", side_effect=docker)
    failures = cleanup_owned_resources(processes, logs, ["owned-one", "owned-two"])
    assert [call.args[0] for call in kill.call_args_list] == [902, 901]
    assert all(log.close.call_count == 1 for log in logs)
    assert [call[-1] for call in calls if call[:3] == ["docker", "rm", "-fv"]] == ["owned-two", "owned-one"]
    assert len([call for call in calls if call[:3] == ["docker", "container", "ls"]]) == 2
    assert len(failures) == 3
    assert "wait failed" in failures[0]
    assert "close failed" in failures[1]
    assert "removal refused" in failures[2]


def test_cleanup_reports_container_still_present_after_removal(mocker):
    """
    Summary: cleanup_owned_resources reports one failure ("absence unverified owned") when the follow-up docker listing still shows the container after docker rm succeeded.
    Supporting design check: the integration harness cleans up after itself
    Double: Stub (docker rm succeeds; docker container ls then still lists "owned"); no real docker
    """
    results = [subprocess.CompletedProcess([], 0, "owned", ""),
               subprocess.CompletedProcess([], 0, "owned\n", "")]
    mocker.patch("scripts.test_support.process_lifecycle.subprocess.run", side_effect=results)
    failures = cleanup_owned_resources([], [], ["owned"])
    assert len(failures) == 1
    assert "absence unverified owned" in failures[0]


def test_cleanup_kills_timed_out_group_and_continues(mocker):
    """
    Summary: When the first process times out waiting, cleanup_owned_resources kills its group again (904, 903, 903), still handles the second process and the container, and returns no failures.
    Supporting design check: the integration harness cleans up after itself
    Double: Stub (first process wait raises TimeoutExpired then returns; wait_group_gone returns True, False, True; os.killpg raises ProcessLookupError once; docker run succeeds), Mock (killpg call order; docker called twice)
    """
    processes = [Mock(pid=903), Mock(pid=904)]
    processes[0].wait.side_effect = [subprocess.TimeoutExpired("owned", 10), 0]
    mocker.patch("scripts.test_support.process_lifecycle.wait_group_gone", side_effect=[True, False, True])
    kill = mocker.patch("scripts.test_support.process_lifecycle.os.killpg", side_effect=[ProcessLookupError(), None, None])
    docker = mocker.patch(
        "scripts.test_support.process_lifecycle.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")
    )
    assert cleanup_owned_resources(processes, [], ["owned"]) == []
    assert [call.args[0] for call in kill.call_args_list] == [904, 903, 903]
    assert docker.call_count == 2


def test_cleanup_removes_child_that_ignores_term(tmp_path):
    """
    Summary: Spawns a real process group whose forked child ignores SIGTERM; cleanup_owned_resources ends the leader with SIGTERM and leaves no process in the group.
    Supporting design check: the integration harness cleans up after itself
    Double: None (real child processes and process group; no docker, no mocker)
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
