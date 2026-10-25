"""SCRUM-45: safely explore notification outcomes without touching shared data.

Launcher safeguards support SCRUM-45 AC1 approval, AC2 rejection, AC3 decision
content/link and AC4 initial assignment/reassignment; they are not new story ACs.
Real: environment/config builders, launcher imports/help, Node config evaluation
and owned local process cleanup. No shared database is used.
The final test is opt-in: it alone starts an isolated multi-service sandbox and
Docker resources. It checks readiness/cleanup, not end-to-end notification delivery.
Not proven: business outcomes, hosted Supabase or production authentication.
Run with the repository-root no-project uv command in the manual runbook.
"""
import importlib.util
from pathlib import Path
import socket
import sys

SCRIPT = Path(__file__).with_name('scrum45_manual_sandbox.py')


def load():
    """Import the manual launcher from its exact file and return the module without starting a
    sandbox.
    """
    assert SCRIPT.exists(), 'Manual sandbox launcher has not been implemented'
    spec = importlib.util.spec_from_file_location('scrum45_manual_sandbox', SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_launcher_help_and_support_imports_work_outside_the_repository(tmp_path):
    """Normal: run launcher help and support imports from repository and unrelated directories;
    successful exits and resolved asset paths show relocation works without starting sandbox
    resources.
    """
    import os
    import subprocess

    root = SCRIPT.resolve().parents[1]
    env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR', 'SSL_CERT_FILE') if key in os.environ}
    env.update(PYTHON_DOTENV_DISABLED='1', FLASK_SKIP_DOTENV='1', PYTHONDONTWRITEBYTECODE='1')
    probe = '''import importlib.util, sys
from pathlib import Path
script = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('scrum45_manual_sandbox', script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from scripts.scrum45_support import system, migration_helpers
assert module.cleanup_owned_resources is system.cleanup_owned_resources
assert migration_helpers.ROOT == script.resolve().parents[1]
assert migration_helpers.MIGRATIONS.is_dir()
assert list(migration_helpers.MIGRATIONS.glob('*.sql'))
assert module.cleanup_owned_resources.__module__ == 'scripts.scrum45_support.system'
'''
    for cwd in (root, tmp_path):
        help_result = subprocess.run([sys.executable, str(SCRIPT), '--help'], cwd=cwd,
                                     env=env, capture_output=True, text=True, timeout=15)
        assert help_result.returncode == 0, help_result.stderr
        assert '--state-dir' in help_result.stdout
        imported = subprocess.run([sys.executable, '-c', probe, str(SCRIPT)], cwd=cwd,
                                  env=env, capture_output=True, text=True, timeout=15)
        assert imported.returncode == 0, imported.stderr
    assert not (root / 'e2e' / 'scrum45').exists()


def test_frontend_config_overrides_every_api_and_discards_ambient_secrets(tmp_path):
    """Failure: feed ambient shared-service credentials and URLs into environment builders; secret
    keys disappear and every frontend API targets loopback, preventing manual tests from falling
    back to shared systems.
    """
    sandbox = load()
    env = sandbox.isolated_environment({'PATH': '/bin', 'HOME': '/synthetic',
        'DATABASE_URL': 'forbidden', 'VITE_EVENT_SERVICE_URL': 'https://forbidden',
        'SUPABASE_URL': 'forbidden', 'PGHOST': 'forbidden', 'NODE_OPTIONS': 'forbidden'})
    assert env['PYTHON_DOTENV_DISABLED'] == env['FLASK_SKIP_DOTENV'] == '1'
    assert not any(k in env for k in ('DATABASE_URL', 'SUPABASE_URL', 'PGHOST', 'NODE_OPTIONS'))
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        unavailable = f'http://127.0.0.1:{reserved.getsockname()[1]}'
        urls = {'event-service': 'http://127.0.0.1:46123'}
        config = sandbox.frontend_environment(env, urls, unavailable)
        expected = sandbox.frontend_api_keys()
        assert {'VITE_EVENT_SERVICE_URL', 'VITE_EQUIPMENT_SERVICE_URL', 'VITE_USER_SERVICE_URL',
                'VITE_NOTIFICATION_SERVICE_URL', 'VITE_EVENT_WORKFLOW_SERVICE_URL'} <= expected
        assert {key for key in config if key.startswith('VITE_')} == expected
        assert config['VITE_EVENT_SERVICE_URL'] == urls['event-service']
        assert all(value.startswith('http://127.0.0.1:') for key, value in config.items() if key.startswith('VITE_'))
        assert config['VITE_EQUIPMENT_SERVICE_URL'] == unavailable


def test_lifecycle_cleans_only_owned_process_on_setup_exception_and_preserves_state(tmp_path):
    """Failure: raise during sandbox setup while a bystander process runs; only the owned group
    disappears and stopped-state evidence remains, preventing partial startup from leaking or
    killing unrelated work.
    """
    import json
    import os
    import subprocess
    import pytest
    module = load()
    assert hasattr(module, 'Sandbox'), 'Owned manual lifecycle is not implemented'
    bystander = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)'], start_new_session=True)
    state = tmp_path / 'owned'
    try:
        with pytest.raises(RuntimeError, match='deliberate setup failure'):
            with module.Sandbox(state) as sandbox:
                owned = sandbox.run_process('probe', [sys.executable, '-c', 'import time; time.sleep(90)'], tmp_path)
                raise RuntimeError('deliberate setup failure')
        assert owned.poll() is not None
        with pytest.raises(ProcessLookupError):
            os.killpg(owned.pid, 0)
        assert bystander.poll() is None
        manifest = json.loads((state / 'state.json').read_text())
        assert manifest['status'] == 'stopped'
        assert manifest['cleanupFailures'] == []
        with pytest.raises(FileExistsError):
            with module.Sandbox(state):
                pass
    finally:
        os.killpg(bystander.pid, 15)
        bystander.wait(timeout=5)


