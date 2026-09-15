"""Tests for the ClawHub publish scripts.

The ClawHub CLI is replaced by a small Python stand-in that replies with canned
JSON, and the ClawHub HTTP API by a local server, so no network access, Bun or
token is needed. Response shapes follow the ClawHub source pinned in
publish-clawhub.yml. Run with: python -m pytest .github/scripts -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
PUBLISH = SCRIPTS / "clawhub_publish.py"
RELEASE_VERSION = SCRIPTS / "clawhub_release_version.py"
OWNER = "drdaviddelorenzo"

FAKE_CLI = '''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\\n")
if os.environ.get("FAKE_FAIL"):
    sys.stderr.write("boom: registry unreachable\\n")
    sys.exit(1)
if "--dry-run" in args and "--version" in args:
    print(os.environ["FAKE_PLAN"])
elif "--dry-run" in args:
    print(os.environ["FAKE_PROBE"])
else:
    print(os.environ["FAKE_RESULT"])
'''


def cli_json(**fields) -> str:
    return json.dumps({"ok": True, "slug": "dnasp", "fileCount": 30, **fields})


def verdict(status="pending", raw=None, reasons=("security.pending",), decision="fail",
            publisher=OWNER, version="0.5.1") -> str:
    """A security-verdicts response: the server normalises failed to status "error" and keeps
    the original value in rawStatus and verdict."""
    item = {"ok": decision == "pass", "decision": decision, "reasons": list(reasons),
            "slug": "dnasp", "version": version, "publisherHandle": publisher,
            "security": {"status": status, "rawStatus": raw, "verdict": raw}}
    return json.dumps({"schema": "clawhub.skill.security-verdicts.v1", "items": [item]})


MALICIOUS = verdict(status="malicious", raw="malicious", reasons=("moderation.malware_blocked",))
SCAN_FAILED = verdict(status="error", raw="failed", reasons=("security.not_passed",))
SUSPICIOUS = verdict(status="suspicious", raw="suspicious", reasons=("security.suspicious",))
PENDING = verdict()
NOT_FOUND = (404, "Version not found")
LISTED = (200, json.dumps({"version": {"version": "0.5.1"}}))
FILE_OK = (200, "---\nname: dnasp\n---\n")
FILE_BLOCKED = (403, "Blocked: this skill version has been flagged as malicious by ClawScan and cannot be downloaded.")
NEW_SKILL = cli_json(status="would-publish", version="1.0.0", latestVersion=None)
VERSION_PATH = f"/api/v1/skills/dnasp/versions/0.5.1?ownerHandle={OWNER}"
FILE_PATH = f"/api/v1/skills/dnasp/file?path=SKILL.md&version=0.5.1&ownerHandle={OWNER}"


class FakeClawHub:
    """Serves the version and file endpoints from queues of responses (the last one repeats)."""

    def __init__(self) -> None:
        self.versions = [NOT_FOUND]
        self.files = [FILE_OK]
        self.verdict = (200, PENDING)
        self.version_paths: list[str] = []
        self.file_paths: list[str] = []
        self.post_bodies: list[dict] = []
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if "/file?" in self.path:
                    hub.file_paths.append(self.path)
                    queue, count = hub.files, len(hub.file_paths)
                else:
                    hub.version_paths.append(self.path)
                    queue, count = hub.versions, len(hub.version_paths)
                self._send(*queue[min(count - 1, len(queue) - 1)])

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                hub.post_bodies.append(json.loads(self.rfile.read(length) or b"{}"))
                self._send(*hub.verdict)

            def _send(self, status, body):
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def hub():
    server = FakeClawHub()
    yield server
    server.server.shutdown()


def base_env() -> dict:
    return {"PATH": "", "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}


def run_publish(tmp_path, hub, **env_overrides):
    (tmp_path / "fake_cli.py").write_text(FAKE_CLI, encoding="utf-8")
    log = tmp_path / "calls.jsonl"
    log.write_text("", encoding="utf-8")
    env = {
        **base_env(),
        "BUN": sys.executable, "CLI_ENTRY": "fake_cli.py", "GITHUB_WORKSPACE": str(tmp_path),
        "OWNER": OWNER, "SKILL_PATH": "skills/dnasp", "VERSION": "0.5.1",
        "REGISTRY": hub.url, "SITE": hub.url, "POLL_SECONDS": "0.3", "POLL_INTERVAL": "0.05",
        "GITHUB_REPOSITORY": "drdaviddelorenzo/dnasp", "GITHUB_SHA": "abc123",
        "GITHUB_REF": "refs/heads/main", "GITHUB_OUTPUT": str(tmp_path / "output.txt"),
        "FAKE_LOG": str(log), "DRY_RUN": "false",
    }
    env.update(env_overrides)
    completed = subprocess.run([sys.executable, str(PUBLISH)], env=env, capture_output=True, text=True)
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return completed.returncode, completed.stdout + completed.stderr, calls


UNCHANGED = cli_json(status="unchanged", version="0.5.1", latestVersion=None)


def pending_submission(attempt="att-1"):
    return cli_json(status="pending-publication", version="0.5.1", attemptId=attempt)


# ----------------------------------------------------------------------------- dry run and version rules


def test_new_skill_dry_run_shows_the_recorded_version(tmp_path, hub):
    code, out, calls = run_publish(tmp_path, hub, DRY_RUN="true", FAKE_PROBE=NEW_SKILL,
                                   FAKE_PLAN=cli_json(status="would-publish", version="0.5.1", latestVersion=None))
    assert code == 0, out
    assert "would publish dnasp@0.5.1" in out
    assert len(calls) == 2
    assert "--dry-run" in calls[0] and "--version" not in calls[0]


def test_dry_run_fails_if_the_cli_plans_another_version(tmp_path, hub):
    code, out, _ = run_publish(tmp_path, hub, DRY_RUN="true", FAKE_PROBE=NEW_SKILL,
                               FAKE_PLAN=cli_json(status="would-publish", version="1.0.0", latestVersion=None))
    assert code == 1
    assert "planned version 1.0.0" in out


def test_same_content_stored_under_another_version_fails(tmp_path, hub):
    code, out, _ = run_publish(tmp_path, hub,
                               FAKE_PROBE=cli_json(status="unchanged", version="0.5.0", latestVersion="0.5.0"))
    assert code == 1
    assert "already stored on ClawHub as dnasp@0.5.0" in out


@pytest.mark.parametrize("latest", ["0.5.1", "1.0.0"])
def test_version_not_greater_than_latest_is_refused(tmp_path, hub, latest):
    code, out, calls = run_publish(tmp_path, hub,
                                   FAKE_PROBE=cli_json(status="would-publish", version="x", latestVersion=latest))
    assert code == 1
    assert "not greater" in out
    assert len(calls) == 1


def test_pre_release_latest_version_is_refused(tmp_path, hub):
    code, out, _ = run_publish(tmp_path, hub,
                               FAKE_PROBE=cli_json(status="would-publish", version="x", latestVersion="1.0.0-beta"))
    assert code == 1
    assert "not a plain" in out


def test_non_release_version_is_refused_before_calling_clawhub(tmp_path, hub):
    code, out, calls = run_publish(tmp_path, hub, VERSION="0.5.1-rc1", FAKE_PROBE=NEW_SKILL)
    assert code == 1
    assert "not a plain" in out
    assert calls == []


def test_cli_failure_fails_the_run(tmp_path, hub):
    code, out, _ = run_publish(tmp_path, hub, FAKE_FAIL="1")
    assert code == 1
    assert "registry unreachable" in out


def test_registry_publishing_another_version_fails(tmp_path, hub):
    code, out, _ = run_publish(tmp_path, hub, FAKE_PROBE=NEW_SKILL,
                               FAKE_RESULT=cli_json(status="published", version="1.0.0"))
    assert code == 1
    assert "Unexpected publish result" in out


# ----------------------------------------------------------------------------- publishing


def test_real_publish_passes_version_and_source_and_checks_both_endpoints(tmp_path, hub):
    hub.versions = [LISTED]
    code, out, calls = run_publish(tmp_path, hub, FAKE_PROBE=NEW_SKILL,
                                   FAKE_RESULT=cli_json(status="published", version="0.5.1", versionId="v1"))
    assert code == 0, out
    assert "serves it for download" in out
    publish = calls[-1]
    assert "--dry-run" not in publish
    for flag, value in [("--version", "0.5.1"), ("--tags", "latest"), ("--owner", OWNER),
                        ("--source-repo", "drdaviddelorenzo/dnasp"), ("--source-commit", "abc123"),
                        ("--source-path", "skills/dnasp"), ("--source-ref", "refs/heads/main")]:
        assert publish[publish.index(flag) + 1] == value
    assert hub.version_paths[0] == VERSION_PATH
    assert hub.file_paths[0] == FILE_PATH


def test_version_greater_than_latest_is_published(tmp_path, hub):
    hub.versions = [LISTED]
    code, out, calls = run_publish(tmp_path, hub,
                                   FAKE_PROBE=cli_json(status="would-publish", version="0.5.1", latestVersion="0.5.0"),
                                   FAKE_RESULT=cli_json(status="published", version="0.5.1"))
    assert code == 0, out
    assert len(calls) == 2


def test_pending_submission_that_becomes_available_succeeds(tmp_path, hub):
    hub.versions = [NOT_FOUND, NOT_FOUND, LISTED]
    code, out, _ = run_publish(tmp_path, hub, POLL_SECONDS="5", FAKE_PROBE=NEW_SKILL,
                               FAKE_RESULT=pending_submission("att-7"))
    assert code == 0, out
    assert "attempt att-7" in out
    assert "attempt_id=att-7" in (tmp_path / "output.txt").read_text(encoding="utf-8")


def test_pending_submission_still_under_checks_at_deadline_fails(tmp_path, hub):
    code, out, _ = run_publish(tmp_path, hub, FAKE_PROBE=NEW_SKILL, FAKE_RESULT=pending_submission("att-7"))
    assert code == 1
    assert "is not available after" in out
    assert "att-7" in out and "security.pending" in out
    assert "Published" not in out


def test_unpublished_submission_whose_download_is_blocked_fails_immediately(tmp_path, hub):
    hub.files = [FILE_BLOCKED]
    hub.verdict = (200, MALICIOUS)
    code, out, _ = run_publish(tmp_path, hub, POLL_SECONDS="30", FAKE_PROBE=NEW_SKILL,
                               FAKE_RESULT=pending_submission("att-9"))
    assert code == 1
    assert "ClawHub blocks it" in out and "att-9" in out
    assert "fix the skill" in out
    assert len(hub.file_paths) == 1


def test_listed_submission_whose_download_is_blocked_fails_immediately(tmp_path, hub):
    hub.versions = [LISTED]
    hub.files = [FILE_BLOCKED]
    code, out, _ = run_publish(tmp_path, hub, POLL_SECONDS="30", FAKE_PROBE=NEW_SKILL,
                               FAKE_RESULT=cli_json(status="published", version="0.5.1", attemptId="att-3"))
    assert code == 1
    assert "ClawHub blocks it" in out and "files not served (HTTP 403" in out
    assert len(hub.file_paths) == 1


def test_failed_scan_real_response_shape_is_blocked_with_rescan_advice(tmp_path, hub):
    """The verdict endpoint reports a failed scan as status "error" with rawStatus/verdict "failed"."""
    hub.files = [FILE_BLOCKED]
    hub.verdict = (200, SCAN_FAILED)
    code, out, _ = run_publish(tmp_path, hub, POLL_SECONDS="30", FAKE_PROBE=NEW_SKILL,
                               FAKE_RESULT=pending_submission("att-5"))
    assert code == 1
    assert "ClawHub blocks it" in out
    assert "scan failed rather than finding a problem" in out
    assert "scan failed" in out and "fix the skill" not in out


def test_another_publishers_malicious_verdict_does_not_stop_polling(tmp_path, hub):
    """The unscoped verdict endpoint may describe another publisher's skill: never treat it as ours."""
    hub.verdict = (200, verdict(status="malicious", raw="malicious", reasons=("moderation.malware_blocked",),
                                publisher="someone-else"))
    hub.versions = [NOT_FOUND, NOT_FOUND, NOT_FOUND, LISTED]
    code, out, _ = run_publish(tmp_path, hub, POLL_SECONDS="5", FAKE_PROBE=NEW_SKILL,
                               FAKE_RESULT=pending_submission("att-2"))
    assert code == 0, out
    assert "blocks it" not in out
    assert "not available for this publisher's release" in out
    assert len(hub.version_paths) == 4


