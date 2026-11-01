# Unit Test Convention

How every unit test file in the repo is laid out. Apply it when you write a new test file and when you review or revamp an old one.

Read [AGENTS.md](../../AGENTS.md) first: its *Testing expectations* section covers how to run the tests, the two test folders and CI. This file covers how a unit test file is written. Integration tests have their own guide, [integration-testing.md](integration-testing.md).

The convention is based on IS212 Week 6 (Automated Testing #1) and Week 9 (Automated Testing #2: Test Doubles). **All unit tests use pytest** (section 1). The slides use `unittest`, but the ideas carry over directly: stubs, mocks, fakes, FIRST and coverage work the same way. Test doubles still come from `unittest.mock`, as in the slides.

---

## Goal: 100% coverage that means something

**Target: 100% statement *and* branch coverage for every service.** Each service sets `fail_under = 100` in `[tool.coverage.report]` of its `pyproject.toml`, so `uv run pytest` fails below it, and CI's `unit-tests` job runs exactly that command. A PR that lowers coverage cannot merge.

```bash
cd services/<name>-service
uv run pytest
```

No flags are needed: every pytest and coverage setting lives in the service's `pyproject.toml` (AGENTS.md). The report lists any uncovered line in its `Missing` column.

Coverage only shows which lines *ran*. It doesn't show whether anything was *checked*. Week 6 warned that a suite can report 100% coverage while the requirement is still violated, for example when an agent writes both the code and its tests. So reaching 100% is necessary, but it isn't enough. These rules apply:

1. **Coverage must come from AC-mapped tests.** Never write a test only to hit lines. Every test has an `AC<n>:` line (section 4), or is a supporting design check (section 4.1), and every assertion checks an outcome that AC describes.
2. **Hit the crux of the story.** The crux is the *Then* of each AC and the *so that* of the story: the business rule a user would notice if it broke. For SCRUM-13 that's "only the assigned coordinator can move a Submitted event to Approved, and the approval is recorded". It isn't "the function returns an object". Every crux rule needs a test that **fails if that rule is broken**, so check it: comment out or invert the line that enforces the rule, run the tests, confirm at least one fails, then revert. This is mutation testing done by hand (Week 6).
3. **Every branch gets a deliberate test.** An `if` that guards an AC (status check, assignment check, capacity, deadline, buffer) needs a test for each side, and a boundary test where there's a threshold (just below, at, just above). Use `@pytest.mark.parametrize` for boundary values (section 4).
4. **Uncovered code that no AC explains means a finding, not a new test.** Either the code is dead (delete it), Jira is missing an AC (raise it with the PO, then add the AC and the test), or it is plumbing every story relies on (a supporting design check, section 4.1). `# pragma: no cover` is allowed only for code that can't run in a unit test (for example, an `if __name__ == "__main__":` block), and it needs a comment saying why.
5. **Doubled lines count as covered, but they aren't proven.** Anything behind a stub, mock or fake still goes under **Not proven** (section 3).

---

## 1. pytest setup

Every unit test runs on pytest and is written in pytest style. Each service already has this setup; a new service copies it.

- Dev dependencies, added with `uv add --dev` so `uv.lock` stays in step: `pytest`, `pytest-cov`, `pytest-mock` and `pytest-socket`.
- `pyproject.toml` holds `[tool.pytest.ini_options]` (including `--disable-socket`, so a unit test that forgets to fake an HTTP call fails instead of reaching a real service) and `[tool.coverage.*]` with `branch = true` and `fail_under`.
- `tests/`, `tests/unit/` and `tests/integration/` are packages (each has an `__init__.py`).
- Shared helpers (test data builders, fake responses, ids) go in `tests/unit/factories.py`, imported as `from tests.unit.factories import ...`. Shared fixtures go in `tests/unit/conftest.py` (or `tests/conftest.py` for ones integration tests share too). Larger hand-written fakes can go in `tests/unit/fakes.py`.
- **A test module never imports another test module.** If two files need the same helper, move it to `factories.py` or `conftest.py`.
- `pytest-socket` does not catch `psycopg2`, which connects from C. Always fake `psycopg2.connect` in unit tests.

### unittest to pytest

| unittest | pytest |
|---|---|
| `class TestX(unittest.TestCase):` | Plain `def test_...():` functions. A plain class with no base class, e.g. `class TestApprove:`, is allowed for grouping. |
| `setUp()` / `tearDown()` | `@pytest.fixture`, with `yield` for teardown. Request a fixture by naming it as a test argument. |
| `self.assertEqual(a, b)` | `assert a == b` |
| `self.assertTrue(x)` / `assertFalse(x)` | `assert x` / `assert not x` |
| `self.assertIn(a, b)` | `assert a in b` |
| `with self.assertRaises(E):` | `with pytest.raises(E):` (add `match="..."` to check the message) |
| `@patch("mod.name")` decorator or `with patch(...)` block | The `mocker` fixture: `mocker.patch("mod.name")`. `monkeypatch.setattr` is also fine for simple replacements. |
| One test per boundary value | `@pytest.mark.parametrize` with `ids=` |
| `Mock()`, `.return_value`, `assert_called_once_with` | Unchanged. Keep using `unittest.mock`, as in Week 9. |

---

## 2. File layout and naming

**One test file tests one user story, and its name starts with that story's Jira key:**

```
tests/unit/test_scrum<key>_<feature>.py
```

- ✓ `test_scrum149_safety_check_submission.py`, `test_scrum13_approve_event_request.py`
- ✗ `test_safety_submit.py` (no key), `test_clients.py` (named after a code module, and mixes stories)
- The `<feature>` part names the behaviour in words, not the `app/` module it lives in.
- A story may have **several** files when its tests grow large or fall into clear parts, e.g. `test_scrum149_safety_check_submission.py` and `test_scrum149_submission_readiness.py`. Each file gets the full header.
- A file **never mixes stories**. If a test belongs to another story, move it to that story's file, even when it exercises the same code (for example, a role check on the safety queue belongs to the SCRUM-9 file, not the SCRUM-162 file). Tests of a client or helper go in the file of the story that the client call serves.
- A file whose tests belong to no story is named for what it checks, e.g. `test_service_infrastructure.py` (health check, CORS, start-up). See section 4.1.

Every test file has two parts, in this order:

1. **A module docstring** at the top of the file containing:
   - the **exact user story**, copied word for word from Jira, with its key, title and all acceptance criteria
   - three summaries: **Real**, **Doubled** and **Not proven**
2. **Test cases.** Each test function's docstring starts with a one-line summary, then the AC it covers, then the test doubles it uses.

---

## 3. Module docstring

```python
"""
SCRUM-<key>: <Story title>

User Story
----------
As a <role>, I want <goal>, so that <benefit>.

Acceptance Criteria
-------------------
AC1: <copied exactly from Jira>
AC2: <copied exactly from Jira>
AC3: <copied exactly from Jira>

Real
----
- <What runs for real in these tests and what the assertions actually prove.>

Doubled
-------
- <Each dependency that was replaced, in plain words, with its type in brackets.>

Not proven
----------
- <What these tests cannot tell us, and where it is (or should be) tested instead.>
"""
```

### Rules for the user story block

- **Copy it exactly from Jira.** Don't paraphrase it, shorten it, or "fix" its wording. If Jira's wording is wrong, change it in Jira first, then copy it again.
- **Keep Jira's AC numbering.** If Jira writes the ACs as unnumbered bullets, number them `AC1`, `AC2`, … from top to bottom, and keep that order.
- **Include every AC,** even ones this service doesn't handle. Say under **Not proven** where those are tested.
- **When the Jira story changes,** update the header *and* every test docstring that quotes the changed AC, in the same PR. Re-read Jira before a review; stories change during the project (e.g. SCRUM-151 and SCRUM-164 gained equipment rules in Week 10).

### What goes in the three summaries

Write all three for a reader who knows the story but not the code (a teammate or the PO).

| Section | Answers | Example |
|---|---|---|
| **Real** | What behaviour actually runs, and which outcomes are checked? | "Approving a safety check: only a Safety Officer, only for an event pending its safety check; the decision recorded first and the event then moved to Confirmed. We check the result the officer sees and the order of the calls." |
| **Doubled** | What was replaced, in plain words, and with which kind of double? | "Event Service: holds the event, or fails [Stub]; we check what it was asked to do [Mock]." / "Safety records (database): hold the rounds each test needs [Stub]." |
| **Not proven** | What would still be unknown even if every test passed, and where is it proven? | "That the SQL works on the real tables (-> tests/integration/test_rounds.py)." / "The review page (-> frontend SafetyReview.test.tsx)." |

**Not proven is required and is never empty.** Week 9 points out that doubled tests can all pass while the boundary between components is broken (the "mock-based integration illusion" slide: dollars in one component, cents in the other). Anything a double stood in for is, by definition, not proven by this file. Say so, and point to the test that does prove it.

- **Only point to tests that exist.** Check the file or folder is there before you name it. If nothing proves it yet, write `NOT COVERED ANYWHERE`, so the gap is easy to find with grep. (A pointer to `tests/integration/` in a service that has no integration tests hides a real gap.)

---

## 4. Test case docstring

Each test function's docstring has three parts:

```python
def test_<unit>_<condition>_<expected_outcome>(<fixtures>):
    """
    Summary: <one short, high-level sentence on what this test proves>
    AC<n>: <the AC text, copied from Jira>
    Double: <the doubles, in plain words, each tagged [Stub], [Mock] or [Fake]; or None>
    """
```

Rules:

- **Summary comes first, in one line, in business terms.** Say what the test proves about the story, not how the test works. A teammate or the PO should understand it without reading the code. Avoid status codes, class names, `token`, `body`, `JSON` and similar.
  - ✓ `Summary: An unassigned coordinator cannot approve someone else's event.`
  - ✓ `Summary: If the event cannot be moved, the approval is undone.`
  - ✗ `Summary: Calls approve() with C2 and asserts PermissionError is raised.`
  - ✗ `Summary: A failed decision is a downstream error.`
  - ✗ `Summary: Tests approve.`
- **Each Summary must be distinct.** If two tests have the same summary, they're either duplicates (merge them) or the summaries are too vague (sharpen them).
- **The Summary, the name and the assertions must agree.** A test named `..._returns_403` must assert 403; a docstring that says "nothing is saved" needs an assertion that nothing was saved.
- **Every test maps to at least one AC of the file's story.** If a test fits no AC of this story, move it to the right story's file, or make it a supporting design check (4.1), or delete it if it is out of scope.
- **Quote the AC in full, from Jira.** Don't write placeholders such as `AC1: (rollback)` or `AC3: (boundary: notes at the limit)`; put that detail in the Summary instead. Only cite ACs of the file's own story, so don't prefix keys (`SCRUM-8 AC2:`) in a story file.
- **One test can cover several ACs.** List each on its own line.
- If a test uses more than one double, list them all.
- **Use `Double: None`** when the unit is pure logic with no dependencies, or the test touches nothing outside the service.

### Describing doubles

Write the `Double:` line (and the header's **Doubled** section) in business terms: say what the replaced thing *does* in this test, then tag it with the role it plays.

- ✓ `Double: Supabase rejects the credentials [Stub].`
- ✓ `Double: The event is confirmed and open [Stub]; Registration Service saves the registration, and we check what it was asked to save [Mock].`
- ✓ `Double: We check no other service is contacted [Mock].`
- ✗ `Double: Stub (cursor returns rows; SQL inspected)`
- ✗ `Double: Stub (respx; request inspected)` (when the test doesn't use respx)

**Tag by role, not by the class you used.** A `Mock()` counts as a **[Stub]** when you only set its answers and assert on the result, and as a **[Mock]** when you assert on its calls (Week 9, "Caution!" slide). Only write "we check …" / [Mock] when the test really asserts on those calls.

### 4.1 Supporting design checks

Some tests check plumbing that every story relies on but no AC describes: the health check, CORS, missing configuration, database outages, the internal service token, default service addresses. They are kept, but they are not labelled as an AC:

- Their docstring says `Supporting design check: <what it checks>` instead of an `AC<n>:` line.
- They sit at the **bottom** of the file, under this comment:

  ```python
  # --- Supporting/supplementary design checks ----------------------------------
  # No Jira acceptance criterion covers these. They check design decisions the
  # stories rely on (health check, CORS, configuration and failure handling).
  ```

- A file made only of these checks (usually `test_service_infrastructure.py`) has a header titled `SUPPORTING DESIGN CHECKS: <what it covers>` in place of the story, still with Real, Doubled and Not proven.

### Test function naming

Every test name says **what is being tested, under what condition, and what the expected outcome is**:

```
test_<unit>_<condition>_<expected_outcome>
```

| Part | What it is | Examples |
|---|---|---|
| `<unit>` | The method or behaviour under test | `approve`, `submit_for_safety_check`, `register` |
| `<condition>` | The situation, usually starting with `when_` or `with_` | `when_coordinator_not_assigned`, `when_event_is_full`, `with_missing_required_fields` |
| `<expected_outcome>` | What should happen, usually starting with `returns_`, `raises_`, `sets_`, `sends_`, `records_` or `blocks_` | `raises_permission_error`, `sets_status_approved`, `sends_no_notification` |

- ✓ `test_approve_when_coordinator_not_assigned_raises_permission_error`
- ✓ `test_register_when_event_at_capacity_returns_full_message`
- ✗ `test_approve_2`, `test_happy_path` (no condition or outcome)
- ✗ `test_approve_works` (doesn't say what "works" means)

The name and the `Summary:` line should describe the same thing: the name is precise, and the Summary is plain English. Long names are fine; clarity matters more than length.

For a parametrized test, the name describes the rule, and each case gets a readable `id`:

```python
@pytest.mark.parametrize(
    "attendance, expected",
    [(99, "suitable"), (100, "suitable"), (101, "over_capacity")],
    ids=["below_capacity", "at_capacity", "above_capacity"],
)
def test_capacity_check_when_attendance_near_capacity_returns_correct_result(attendance, expected):
    ...
```

Plain string or status values (e.g. `["Approved", "Rejected"]`) already make readable ids, so `ids=` can be left out for those.

### Test body: Arrange / Act / Assert (only when the AC uses Given / When / Then)

**Add AAA comments only when the AC the test covers is written in Given / When / Then form.** If it isn't (for example SCRUM-13 AC3, "The approving Event Coordinator's identity and timestamp are recorded"), skip the AAA comments entirely.

When you do use them, tag each block with its matching Given / When / Then:

```python
def test_apply_discount_when_user_is_vip_returns_20_percent_off():
    """
    Summary: VIP users get 20% off their cart total.
    AC1: Given a VIP user, when the discount is applied, then the total is reduced by 20%.
    Double: None
    """
    # Arrange (Given)
    user = User(is_vip=True)
    cart = Cart(user=user, total=100.0)

    # Act (When)
    final_price = cart.apply_discount()

    # Assert (Then)
    assert final_price == 80.0
```

| Comment | Contains |
|---|---|
| `# Arrange (Given)` | Test data, starting state, and **setting up doubles** (stub answers, fake contents, fixed clock) |
| `# Act (When)` | The call to the unit under test |
| `# Assert (Then)` | State assertions and mock call assertions (`assert_called_once_with`, `assert_not_called`) |

Rules:

- **The blocks can appear in any order, and can be combined or repeated** when the test reads better that way. For example, use `# Act + Assert (When / Then)` around a `pytest.raises`, followed by another `# Assert (Then)` that checks nothing changed.
- **Put a blank line between blocks.**
- **When a fixture does part of the Arrange,** still write the `# Arrange (Given)` block for the data that matters to this test. If fixtures do all of it, write `# Arrange (Given): <what>, from fixtures`.
- **One scenario per test.** Don't chain several scenarios in one test body; parametrize instead.

---

## 5. Choosing the double (from Week 9)

| Double | What it does | What you check | Use it when | How (pytest + `unittest.mock`) |
|---|---|---|---|---|
| **Stub** | Returns canned answers | **State**: the unit's return value or resulting data | You need a dependency to return a specific answer, such as "venue already booked", "equipment unavailable" or "DB error" | `mocker.patch("where.it.is.used", return_value=...)` or `side_effect=Exception(...)` |
| **Mock** | Records calls so you can verify them | **Behaviour**: an interaction happened, with the right arguments, the right number of times | The interaction *is* the requirement, such as "a notification is sent", "an audit entry is written" or "no notification is sent for a draft" | `m = mocker.patch("where.it.is.used")` then `m.assert_called_once_with(...)` or `m.assert_not_called()` |
| **Fake** | A working, simplified implementation | State, through the fake's real behaviour | You need the dependency to *behave* realistically across several calls, such as an in-memory repository that saves and reads back | A small hand-written class in `tests/unit/factories.py` or `fakes.py`, provided by a fixture |

Decision guide:

1. Does the AC say something must **happen** (notify, record, call)? → **Mock** that dependency and assert on the call.
2. Does the unit just need a dependency to **give back an answer**? → **Stub** it.
3. Do several steps need to **read back what earlier steps wrote**? → **Fake** it.
4. Is the unit pure logic with no dependencies? → **None**.

### Rules carried over from the slides

- **Never double the unit under test.** If you patch the function you're testing, the test only proves the patch works (Week 9, "What's wrong with this test?").
- **Patch where the name is looked up, not where it's defined.** If `events/service.py` does `from notifications import notify_organiser`, patch `events.service.notify_organiser` (Week 9, "Patch where the name is looked up").
- **Assert on observable outcomes,** meaning the return value, resulting state, and required interactions, not on a dependency's internal workings. Don't assert on a value the stub itself returned and the code just passed through; assert on what the code did with it (e.g. what it saved).
- **Start each test from fresh state.** Use function-scoped fixtures (pytest's default) so every test gets a new fake. Don't use `scope="module"` or `scope="session"` for anything a test can change. Build data with small helpers like `event(status="Submitted")`, show only the values that matter for the test, and default the rest (Week 9, "Test Data"; FIRST: Isolated, Repeatable).
- **Inject the clock and seed any randomness.** Expiry, deadline and buffer logic must not depend on the real current time (Week 9, "Fixing Flakiness").
- **Never use real personal data in fixtures.**

---

## 6. Full example

```python
# tests/unit/conftest.py
from datetime import datetime
from unittest.mock import Mock

import pytest

from events.service import EventService
from tests.unit.factories import InMemoryEventRepository

FIXED_NOW = datetime(2026, 10, 30, 9, 0)


@pytest.fixture
def repo():
    return InMemoryEventRepository()


@pytest.fixture
def clock():
    clock = Mock()
    clock.now.return_value = FIXED_NOW
    return clock


@pytest.fixture
def service(repo, clock):
    return EventService(repo, clock)
```

```python
# tests/unit/test_scrum13_approve_event.py
"""
SCRUM-13: Approve Submitted Event Request

User Story
----------
As an Event Coordinator, I want to approve a submitted event request assigned
to me, so that the Event Organiser knows their event can proceed to planning.

Acceptance Criteria
-------------------
AC1: Given an Event Request has status 'Submitted' and is assigned to the
     current Event Coordinator, when they approve it, then the status changes
     to 'Approved'.
AC2: Given an Event Request is not assigned to the current Event Coordinator,
     the approve action is not available to them.
AC3: The approving Event Coordinator's identity and timestamp are recorded for
     auditability.

Real
----
- Approving a request: only a submitted request assigned to the caller can be
  approved, and the approval is recorded with who approved it and when.
- We check the saved status, the refusal, and the audit entry.

Doubled
-------
- Event records: an in-memory store that saves and reads back [Fake].
- Clock: always says 30 Oct 2026, 09:00, so the timestamp is predictable
  [Stub].
- Organiser notification: we check one is sent for an approval, and none for
  a refusal [Mock].

Not proven
----------
- That the real database saves the status and audit row
  (-> tests/integration/test_event_approval.py).
- That the "Approve" button is hidden for unassigned coordinators (AC2, UI
  half) (-> E2E Journey 2A).
- That the Organiser actually receives the notification in-app
  (-> E2E Journey 1A, step 5).
"""
import pytest

from tests.unit.conftest import FIXED_NOW
from tests.unit.factories import make_event


@pytest.fixture
def notify(mocker):
    return mocker.patch("events.service.notify_organiser")


def test_approve_when_assigned_and_submitted_sets_status_approved(repo, service, notify):
    """
    Summary: The assigned coordinator can approve a submitted event, and the Organiser is notified.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they approve it, then the status changes
        to 'Approved'.
    Double: The event is saved in the in-memory store [Fake]; we check the
        Organiser is notified once [Mock].
    """
    # Arrange (Given)
    make_event(repo, id="E1", status="Submitted", coordinator_id="C1")

    # Act (When)
    service.approve("E1", coordinator_id="C1")

    # Assert (Then)
    assert repo.get("E1").status == "Approved"
    notify.assert_called_once_with("E1", decision="Approved")


def test_approve_when_coordinator_not_assigned_raises_permission_error(repo, service, notify):
    """
    Summary: A coordinator cannot approve an event that isn't assigned to them, and nothing changes.
    AC2: Given an Event Request is not assigned to the current Event
        Coordinator, the approve action is not available to them.
    Double: The event is saved in the in-memory store [Fake]; we check no
        notification is sent [Mock].
    """
    # Arrange (Given)
    make_event(repo, id="E1", status="Submitted", coordinator_id="C1")

    # Act + Assert (When / Then)
    with pytest.raises(PermissionError):
        service.approve("E1", coordinator_id="C2")

    # Assert (Then)
    assert repo.get("E1").status == "Submitted"
    notify.assert_not_called()


def test_approve_when_successful_records_coordinator_and_timestamp(repo, service):
    """
    Summary: Every approval leaves an audit record of who approved it and when.
    AC3: The approving Event Coordinator's identity and timestamp are recorded
        for auditability.
    Double: The event is saved in the in-memory store [Fake]; the clock says
        30 Oct 2026, 09:00 [Stub].
    """
    make_event(repo, id="E1", status="Submitted", coordinator_id="C1")

    service.approve("E1", coordinator_id="C1")

    entry = repo.audit_log("E1")[-1]
    assert entry.actor_id == "C1"
    assert entry.at == FIXED_NOW


@pytest.mark.parametrize("status", ["Draft", "Rejected", "Approved"])
def test_approve_when_status_not_submitted_raises_value_error(repo, service, status):
    """
    Summary: Only an event that is currently Submitted can be approved.
    AC1: Given an Event Request has status 'Submitted' and is assigned to the
        current Event Coordinator, when they approve it, then the status changes
        to 'Approved'.
    Double: The event is saved in the in-memory store [Fake].
    """
    # Arrange (Given)
    make_event(repo, id="E1", status=status, coordinator_id="C1")

    # Act + Assert (When / Then)
    with pytest.raises(ValueError):
        service.approve("E1", coordinator_id="C1")

    # Assert (Then)
    assert repo.get("E1").status == status
```

---

## 7. Checklist for writing or reviewing a test file

**File**

- [ ] The file is named `test_scrum<key>_<feature>.py` and tests that one story only. Tests for other stories have been moved to their own story's file.
- [ ] It is written in pytest style: plain `assert`, `pytest.raises`, fixtures instead of `setUp`, `mocker.patch` instead of `@patch` / `with patch`, and no `unittest.TestCase`.
- [ ] It doesn't import another test module. Shared helpers live in `factories.py` / `conftest.py`.

**Header**

- [ ] The module docstring has the Jira key, title, and the story and all ACs copied **exactly** from current Jira.
- [ ] **Real**, **Doubled** and **Not proven** are all filled in, in business terms. Not proven points only to tests that exist, or says `NOT COVERED ANYWHERE`.

**Each test**

- [ ] It has a `Summary:` line: one high-level sentence in business terms, different from every other test's summary, and matching what the test asserts.
- [ ] It has an `AC<n>:` line quoting the AC in full from Jira, or is a supporting design check at the bottom of the file.
- [ ] It has a `Double:` line in business terms, tagged [Stub], [Mock] or [Fake] by the role the double plays, or `None`.
- [ ] It is named `test_<unit>_<condition>_<expected_outcome>`, and the name matches its Summary and assertions. Parametrized cases have readable `ids`.
- [ ] It has AAA comments if, and only if, its AC is written in Given / When / Then form.
- [ ] It isn't redundant: no other test in the suite checks the same scenario with the same outcome.

**The suite**

- [ ] Every AC of the story has at least one test, or is listed under Not proven with where it is tested.
- [ ] Each AC has a happy-path test, at least one negative test, and boundary tests where it has a threshold (capacity, deadlines, buffers, expiry).
- [ ] The inputs and outputs match the story: each field the AC names is asserted, not just the status code.
- [ ] No test breaks the story's workflow (for example, a test that expects an action the story forbids).
- [ ] The unit under test is never patched, and patches target the module where the name is looked up. Mocks are used only where an interaction is the requirement.
- [ ] No test depends on another test's leftover data, the real clock, or a real network or database.
- [ ] `uv run pytest` passes with 100% statement and branch coverage, reached through AC-mapped tests and supporting design checks only.
- [ ] Every crux rule of the story has a test that fails when that rule is broken. Check by commenting out or inverting the enforcing line, then reverting.
- [ ] Any line still uncovered has been raised as dead code or a missing AC, not covered with a filler test. Any `# pragma: no cover` has a comment saying why.
