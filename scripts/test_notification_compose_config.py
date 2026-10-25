"""SCRUM-173 local Compose configuration regression tests (no Docker daemon needed).

Uses only synthetic env files in temporary directories, never real credentials.
Covers root-only notification setup, token consistency, selective secret exposure,
existing service database preservation, optional dedicated notification database,
and actionable rejection of missing internal tokens. Runs `docker compose config`
only: no containers, broker messages or database writes are performed.
Run: python3 -m unittest discover -s scripts -p test_notification_compose_config.py -v
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'synthetic-compose-test-value'
DATABASE = 'postgresql://fixture@db.invalid/shared'
TOKEN_SERVICES = ('event-service', 'venue-availability-service', 'equipment-request-service',
                  'venue-booking-service', 'venue-notification-dispatcher',
                  'safety-check-service', 'event-workflow-service')

class NotificationComposeConfiguration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='notification-compose-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        text = (ROOT / 'docker-compose.yml').read_text()
        (self.root / 'docker-compose.yml').write_text(text)
        for rel in set(re.findall(r'\./services/[a-z0-9-]+/\.env', text)):
            if rel == './services/notification-service/.env':
                continue
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('DATABASE_URL=postgresql://fixture@db.invalid/service-specific\n'
                         'INTERNAL_SERVICE_TOKEN=stale-service-token\n')
        self.settings = {'DATABASE_URL': DATABASE, 'INTERNAL_SERVICE_TOKEN': TOKEN,
                         'MONGODB_URL': 'mongodb://unrelated.invalid',
                         'SUPABASE_ANON_KEY': 'unrelated-synthetic-setting'}

    def render(self, success=True):
        (self.root / '.env').write_text(''.join(f'{k}={v}\n' for k,v in self.settings.items()))
        env = {k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','DOCKER_CONFIG')}
        p = subprocess.run(['docker','compose','--project-name','notification-config-test',
                            'config','--format','json'], cwd=self.root, env=env,
                           capture_output=True, text=True, timeout=30)
        if success:
            self.assertEqual(p.returncode, 0, p.stderr)
            return json.loads(p.stdout)['services']
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('INTERNAL_SERVICE_TOKEN', p.stderr)
        return {}

    def test_coordinator_upstreams_do_not_use_container_localhost_defaults(self):
        """Docker service URLs override stale env_file values without changing the database."""
        p = self.root / 'services/coordinator-assignment-service/.env'
        p.write_text(p.read_text() + 'EVENT_SERVICE_URL=http://localhost:5003\n'
                     'USER_SERVICE_URL=http://localhost:5001\n')
        env = self.render()['coordinator-assignment-service']['environment']
        self.assertEqual(env['EVENT_SERVICE_URL'], 'http://event-service:5000')
        self.assertEqual(env['USER_SERVICE_URL'], 'http://user-service:5000')
        self.assertEqual(env['DATABASE_URL'], 'postgresql://fixture@db.invalid/service-specific')

    def test_root_configuration_needs_no_notification_env(self):
        services = self.render()
        for name in ('notification-service','notification-consumer'):
            self.assertEqual(services[name]['environment']['DATABASE_URL'], DATABASE)
        self.assertFalse((self.root/'services/notification-service/.env').exists())

    def test_root_token_overrides_stale_service_copies(self):
        services = self.render()
        for name in TOKEN_SERVICES:
            self.assertEqual(services[name]['environment']['INTERNAL_SERVICE_TOKEN'], TOKEN)

    def test_existing_service_databases_are_preserved(self):
        services = self.render()
        for name in ('event-service','venue-availability-service','venue-booking-service','equipment-request-service'):
            self.assertEqual(services[name]['environment']['DATABASE_URL'],
                             'postgresql://fixture@db.invalid/service-specific')

    def test_workers_receive_only_relevant_settings(self):
        services = self.render()
        for name in ('notification-service','notification-consumer','venue-notification-dispatcher'):
            env = services[name]['environment']
            self.assertNotIn('MONGODB_URL', env)
            self.assertNotIn('SUPABASE_ANON_KEY', env)
        self.assertNotIn('DATABASE_URL', services['venue-notification-dispatcher']['environment'])
        self.assertNotIn('INTERNAL_SERVICE_TOKEN', services['notification-service']['environment'])
        self.assertNotIn('INTERNAL_SERVICE_TOKEN', services['notification-consumer']['environment'])

    def test_optional_notification_database_override(self):
        self.settings['NOTIFICATION_DATABASE_URL'] = 'postgresql://fixture@db.invalid/notification'
        services = self.render()
        for name in ('notification-service','notification-consumer'):
            self.assertEqual(services[name]['environment']['DATABASE_URL'], self.settings['NOTIFICATION_DATABASE_URL'])

    def test_missing_or_empty_token_is_rejected(self):
        for value in (None, ''):
            with self.subTest(value=value):
                if value is None:
                    self.settings.pop('INTERNAL_SERVICE_TOKEN',None)
                else:
                    self.settings['INTERNAL_SERVICE_TOKEN']=value
                self.render(success=False)

    def test_dev_flags_default_off_and_can_be_enabled(self):
        services = self.render()
        self.assertEqual(services['notification-service']['environment']['NOTIFICATION_DEV_MODE'],'false')
        self.settings['NOTIFICATION_DEV_MODE']='true'
        services = self.render()
        self.assertEqual(services['notification-service']['environment']['NOTIFICATION_DEV_MODE'],'true')

    def test_broker_and_clients_share_root_credentials(self):
        self.settings.update(RABBITMQ_USER='fixture',RABBITMQ_PASSWORD='synthetic-local-value')
        services=self.render()
        self.assertEqual(services['rabbitmq']['environment']['RABBITMQ_DEFAULT_USER'],'fixture')
        self.assertEqual(services['rabbitmq']['environment']['RABBITMQ_DEFAULT_PASS'],'synthetic-local-value')
        for name in ('notification-consumer','venue-notification-dispatcher'):
            self.assertEqual(services[name]['environment']['RABBITMQ_URL'],
                             'amqp://fixture:synthetic-local-value@rabbitmq:5672/%2F')

if __name__ == '__main__':
    unittest.main()
