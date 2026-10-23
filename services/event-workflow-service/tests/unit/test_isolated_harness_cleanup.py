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
    with patch("tests.integration.system.os.killpg") as kill, patch("tests.integration.system.subprocess.run", side_effect=docker):
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
    with patch("tests.integration.system.os.killpg", side_effect=[ProcessLookupError(), None, None]) as kill, patch(
        "tests.integration.system.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")
    ) as docker:
        assert cleanup_owned_resources(processes, [], ["owned"]) == []
    assert [call.args[0] for call in kill.call_args_list] == [904, 903, 903]
    assert docker.call_count == 2
