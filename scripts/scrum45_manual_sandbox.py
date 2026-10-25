"""Owned, disposable SCRUM-45 manual UI; no dotenv or shared services.

Run the exact uv command in docs/scrum-45-isolated-manual-testing.md.
This launcher deliberately reuses ordinary lifecycle helpers, not pytest fixtures.
"""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'frontend/event-management-ui'
sys.path.insert(0, str(ROOT))
from scripts.scrum45_support.system import cleanup_owned_resources, command, free_port, wait


class Sandbox:
    """Track only resources created in this process; state is evidence, not a kill list."""
    def __init__(self, state):
        self.state = Path(state).resolve()
        self.env = isolated_environment()
        self.identifier = 'scrum45-manual-' + uuid4().hex[:12]
        self.processes, self.logs, self.names, self.volumes = [], [], [], []
        self.urls, self.dsns = {}, {}
        self.reserved = None
        self.status = 'starting'
        self.failures = []

    def record(self):
        (self.state / 'state.json').write_text(json.dumps(dict(
            status=self.status, identifier=self.identifier, urls=self.urls,
            containers=self.names, volumes=self.volumes,
            processes=[dict(pid=p.pid, pgid=p.pid) for p in self.processes],
            cleanupFailures=self.failures), indent=2))

    def __enter__(self):
        self.state.mkdir(parents=True, exist_ok=False)
        self.record()
        return self

    def run_process(self, name, args, cwd, env=None):
        logfile = (self.state / f'{name}.log').open('w')
        self.logs.append(logfile)
        process = subprocess.Popen(args, cwd=cwd, env=self.env if env is None else env,
            stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True)
        self.processes.append(process)
        self.record()
        return process

    def setup(self):
        import httpx
        import psycopg2
        from scripts.scrum45_support.migration_helpers import Database, MIGRATIONS
        command(['docker', 'info', '--format', '{{.ServerVersion}}'])
        for service in ('event-service', 'notification-service', 'user-service',
                        'coordinator-assignment-service', 'venue-availability-service', 'event-workflow-service'):
            if not (ROOT / 'services' / service / '.venv/bin/python').exists():
                raise RuntimeError(f'Missing {service}/.venv; see runbook prerequisites')
        if not (UI / 'node_modules/vite/bin/vite.js').exists():
            raise RuntimeError('Missing frontend node_modules; see runbook prerequisites')
        self.urls['frontend'] = f'http://127.0.0.1:{free_port()}'
        self.env['FRONTEND_ORIGIN'] = self.urls['frontend']
        for suffix, image, port, variables in (
            ('postgres', 'postgres:17.6', 5432, {'POSTGRES_USER': 'isolated', 'POSTGRES_PASSWORD': 'synthetic-only'}),
            ('rabbit', 'rabbitmq:4-management', 5672, {'RABBITMQ_DEFAULT_USER': 'isolated', 'RABBITMQ_DEFAULT_PASS': 'synthetic-only'}),
        ):
            name = self.identifier + '-' + suffix
            self.names.append(name)
            self.record()
            command(['docker', 'run', '-d', '--name', name, '--label', 'connectsphere.test=scrum45-manual',
                     '-p', f'127.0.0.1::{port}',
                     *[item for key, value in variables.items() for item in ('-e', f'{key}={value}')], image])
            mounts = json.loads(command(['docker', 'inspect', '--format', '{{json .Mounts}}', name]))
            self.volumes.extend(m['Name'] for m in mounts if m['Type'] == 'volume')
            self.record()
            binding = command(['docker', 'port', name, str(port)])
            assert binding.startswith('127.0.0.1:'), binding
            selected = binding.rsplit(':', 1)[1]
            if suffix == 'postgres':
                admin = f'postgresql://isolated:synthetic-only@127.0.0.1:{selected}/isolated?connect_timeout=2'
            else:
                self.env['RABBITMQ_URL'] = f'amqp://isolated:synthetic-only@127.0.0.1:{selected}/%2F'
        def postgres_ready():
            connection = psycopg2.connect(admin)
            connection.close()
            return True
        wait(postgres_ready)
        wait(lambda: subprocess.run(['docker', 'exec', '-u', 'rabbitmq', self.names[1],
             'rabbitmq-diagnostics', '-q', 'check_running'], capture_output=True, timeout=15).returncode == 0)
        fixtures = synthetic_fixtures()
        for database in ('events', 'notifications', 'users', 'availability'):
            connection = psycopg2.connect(admin)
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute('CREATE DATABASE ' + database)
            connection.close()
            self.dsns[database] = admin.replace('/isolated?', '/' + database + '?')
            connection = psycopg2.connect(self.dsns[database])
            try:
                db = Database(connection)
                db.apply(sorted(MIGRATIONS.glob('*.sql')))
                for user in fixtures['users'].values():
                    db.query('INSERT INTO public."User"(user_id,username,email,role) VALUES (%s,%s,%s,%s)',
                             (user['id'], user['name'], user['id'] + '@example.invalid', user['role']))
                for event in fixtures['events'].values():
                    db.query('''INSERT INTO public."Event"(event_id,event_name,organiser_id,coordinator_id,status,
                                description,expected_attendance,preferred_start_date,preferred_end_date,submission_date)
                                VALUES (%s,%s,%s,%s,%s,%s,25,'2030-02-01 10:00Z','2030-02-01 12:00Z',now())''',
                             (event['id'], event['name'], fixtures['users']['organiser']['id'],
                              event['coordinatorId'], event['status'], 'Synthetic SCRUM-45 manual fixture'))
            finally:
                connection.close()
        (self.state / 'fixtures.json').write_text(json.dumps(fixtures, indent=2))
        for service, database in (('event-service', 'events'), ('notification-service', 'notifications'),
                                  ('user-service', 'users'), ('venue-availability-service', 'availability'),
                                  ('coordinator-assignment-service', None)):
            port = free_port()
            self.urls[service] = f'http://127.0.0.1:{port}'
            self.service(service, ['-m', 'flask', '--app', 'app', 'run', '--host', '127.0.0.1', '--port', str(port)], database)
            wait(lambda: httpx.get(self.urls[service] + '/health', timeout=2).status_code == 200)
            if service in ('event-service', 'user-service'):
                self.env[service.upper().replace('-', '_') + '_URL'] = self.urls[service]
        self.service('notification-service', ['-m', 'app.consumer'], 'notifications', 'consumer')
        self.service('event-workflow-service', ['-m', 'app.dispatcher'], name='dispatcher')
        # Hold a bound, non-listening socket so omitted APIs cannot hit another local stack.
        self.reserved = socket.socket()
        self.reserved.bind(('127.0.0.1', 0))
        unavailable = f'http://127.0.0.1:{self.reserved.getsockname()[1]}'
        frontend_env = frontend_environment(self.env, self.urls, unavailable)
        (self.state / 'frontend-config.json').write_text(json.dumps(
            {key: value for key, value in frontend_env.items() if key.startswith('VITE_')}, indent=2))
        config = self.state / 'vite.config.mjs'
        config.write_text(vite_config({**self.urls, 'unavailable': unavailable}))
        self.run_process('vite', ['node', str(UI / 'node_modules/vite/bin/vite.js'), '--config', str(config),
            '--host', '127.0.0.1', '--port', self.urls['frontend'].rsplit(':', 1)[1], '--strictPort'], UI, frontend_env)
        wait(lambda: httpx.get(self.urls['frontend'], timeout=2).status_code == 200)
        self.status = 'ready'
        self.record()
        print('READY ' + self.urls['frontend'], flush=True)
        print('State and fixtures: ' + str(self.state), flush=True)
        print('Keep this terminal open; Ctrl-C removes only these owned processes/containers/volumes.', flush=True)

    def service(self, service, args, database=None, name=None):
        env = {**self.env, **({'DATABASE_URL': self.dsns[database]} if database else {})}
        return self.run_process(name or service, [str(ROOT / 'services' / service / '.venv/bin/python'), *args],
                                ROOT / 'services' / service, env)

    def __exit__(self, kind, error, traceback):
        self.failures = cleanup_owned_resources(self.processes, self.logs, self.names)
        if self.reserved is not None:
            self.reserved.close()
        if self.volumes:
            try:
                existing = command(['docker', 'volume', 'ls', '--format', '{{.Name}}']).splitlines()
                remaining = set(self.volumes).intersection(existing)
                if remaining:
                    self.failures.append(f'Owned volumes remain: {sorted(remaining)}')
            except Exception as failure:
                self.failures.append(f'Volume absence unverified: {failure}')
        self.status = 'cleanup-failed' if self.failures else 'stopped'
        self.record()
        print('CLEANUP ' + json.dumps(dict(status=self.status, failures=self.failures)), flush=True)
        if self.failures:
            message = '; '.join(self.failures)
            if error is not None:
                error.add_note(message)
            else:
                raise RuntimeError(message)
        return False