def test_another_publishers_verdict_at_deadline_is_not_reported_as_blocked(tmp_path, hub):
    hub.verdict = (200, verdict(status="malicious", raw="malicious", publisher="someone-else"))
    code, out, _ = run_publish(tmp_path, hub, FAKE_PROBE=NEW_SKILL, FAKE_RESULT=pending_submission())
    assert code == 1
    assert "is not available after" in out
    assert "blocks it" not in out


def test_verdict_for_another_version_is_ignored(tmp_path, hub):
    hub.verdict = (200, verdict(status="malicious", raw="malicious", version="0.4.0"))
    code, out, _ = run_publish(tmp_path, hub, FAKE_PROBE=NEW_SKILL, FAKE_RESULT=pending_submission())
    assert code == 1
    assert "not available for this publisher's release" in out
    assert "blocks it" not in out


# ----------------------------------------------------------------------------- identical-content reruns


def test_pending_then_blocked_then_identical_rerun_reports_blocked(tmp_path, hub):
    """First run leaves a pending submission, the scan blocks it, the rerun must not succeed."""
    first_code, _, _ = run_publish(tmp_path, hub, FAKE_PROBE=NEW_SKILL, FAKE_RESULT=pending_submission())
    assert first_code == 1
    hub.files = [FILE_BLOCKED]
    hub.verdict = (200, MALICIOUS)
    code, out, calls = run_publish(tmp_path, hub, FAKE_PROBE=UNCHANGED)
    assert code == 1
    assert "ClawHub blocks it" in out
    assert "Nothing was uploaded" in out
    assert len(calls) == 1 and "--dry-run" in calls[0]


