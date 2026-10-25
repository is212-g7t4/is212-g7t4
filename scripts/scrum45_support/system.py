"""Resource support for scripts/scrum45_manual_sandbox.py.

SCRUM-45 cross-service tests/fixture have been handed off. Only the resource and
process lifecycle helpers imported by kept scripts and their safety tests remain.
This module does not start services or provision databases on import.
"""
import os
import signal
import socket
import subprocess
import time

def command(args, **kwargs):
    """Run a bounded command and return stripped stdout; fail with captured output if the command
    exits unsuccessfully.
    """
    result = subprocess.run(args, capture_output=True, text=True, timeout=90, **kwargs)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()

def wait(check, seconds=60):
    """Poll a callback until it returns a truthy value; return that value or fail at the deadline
    with the last exception.
    """
    end = time.monotonic() + seconds
    last = None
    while time.monotonic() < end:
        try:
            value = check()
            if value:
                return value
        except Exception as error:
            last = error
        time.sleep(0.2)
    raise AssertionError(f'Condition timed out: {last}')

def free_port():
    """Return an available loopback port; the temporary socket closes, so this is discovery rather
    than a lasting reservation.
    """
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]

def wait_group_gone(pgid, seconds):
    """Return true only after the supplied process group is absent; permission errors and timeout
    are not proof. Unreaped zombies can keep a group observable after its leader exits.
    """
    deadline = time.monotonic() + seconds
    while True:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)

def cleanup_owned_resources(processes, logs, names):
    """Stop only supplied owned process groups, close logs and remove named containers; attempt
    every resource and return failure diagnostics so cleanup cannot mask an earlier setup error.
    Callers must supply groups they created, not arbitrary PIDs.
    """
    failures = []
    for process in reversed(processes):
        try:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            if not wait_group_gone(process.pid, seconds=1):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
                if not wait_group_gone(process.pid, seconds=5):
                    raise RuntimeError('owned group absence unverified after SIGKILL (may include unreaped zombies)')
        except Exception as error:
            failures.append(f'process {process.pid}: {type(error).__name__}: {error}')
    for logfile in logs:
        try:
            logfile.close()
        except Exception as error:
            failures.append(f'log close: {type(error).__name__}: {error}')
    for name in reversed(names):
        try:
            removed = subprocess.run(['docker', 'rm', '-fv', name], capture_output=True, text=True, timeout=30)
            if removed.returncode:
                failures.append(f'docker rm {name}: {removed.returncode}: {removed.stderr.strip()}')
            inspected = subprocess.run(['docker', 'container', 'ls', '-a', '--filter', f'name=^/{name}$', '--format', '{{.Names}}'], capture_output=True, text=True, timeout=15)
            if inspected.returncode or inspected.stdout.strip():
                failures.append(f'container absence unverified {name}: {inspected.returncode}: {inspected.stdout.strip()} {inspected.stderr.strip()}')
        except Exception as error:
            failures.append(f'container {name}: {type(error).__name__}: {error}')
    return failures