def isolated_environment(source=None):
    source = os.environ if source is None else source
    env = {key: source[key] for key in ('PATH', 'HOME', 'SSL_CERT_FILE', 'TMPDIR') if key in source}
    env.update(PYTHON_DOTENV_DISABLED='1', FLASK_SKIP_DOTENV='1', PYTHONUNBUFFERED='1',
               INTERNAL_SERVICE_TOKEN='scrum45-isolated-test-token', NOTIFICATION_DEV_MODE='true',
               CALENDAR_DEV_MODE='true')
    return env


def frontend_api_keys():
    return {key for path in (UI / 'src').rglob('*') if path.suffix in ('.ts', '.tsx')
            for key in re.findall(r'import\.meta\.env\.(VITE_[A-Z_]+_URL)', path.read_text())}


def frontend_environment(env, urls, unavailable):
    return {**env, **{key: urls.get(key.removeprefix('VITE_').removesuffix('_URL').lower().replace('_', '-'), unavailable)
                     for key in frontend_api_keys()}}


def vite_config(urls):
    """Remove remote presentation assets; CSP independently forbids external egress."""
    policy = ("default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
              "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
              "connect-src 'self' " + ' '.join(urls.values()) + ' ' +
              urls['frontend'].replace('http://', 'ws://') + "; form-action 'self'; base-uri 'self'; frame-src 'none'")
    return ('export default {envDir: false, server: {headers: ' +
            json.dumps({'Content-Security-Policy': policy}) +
            r'''}, plugins: [{name: 'isolated-no-remote-assets', transformIndexHtml(html) {
              return html.replace(/<link\b[^>]*href=["']https?:\/\/[^>]*>/g, '')
            }}]}''' + '\n')


