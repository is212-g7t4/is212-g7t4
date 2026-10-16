"""# Test scope and acceptance mapping — SCRUM-171 integration

- **Real browser → HTTP → owned PostgreSQL:** direct clause-by-clause mapping follows below; fixtures are synthetic and setup/teardown is automatic. AC5 rollback uses an injected database failure, not a lost-response inference.
- **Scope:** counts are verification checks, not unique acceptance cases; no shared database or real safety submission is exercised.

## Case/group traceability

The named test functions/cases below implement the groups above; their existing
names and assertions specify the scenario. No group is credited with all five ACs.

## Existing test contract and detailed cases

Opt-in real browser -> actual services -> owned PostgreSQL SCRUM-171 checks.
Run: uv run --no-project --with playwright==1.63.0 --with psycopg2-binary python THIS --output NEW_DIR
--manual starts the same isolated synthetic environment until Enter; never shared DBs.

Uses the canonical five SCRUM-171 criteria in verify_scrum171_postgres.py.
Existing check names/order retain the FE-L01--FE-L22 report crosswalk:
- FE-L01 browser_preview_read_only, FE-L03 browser_back_no_writes,
  FE-L04 changed_impact_no_save_until_second_click and FE-L20
  mobile_discard_no_write: AC4 preview/confirmation/no-save clauses.
- FE-L02 non_singapore_preview_time: AC4 preview-time subclause only,
  not AC3 rejected-request detail evidence.
- FE-L05 browser_save_persists_closure_and_all_eligible_rejections: AC1,
  including independently affected siblings; successful-save support for AC5.
- FE-L06 excluded_siblings_and_parent_unchanged: AC2.
- FE-L07 browser_history_survives_reload: SCRUM-170 history regression,
  not AC3 rejected-request detail evidence.
- FE-L08 browser_atomic_failure_rolls_back_and_retains_draft: AC5 rollback;
  draft retention is supplementary robustness.
- FE-L09--FE-L12 retry/lost-response checks (including
  lost_response_reconciled_from_real_history): uncertainty/reconciliation
  robustness, not AC3 or an assertion that transport failure means rollback.
- FE-L15 mobile_rejection_full_period_sgt: AC3 display, asserting the closure
  cause, full start/end SGT period and operational reason on request details.
- FE-L14 mobile_manual_and_automatic_rejections_have_no_mutation_controls,
  FE-L17 existing_add_request_creates_separate_pending_replacement and
  FE-L18 replacement_preserves_history_siblings_parent: separately approved
  immutability/replacement rule, not direct AC2 closure-time preservation.
- FE-L13 identity switching, FE-L16/FE-L19 layout, FE-L21 JavaScript errors
  and FE-L22 application-origin isolation: supporting checks, not full AC proof.
"""
import argparse
import hashlib
import json
import os
import subprocess
import time
import traceback
from pathlib import Path
from urllib.request import urlopen
from verify_scrum171_postgres import Harness, MIGRATION, ROOT, port, http

UI = ROOT / 'frontend/event-management-ui'