def test_vite_config_disables_dotenv_and_removes_external_font_links(tmp_path):
    """Normal: execute the generated Vite configuration with Node; dotenv is disabled, external
    font markup is removed and CSP permits only local APIs, preventing unintended browser
    egress.
    """
    import json
    import subprocess
    module = load()
    assert hasattr(module, 'vite_config'), 'Sandbox Vite egress guard is not implemented'
    path = tmp_path / 'vite.config.mjs'
    path.write_text(module.vite_config({'frontend': 'http://127.0.0.1:46123', 'event-service': 'http://127.0.0.1:46124'}))
    script = "const {default:c}=await import(process.argv[1]); console.log(JSON.stringify({envDir:c.envDir,headers:c.server.headers,html:c.plugins[0].transformIndexHtml('<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" /><link href=\"/favicon.svg\" />')}))"
    result = subprocess.run(['node', '--input-type=module', '-e', script, path.as_uri()],
                            check=True, capture_output=True, text=True)
    config = json.loads(result.stdout)
    assert config['envDir'] is False
    assert config['html'] == '<link href="/favicon.svg" />'
    policy = config['headers']['Content-Security-Policy']
    assert "default-src 'self'" in policy
    assert 'http://127.0.0.1:46124' in policy
    assert 'https:' not in policy


def test_assignment_fixture_is_submitted_so_the_lead_queue_can_find_it():
    """Normal: build synthetic fixtures; the assignment event is Submitted with no coordinator,
    making it eligible for the Lead queue instead of an unrelated review state.
    """
    fixtures = load().synthetic_fixtures()
    assert fixtures['events']['assignment']['status'] == 'Submitted'
    assert fixtures['events']['assignment']['coordinatorId'] is None


def test_real_cli_holds_healthy_fixtures_until_interrupt_then_removes_owned_resources(tmp_path):
    """Normal (explicit opt-in only): start the isolated CLI, check healthy services and synthetic
    fixtures, then interrupt; stopped state and exact process/container/volume absence prove
    lifecycle cleanup, not notification delivery.
    """
    import json
    import os
    import signal
    import subprocess
    import time
    import httpx
    import pytest
    if os.environ.get('SCRUM45_RUN_MANUAL_TEST') != '1':
        pytest.skip('Explicit opt-in: starts owned Docker containers and local service processes')
    state = tmp_path / 'manual'
    with (tmp_path / 'launcher.log').open('w') as log:
        process = subprocess.Popen([sys.executable, str(SCRIPT), '--state-dir', str(state)],
            stdout=log, stderr=subprocess.STDOUT)
        try:
            end = time.monotonic() + 180
            manifest = {}
            while time.monotonic() < end:
                assert process.poll() is None, (tmp_path / 'launcher.log').read_text()
                try:
                    manifest = json.loads((state / 'state.json').read_text())
                    if manifest['status'] == 'ready':
                        break
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
                time.sleep(0.2)
            assert manifest.get('status') == 'ready', (tmp_path / 'launcher.log').read_text()
            fixtures = json.loads((state / 'fixtures.json').read_text())
            assert set(fixtures['events']) == {'rejection', 'approval', 'assignment', 'reassignment'}
            for service, url in manifest['urls'].items():
                assert url.startswith('http://127.0.0.1:')
                assert httpx.get(url + ('' if service == 'frontend' else '/health')).status_code == 200
            frontend = httpx.get(manifest['urls']['frontend'])
            assert 'fonts.googleapis.com' not in frontend.text
            assert 'fonts.gstatic.com' not in frontend.text
            assert "default-src 'self'" in frontend.headers['Content-Security-Policy']
            for event in fixtures['events'].values():
                response = httpx.get(manifest['urls']['event-service'] + '/events/' + event['id'],
                                     params={'organiserId': fixtures['users']['organiser']['id']})
                assert response.status_code == 200
                assert response.json()['eventName'] == event['name']
            queue = httpx.get(manifest['urls']['coordinator-assignment-service'] + '/queue',
                              params={'actingUserId': fixtures['users']['lead']['id']})
            assert queue.status_code == 200
            assert [event['id'] for event in queue.json()['events']] == [fixtures['events']['assignment']['id']]
            assert process.poll() is None
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
            process.wait(timeout=90)
    assert process.returncode == 0, (tmp_path / 'launcher.log').read_text()
    manifest = json.loads((state / 'state.json').read_text())
    assert manifest['status'] == 'stopped'
    assert manifest['cleanupFailures'] == []
    for owned in manifest['processes']:
        with pytest.raises(ProcessLookupError):
            os.killpg(owned['pgid'], 0)
    containers = subprocess.run(['docker', 'container', 'ls', '-a', '--format', '{{.Names}}'],
                                capture_output=True, text=True, check=True).stdout.splitlines()
    volumes = subprocess.run(['docker', 'volume', 'ls', '--format', '{{.Name}}'],
                             capture_output=True, text=True, check=True).stdout.splitlines()
    assert not set(manifest['containers']).intersection(containers)
    assert not set(manifest['volumes']).intersection(volumes)
