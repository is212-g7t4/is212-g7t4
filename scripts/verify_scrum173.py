#!/usr/bin/env python3
"""Portable SCRUM-173 verification. No application .env or shared deployment.

Default: hermetic regression suites, component coverage, FIRST order runs, build,
lint and isolated mocked browser. --integration adds owned Docker services.
Run from any directory. Without --evidence, allocate a unique platform temporary
directory (honoring TMPDIR); output is retained until external temp cleanup.
An explicit evidence destination must not already exist.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import time
import tempfile

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "frontend/event-management-ui"
SCRIPTS = ROOT / "scripts"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, help="new output directory; defaults to a unique platform temporary directory")
    parser.add_argument("--integration", action="store_true")
    parser.add_argument("--integration-only", action="store_true")
    args = parser.parse_args()
    if args.evidence is None:
        evidence = Path(tempfile.mkdtemp(prefix="scrum173-verification-")).resolve()
    else:
        evidence = args.evidence.resolve()
        evidence.mkdir(parents=True, exist_ok=False)
    print(f"Evidence: {evidence} (retained; copy elsewhere before platform temporary-file cleanup)", flush=True)
    records = []
    base_env = {**os.environ, "PYTHON_DOTENV_DISABLED": "1", "FLASK_SKIP_DOTENV": "1"}
    # Evidence plugin is independent of application imports and never opens sockets.
    base_env["PYTHONPATH"] = str(SCRIPTS) + os.pathsep + base_env.get("PYTHONPATH", "")

    def run(name, command, cwd=ROOT, env=None):
        started = time.time()
        with (evidence / (name + ".log")).open("w") as stream:
            result = subprocess.run(command, cwd=cwd, env={**base_env, **(env or {})},
                                    stdout=stream, stderr=subprocess.STDOUT)
        record = {"name": name, "command": shlex.join(map(str, command)), "cwd": str(cwd),
                  "startedAt": started, "seconds": time.time() - started,
                  "exitCode": result.returncode}
        records.append(record)
        (evidence / "commands.json").write_text(json.dumps(records, indent=2))
        print(json.dumps(record), flush=True)
        return result.returncode

    if not args.integration_only:
        # Match CI auto-discovery: include templates and every service, not a stale list.
        for project in sorted((ROOT / "services").glob("*/pyproject.toml")):
            service = project.parent
            run("backend-" + service.name,
                ["uv", "run", "--no-env-file", "pytest", "-p", "scrum173_pytest_evidence",
                 "--junitxml=" + str(evidence / (service.name + "-junit.xml")),
                 "--cov-report=json:" + str(evidence / (service.name + "-coverage.json"))], service,
                {"SCRUM173_PYTEST_EVIDENCE": str(evidence / (service.name + "-cases.jsonl"))})
        for service in ("event-service", "notification-service", "venue-availability-service", "venue-booking-service"):
            unit = ROOT / "services" / service / "tests/unit"
            modules = sorted(unit.glob("test_notification*.py")) if service != "notification-service" else sorted(unit.glob("test_*.py"))
            for order in ("reverse", "shuffle"):
                run(f"FIRST-{service}-{order}",
                    ["uv", "run", "--no-env-file", "pytest", "--no-cov", "-p", "scrum173_pytest_evidence",
                     *[str(module.relative_to(unit.parent.parent)) for module in modules]], unit.parent.parent,
                    {"SCRUM173_TEST_ORDER": order,
                     "SCRUM173_PYTEST_EVIDENCE": str(evidence / f"FIRST-{service}-{order}.jsonl")})
        run("frontend-full", ["npm", "run", "test:coverage", "--", "--reporter=default", "--reporter=json",
                              "--outputFile=" + str(evidence / "frontend-full.json")], UI)
        run("frontend-ticket-coverage", ["./node_modules/.bin/vitest", "run", "src/features/notifications", "--coverage",
              "--coverage.include=src/features/notifications/*.{ts,tsx}", "--coverage.reporter=json", "--coverage.reporter=text",
              "--coverage.reportsDirectory=" + str(evidence / "notification-ui-coverage")], UI)
        run("FIRST-frontend-shuffle", ["./node_modules/.bin/vitest", "run", "src/features/notifications",
             "--sequence.shuffle", "--sequence.seed=173", "--maxWorkers=1", "--reporter=default",
             "--reporter=" + str(SCRIPTS / "scrum173-vitest-reporter.mjs")], UI,
             {"SCRUM173_VITEST_EVIDENCE": str(evidence / "FIRST-frontend-order.jsonl")})
        run("frontend-build", ["npm", "run", "build"], UI)
        run("frontend-lint", ["npm", "run", "lint"], UI)
        # Preserve every pinned service mock; allocate a private Vite port, never reuse a server.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config = evidence / "playwright.isolated.mts"
        config.write_text("import original from " + json.dumps(str(UI / "e2e/playwright.config.ts")) + ";\nexport default { ...original, "
             + "testDir: " + json.dumps(str(UI / "e2e")) + ", outputDir: " + json.dumps(str(evidence / "browser-results"))
             + ", reporter: [['list'], ['json', {outputFile: " + json.dumps(str(evidence / "browser.json")) + "}]], "
             + "use: {...original.use, baseURL: 'http://localhost:" + str(port) + "', timezoneId: 'America/Los_Angeles'}, "
             + "webServer: {...original.webServer, cwd: " + json.dumps(str(UI))
             + ", command: 'npm run dev -- --port " + str(port) + "', url: 'http://localhost:" + str(port)
             + "', reuseExistingServer: false}};\n")
        run("mocked-browser-full", ["./node_modules/.bin/playwright", "test", "-c", str(config), "--workers=4"], UI)
    if args.integration or args.integration_only:
        ready = run("docker-ready", ["docker", "info", "--format", "{{.ServerVersion}}"])
        if not ready:
            run("real-integration-pytest", ["uv", "run", "--no-env-file", "--with", "psycopg2-binary", "python", "-m", "pytest",
                "tests/integration/test_scrum173_real.py", "-m", "integration", "--force-enable-socket", "--no-cov",
                "--basetemp=" + str(evidence / "pytest-owned-temp"),
                "-p", "scrum173_pytest_evidence", "--junitxml=" + str(evidence / "integration-junit.xml")],
                ROOT / "services/venue-booking-service",
                {"SCRUM173_INTEGRATION_EVIDENCE": str(evidence / "real-integration"),
                 "SCRUM173_PYTEST_EVIDENCE": str(evidence / "integration-cases.jsonl")})
    run("whitespace", ["git", "diff", "--check"])
    failed = [record["name"] for record in records if record["exitCode"]]
    print(json.dumps({"failed": failed, "evidence": str(evidence)}), flush=True)
    return bool(failed)


if __name__ == "__main__":
    sys.exit(main())