def test_identical_rerun_listed_but_failed_rescan_blocks_download(tmp_path, hub):
    """Metadata still returns 200 after a failed rescan, but files get 403: must not report success."""
    hub.versions = [LISTED]
    hub.files = [FILE_BLOCKED]
    hub.verdict = (200, SCAN_FAILED)
    code, out, calls = run_publish(tmp_path, hub,
                                   FAKE_PROBE=cli_json(status="unchanged", version="0.5.1", latestVersion="0.5.1"))
    assert code == 1
    assert "ClawHub blocks it" in out and "files not served (HTTP 403" in out
    assert "Nothing to do" not in out
    assert len(calls) == 1


def test_identical_rerun_download_403_is_blocked_even_if_verdict_endpoint_is_down(tmp_path, hub):
    hub.versions = [LISTED]
    hub.files = [FILE_BLOCKED]
    hub.verdict = (500, "internal error")
    code, out, _ = run_publish(tmp_path, hub,
                               FAKE_PROBE=cli_json(status="unchanged", version="0.5.1", latestVersion="0.5.1"))
    assert code == 1
    assert "ClawHub blocks it" in out
    assert "security verdict unavailable (HTTP 500)" in out


def test_identical_rerun_of_a_downloadable_suspicious_release_succeeds(tmp_path, hub):
    hub.versions = [LISTED]
    hub.verdict = (200, SUSPICIOUS)
    code, out, calls = run_publish(tmp_path, hub,
                                   FAKE_PROBE=cli_json(status="unchanged", version="0.5.1", latestVersion="0.5.1"))
    assert code == 0, out
    assert "already published and downloadable" in out
    assert len(calls) == 1