def synthetic_fixtures():
    users = {key: dict(id=f'10000000-0000-0000-0000-{index:012d}', name=name, role=role)
             for index, key, name, role in (
                 (1, 'organiser', 'Synthetic Organiser', 'Event Organiser'),
                 (2, 'coordinatorOne', 'Synthetic Coordinator One', 'Event Coordinator'),
                 (3, 'coordinatorTwo', 'Synthetic Coordinator Two', 'Event Coordinator'),
                 (4, 'otherOrganiser', 'Synthetic Other Organiser', 'Event Organiser'),
                 (5, 'lead', 'Synthetic Lead', 'Event Coordinator Lead'))}
    events = {key: dict(id=f'20000000-0000-0000-0000-{index:012d}', name=name,
                        coordinatorId=users[coordinator]['id'] if coordinator else None, status=status)
              for index, key, name, coordinator, status in (
                  (1, 'rejection', 'Community Workshop', 'lead', 'Under Review'),
                  (2, 'approval', 'Approval Workshop', 'lead', 'Under Review'),
                  (3, 'assignment', 'Assignment Workshop', None, 'Submitted'),
                  (4, 'reassignment', 'Reassignment Workshop', 'coordinatorOne', 'Under Review'))}
    return dict(users=users, events=events)


def main():
    import argparse
    import shlex
    import signal
    import time
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, required=True,
                        help='New evidence directory; must not exist. Data resets every launch.')
    args = parser.parse_args()
    state = args.state_dir.resolve()
    restart = state.with_name(state.name + '-restart-' + uuid4().hex[:6])
    print('START COMMAND (fresh state): ' + shlex.join([
        'uv', 'run', '--no-project', '--with', 'pytest', '--with', 'httpx', '--with', 'psycopg2-binary',
        'python', str(Path(__file__).resolve()), '--state-dir', str(restart)]), flush=True)
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    try:
        with Sandbox(state) as sandbox:
            sandbox.setup()
            while True:
                failed = [process.pid for process in sandbox.processes if process.poll() is not None]
                if failed:
                    raise RuntimeError(f'Owned processes stopped unexpectedly: {failed}; see {state}')
                time.sleep(0.5)
    except KeyboardInterrupt:
        return 0 if sandbox.status == 'stopped' else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