class BrowserHarness(Harness):
    def start_ui(self):
        self.uiport = port()
        self.origin = f'http://127.0.0.1:{self.uiport}'
        os.environ['FRONTEND_ORIGIN'] = self.origin
        self.services()
        self.ports['user'] = port()
        user = ROOT / 'services/user-service'
        env = {**os.environ, 'DATABASE_URL': self.dsn, 'PYTHON_DOTENV_DISABLED': '1', 'FLASK_SKIP_DOTENV': '1', 'FLASK_DEBUG': '0', 'FRONTEND_ORIGIN': self.origin}
        self.spawn([str(user / '.venv/bin/python'), '-m', 'flask', '--app', 'app', 'run', '--host', '127.0.0.1', '--port', str(self.ports['user']), '--no-reload'], user, env, 'user')
        self.wait(self.url('user', '/health'))
        # Every browser API target is explicit. Unused services point at a closed
        # loopback port; no .env value or protected developer service can be used.
        dead = port()
        prefixes = ['USER', 'EVENT', 'VENUE', 'VENUE_BOOKING', 'VENUE_AVAILABILITY', 'EQUIPMENT', 'COORDINATOR_ASSIGNMENT', 'REGISTRATION', 'ATTENDEE_REGISTRATION', 'EQUIPMENT_RESERVATION', 'SAFETY_CHECK']
        frontend_env = {**os.environ, **{f'VITE_{s}_SERVICE_URL': f'http://127.0.0.1:{dead}' for s in prefixes}}
        frontend_env.update({f'VITE_{s.upper().replace("-", "_")}_SERVICE_URL': self.url(s, '') for s in self.ports})
        frontend_env.pop('CLOSURE_CONFIRMATION_KEY', None)
        self.spawn(['npm', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', str(self.uiport)], UI, frontend_env, 'frontend')
        self.ports['frontend'] = self.uiport
        self.wait(self.origin)
        self.report['origin'] = self.origin
        self.report['frontendSources'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in UI.joinpath('src').rglob('*') if p.is_file()}
        self.report['harnessSha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    def spawn(self, command, cwd, env, name):
        log = (self.out / f'{name}.log').open('w')
        self.logs.append(log)
        # Own a process group so npm's Vite child is cleaned up too.
        proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.processes.append(proc)
        self.groups.append(proc)

    def wait(self, url):
        for _ in range(150):
            try:
                with urlopen(url, timeout=1) as r:
                    if r.status == 200:
                        return
            except OSError:
                pass
            time.sleep(.1)
        raise AssertionError('Readiness timeout: ' + url)

    def teardown(self):
        import signal
        for proc in getattr(self, 'groups', []):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        super().teardown()


def browser_cases(h):
    from playwright.sync_api import sync_playwright, expect
    before = h.snapshot()
    affected = [h.booking(status, 10, 12) for status in ['Pending', 'Pending Review', 'Approved']]
    excluded = [h.booking(status, 10, 12) for status in ['Cancelled', 'Expired', 'On Hold']]
    excluded += [h.booking('Approved', 8, 10), h.booking('Approved', 12, 14), h.booking('Approved', 10, 12, 'other'), h.legacy]
    baseline = h.snapshot()
    reason = 'Maintenance <script>plain text</script>\nSafety inspection'
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(timezone_id='America/Los_Angeles', viewport={'width': 1440, 'height': 1100})
        context.add_init_script(f"localStorage.setItem('activeUserId', {json.dumps(h.ids['staff'])})")
        page = context.new_page()
        requests, errors = [], []
        page.on('request', lambda r: requests.append({'method': r.method, 'url': r.url}))
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(h.origin + '/venues/' + h.ids['venue'])
        expect(page.get_by_text('No recorded closures.', exact=True)).to_be_visible()
        page.screenshot(path=str(h.out / 'desktop-collapsed.png'), full_page=True)

        def fill(start=10, end=12, text=reason):
            if page.get_by_label('Closure start (SGT)').count() == 0:
                page.get_by_role('button', name='Record temporary closure', exact=True).click()
            page.get_by_label('Closure start (SGT)').fill(h.stamp(start).strftime('%Y-%m-%dT%H:%M'))
            page.get_by_label('Closure end (SGT)').fill(h.stamp(end).strftime('%Y-%m-%dT%H:%M'))
            page.get_by_label('Reason', exact=True).fill(text)
            page.get_by_role('button', name='Preview affected requests', exact=True).click()
            expect(page.get_by_role('region', name='Confirm temporary closure', exact=True)).to_be_visible()

        def confirm():
            page.get_by_role('button', name='Confirm closure and reject requests', exact=True).click()

        fill()
        expect(page.get_by_text('3 booking requests will be rejected.', exact=True)).to_be_visible()
        expect(page.get_by_role('list', name='Affected booking requests').locator('li')).to_have_count(3)
        h.check('browser_preview_read_only', h.snapshot() == baseline)
        region = page.get_by_role('region', name='Confirm temporary closure', exact=True)
        expected_time = h.stamp(10).strftime('%H:%M') + ' SGT'
        h.check('non_singapore_preview_time', expected_time in region.inner_text(), text=region.inner_text())
        page.screenshot(path=str(h.out / 'desktop-preview.png'), full_page=True)
        region.screenshot(path=str(h.out / 'desktop-preview-card.png'))
        page.get_by_role('button', name='Back to edit', exact=True).click()
        h.check('browser_back_no_writes', h.snapshot() == baseline)
        page.get_by_role('button', name='Preview affected requests', exact=True).click()
        expect(region).to_be_visible()
        late = h.booking('Pending Review', 10, 12)
        affected.append(late)
        before_confirm = h.snapshot()
        confirm()
        expect(page.get_by_text('4 booking requests will be rejected.', exact=True)).to_be_visible()
        expect(page.get_by_role('alert')).to_contain_text('confirm again')
        h.check('changed_impact_no_save_until_second_click', h.snapshot() == before_confirm)
        page.screenshot(path=str(h.out / 'desktop-reconfirm.png'), full_page=True)
        confirm()
        expect(page.get_by_text('Closure recorded.', exact=True)).to_be_visible()
        expect(page.get_by_text('4 booking requests rejected.', exact=True)).to_be_visible()
        after = h.snapshot()
        changed = {r['booking_id']: r for r in after['VenueBooking']}
        old = {r['booking_id']: r for r in before_confirm['VenueBooking']}
        h.check('browser_save_persists_closure_and_all_eligible_rejections', len(after['VenueClosure']) == 1 and all(changed[i]['status'] == 'Rejected' and changed[i]['rejection_closure_reason'] == reason for i in affected), affected=affected, after=after)
        h.check('excluded_siblings_and_parent_unchanged', all(changed[i] == old[i] for i in excluded) and after['Event'] == before_confirm['Event'])
        page.reload()
        expect(page.get_by_text(reason, exact=True)).to_be_visible()
        h.check('browser_history_survives_reload', page.get_by_text(reason, exact=True).count() == 1)
        page.screenshot(path=str(h.out / 'desktop-history.png'), full_page=True)

        # Force failure during update (not a mocked response): the complete
        # PostgreSQL transaction must roll back and UI must retain the draft.
        fail_ids = [h.booking('Pending Review', 20, 22), h.booking('Approved', 20, 22)]
        h.sql("""CREATE FUNCTION scrum171_fail_update() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.booking_id = '%s'::uuid AND NEW.status = 'Rejected' THEN RAISE EXCEPTION 'synthetic rollback probe'; END IF; RETURN NEW; END $$; CREATE TRIGGER scrum171_fail BEFORE UPDATE ON public.\"VenueBooking\" FOR EACH ROW EXECUTE FUNCTION scrum171_fail_update();""" % fail_ids[1])
        rollback_before = h.snapshot()
        fill(20, 22, 'Rollback probe')
        confirm()
        expect(page.get_by_role('alert')).to_contain_text('may have been recorded')
        expect(page.get_by_label('Reason', exact=True)).to_have_value('Rollback probe')
        expect(page.get_by_role('button', name='Preview affected requests')).to_be_disabled()
        h.check('browser_atomic_failure_rolls_back_and_retains_draft', h.snapshot() == rollback_before)
        h.sql('DROP TRIGGER scrum171_fail ON public."VenueBooking"; DROP FUNCTION scrum171_fail_update()')
        page.get_by_role('button', name='Refresh closures', exact=True).click()
        page.get_by_role('button', name='I checked all recorded closures; start a new preview').click()
        page.get_by_role('button', name='Preview affected requests', exact=True).click()
        expect(page.get_by_text('2 booking requests will be rejected.', exact=True)).to_be_visible()
        confirm()
        expect(page.get_by_text('Closure recorded.', exact=True)).to_be_visible()
        h.check('browser_retry_after_reconciliation_persists', len(h.snapshot()['VenueClosure']) == 2)

        # Commit then deliberately lose the response. This is a transport fault
        # against the real service, never fake persistence or a fabricated body.
        def lose_response(route):
            if route.request.method == 'POST':
                actual = route.fetch()
                h.check('zero_impact_real_save_before_response_loss', actual.status == 201)
                route.abort()
            else:
                route.continue_()
        page.route(h.url('venue-booking', '/venue-closures'), lose_response)
        fill(40, 42, 'Zero-impact lost response')
        expect(page.get_by_text('0 booking requests will be rejected.', exact=True)).to_be_visible()
        confirm()
        expect(page.get_by_role('alert')).to_contain_text('may have been recorded')
        expect(page.get_by_role('button', name='Preview affected requests')).to_be_disabled()
        h.check('zero_impact_uncertain_no_blind_replay', len(h.snapshot()['VenueClosure']) == 3)
        page.unroute(h.url('venue-booking', '/venue-closures'), lose_response)
        page.get_by_role('button', name='Refresh closures', exact=True).click()
        expect(page.locator('.closure-list').get_by_text('Zero-impact lost response', exact=True)).to_be_visible()
        h.check('lost_response_reconciled_from_real_history', len(h.snapshot()['VenueClosure']) == 3)
        page.screenshot(path=str(h.out / 'desktop-uncertain-reconciled.png'), full_page=True)
        page.get_by_label('Select active user').select_option(h.ids['coordinator'])
        expect(page.get_by_role('region', name='Temporary venue closures')).to_have_count(0)
        h.check('identity_switch_removes_staff_controls', page.get_by_role('region', name='Temporary venue closures').count() == 0)
        context.close()

        # A second, mobile browser reads persisted rejection metadata and creates
        # a distinct replacement through the existing Add venue booking form.
        mobile = browser.new_context(timezone_id='America/Los_Angeles', viewport={'width': 390, 'height': 844})
        mobile.add_init_script(f"if (!localStorage.getItem('activeUserId')) localStorage.setItem('activeUserId', {json.dumps(h.ids['coordinator'])})")
        page = mobile.new_page()
        page.on('request', lambda r: requests.append({'method': r.method, 'url': r.url}))
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(h.origin + '/events/' + h.ids['event'])
        expect(page.get_by_role('heading', name='Venue bookings', exact=True)).to_be_visible()
        rejected = page.locator('.venue-booking-item').filter(has=page.get_by_text('Rejected', exact=True))
        expect(rejected).to_have_count(7)
        h.check('mobile_manual_and_automatic_rejections_have_no_mutation_controls', rejected.get_by_role('button').count() == 0)
        expect(page.locator('.closure-rejection').first).to_contain_text(reason)
        expected_period = ' – '.join(h.stamp(hour).strftime('%-d %b %Y, %H:%M') + ' SGT' for hour in [10, 12])
        detail = page.locator('.closure-rejection').first
        expect(detail).to_contain_text(expected_period)
        h.check('mobile_rejection_full_period_sgt', expected_period in detail.inner_text() and reason in detail.inner_text() and 'Rejected due to temporary venue closure' in detail.inner_text(), expectedPeriod=expected_period, text=detail.inner_text())
        page.screenshot(path=str(h.out / 'mobile-before-overflow-check.png'), full_page=True)
        overflow = page.evaluate("[...document.querySelectorAll('*')].filter(e => e.getBoundingClientRect().right > innerWidth + 1).map(e => ({tag:e.tagName,cls:e.className,width:e.getBoundingClientRect().width,text:e.textContent.slice(0,100)}))")
        h.check('mobile_no_horizontal_overflow', page.evaluate('document.documentElement.scrollWidth <= innerWidth'), overflowing=overflow)
        page.locator('.venue-booking-item').first.scroll_into_view_if_needed()
        page.screenshot(path=str(h.out / 'mobile-rejections.png'), full_page=True)
        page.locator('.venue-booking-item').filter(has=page.locator('.closure-rejection')).first.screenshot(path=str(h.out / 'mobile-rejection-card.png'))
        replacement_before = h.snapshot()
        page.locator('.venue-booking-form select').select_option(h.ids['other'])
        page.get_by_label('Booking start *', exact=True).fill(h.stamp(30).strftime('%Y-%m-%dT%H:%M'))
        page.get_by_label('Booking end *', exact=True).fill(h.stamp(32).strftime('%Y-%m-%dT%H:%M'))
        page.get_by_role('button', name='Submit venue booking', exact=True).click()
        expect(page.get_by_text('booking request submitted. Status: Pending Review.', exact=False)).to_be_visible()
        replacement_after = h.snapshot()
        original_ids = {r['booking_id'] for r in replacement_before['VenueBooking']}
        new_rows = [r for r in replacement_after['VenueBooking'] if r['booking_id'] not in original_ids]
        h.check('existing_add_request_creates_separate_pending_replacement', len(new_rows) == 1 and new_rows[0]['status'] == 'Pending Review' and new_rows[0]['event_id'] == h.ids['event'], newRows=new_rows)
        h.check('replacement_preserves_history_siblings_parent', [r for r in replacement_after['VenueBooking'] if r['booking_id'] in original_ids] == replacement_before['VenueBooking'] and replacement_after['Event'] == replacement_before['Event'])
        page.reload()
        expect(page.get_by_role('heading', name='Venue bookings', exact=True)).to_be_visible()
        expect(page.locator('.venue-booking-item')).to_have_count(len(replacement_after['VenueBooking']))
        page.screenshot(path=str(h.out / 'mobile-replacement.png'), full_page=True)
        # Same mobile viewport also exercises a new zero-impact confirmation.
        page.get_by_label('Select active user').select_option(h.ids['staff'])
        page.goto(h.origin + '/venues/' + h.ids['venue'])
        fill(60, 62, 'Mobile zero-impact preview')
        expect(page.get_by_text('0 booking requests will be rejected.', exact=True)).to_be_visible()
        h.check('mobile_preview_no_horizontal_overflow', page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        page.screenshot(path=str(h.out / 'mobile-preview.png'), full_page=True)
        page.get_by_role('region', name='Confirm temporary closure', exact=True).screenshot(path=str(h.out / 'mobile-preview-card.png'))
        page.get_by_role('button', name='Discard closure draft', exact=True).click()
        h.check('mobile_discard_no_write', h.snapshot() == replacement_after)
        h.check('no_browser_javascript_errors', not errors, errors=errors)
        allowed = {h.origin, *(h.url(s, '') for s in h.ports)}
        from urllib.parse import urlsplit
        origins = {f'{urlsplit(r["url"]).scheme}://{urlsplit(r["url"]).netloc}' for r in requests}
        font_origins = {'https://fonts.googleapis.com', 'https://fonts.gstatic.com'}
        h.check('all_application_requests_use_owned_origins', origins - font_origins <= allowed, origins=sorted(origins), externalStaticFontOrigins=sorted(origins & font_origins))
        h.report['browserRequests'] = requests
        h.report['baselineBeforeFixtures'] = before
        mobile.close()
        browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--manual', action='store_true')
    args = parser.parse_args()
    h = BrowserHarness(args.output)
    h.groups = []
    failed = False
    try:
        h.setup()
        # Whole-minute fixtures match native datetime-local input precision.
        h.base = h.base.replace(second=0)
        # Short readable identities avoid unrelated shared Topbar/header overflow
        # from the backend harness's UUID-length display names; UUID keys remain.
        for role in ['staff', 'coordinator', 'organiser']:
            h.sql('UPDATE public."User" SET username=%s WHERE user_id=%s', ('Demo ' + role, h.ids[role]))
        h.sql('UPDATE public."Event" SET event_name=%s WHERE event_id=%s', ('SCRUM171 Demo Event', h.ids['event']))
        h.sql(MIGRATION.read_text())
        h.start_ui()
        if args.manual:
            for status in ['Pending', 'Pending Review', 'Approved']:
                h.booking(status, 10, 12)
            instructions = {'url': h.origin + '/venues/' + h.ids['venue'], 'eventUrl': h.origin + '/events/' + h.ids['event'], 'staffId': h.ids['staff'], 'coordinatorId': h.ids['coordinator'], 'startSGT': h.stamp(10).strftime('%Y-%m-%dT%H:%M'), 'endSGT': h.stamp(12).strftime('%Y-%m-%dT%H:%M'), 'database': h.name, 'instructions': 'Choose the synthetic staff in Select active user; preview then confirm. Switch to synthetic coordinator and open eventUrl to read rejection details. Press Enter in this terminal to stop and remove only this environment.'}
            (h.out / 'manual-instructions.json').write_text(json.dumps(instructions, indent=2))
            print(json.dumps(instructions, indent=2), flush=True)
            h.check('manual_launcher_health', all(http(h.url(s, '/health'))[0] == 200 for s in ['user', 'event', 'venue', 'venue-booking', 'venue-availability']))
            input('Enter to tear down isolated demo: ')
        else:
            browser_cases(h)
    except BaseException:
        failed = True
        h.report['error'] = traceback.format_exc()
        print(h.report['error'])
    finally:
        h.teardown()
    assert h.report.get('containerAbsent') and all(h.report['portsClosed'].values()), 'Owned resources were not cleaned up'
    print(json.dumps({'output': str(h.out), 'checks': len(h.report['cases']), 'failed': failed, 'portsClosed': h.report['portsClosed'], 'containerAbsent': h.report['containerAbsent']}, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