def test_identical_rerun_while_still_pending_fails_without_uploading(tmp_path, hub):
    code, out, calls = run_publish(tmp_path, hub, FAKE_PROBE=UNCHANGED)
    assert code == 1
    assert "is not available yet" in out
    assert len(calls) == 1


def test_identical_rerun_with_another_publishers_malicious_verdict_is_not_blocked(tmp_path, hub):
    hub.verdict = (200, verdict(status="malicious", raw="malicious", publisher="someone-else"))
    code, out, _ = run_publish(tmp_path, hub, FAKE_PROBE=UNCHANGED)
    assert code == 1
    assert "is not available yet" in out
    assert "blocks it" not in out


# ----------------------------------------------------------------------------- release version


def make_skill(root: Path, top="0.5.1", meta="0.5.1", module="0.5.1", entry="0.5.1", date="2026-09-15") -> Path:
    skill = root / "skills" / "dnasp"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: dnasp\ndescription: test\nversion: {top}\nlicense: MIT\nmetadata:\n  version: {meta}\n---\n# DnaSP\n",
        encoding="utf-8")
    (skill / "dnasp.py").write_text(f'__version__ = "{module}"\n', encoding="utf-8")
    (skill / "CHANGELOG.md").write_text(f"# Changelog\n\n## [{entry}] - {date}\n\n- change\n", encoding="utf-8")
    return skill


def run_release_version(root: Path, dry_run: str):
    env = {**base_env(), "SKILL_PATH": str(root / "skills" / "dnasp"), "DRY_RUN": dry_run,
           "GITHUB_OUTPUT": str(root / "output.txt")}
    completed = subprocess.run([sys.executable, str(RELEASE_VERSION)], env=env, capture_output=True, text=True)
    return completed.returncode, completed.stdout + completed.stderr


def test_release_version_agreeing_and_dated(tmp_path):
    make_skill(tmp_path)
    code, out = run_release_version(tmp_path, "false")
    assert code == 0, out
    assert "version=0.5.1" in (tmp_path / "output.txt").read_text(encoding="utf-8")


def test_release_version_undated_warns_on_dry_run_and_refuses_real_publish(tmp_path):
    make_skill(tmp_path, date="unreleased")
    code, out = run_release_version(tmp_path, "true")
    assert code == 0 and "::warning::" in out
    code, out = run_release_version(tmp_path, "false")
    assert code == 1 and "Date the entry" in out


@pytest.mark.parametrize("field", ["top", "meta", "module", "entry"])
def test_release_version_disagreement_is_refused(tmp_path, field):
    make_skill(tmp_path, **{field: "0.5.2"})
    code, out = run_release_version(tmp_path, "true")
    assert code == 1
    assert "disagree" in out


def test_release_version_pre_release_is_refused(tmp_path):
    make_skill(tmp_path, top="0.5.1-rc1", meta="0.5.1-rc1", module="0.5.1-rc1", entry="0.5.1-rc1")
    code, out = run_release_version(tmp_path, "true")
    assert code == 1
    assert "not a plain" in out
