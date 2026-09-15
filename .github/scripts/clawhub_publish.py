"""Publish the skill to ClawHub at exactly the recorded version, safely re-runnable.

`clawhub skill publish` without --version compares the bundle fingerprint with
ClawHub and reports "unchanged" when that content is already stored, but then
picks the version itself (1.0.0 for a new skill, otherwise the next patch). With
--version it skips that comparison and always uploads. ClawHub also stores a
fingerprint as soon as a version is submitted, before its security checks
finish, and keeps it when a release is blocked, so "unchanged" does not mean
"available". This script therefore:

  1. asks ClawHub, without uploading (--dry-run, no --version), where this exact
     content stands. Stored under VERSION: succeed only if the version is
     available (see below), otherwise fail and say whether it is still being
     checked or was blocked. Stored under another version: fail;
  2. refuses VERSION unless it is greater than ClawHub's latest public version;
  3. on a dry run, shows the plan. On a real run, publishes with --version
     VERSION, keeps the attempt id, and waits up to POLL_SECONDS for the version
     to become available. A blocked release, or one still under checks at the
     deadline, fails the run; re-running later never uploads identical content
     again and reports the outcome.

Both decisions come from two public, owner-scoped ClawHub endpoints (no token
needed, and neither adds to the skill's download count):
  GET  /api/v1/skills/<slug>/versions/<version>?ownerHandle=<owner>
       200 only when the version is published and not hidden or removed;
  GET  /api/v1/skills/<slug>/file?path=SKILL.md&version=<version>&ownerHandle=<owner>
       200 when the version's files may be served; 403 when its security scan,
       including a later rescan, failed or flagged it as malicious. It answers
       for unpublished versions too, so a blocked submission is seen at once.
  available = both return 200;  blocked = the file endpoint returns 403.

POST /api/v1/skills/-/security-verdicts only adds wording to messages. It is not
scoped to a publisher, so its answer is used only when the returned
publisherHandle and version match this release, and it never decides the
outcome.

Environment: VERSION, DRY_RUN ("true"/"false"), SKILL_PATH, OWNER, REGISTRY,
CLI_ENTRY (path to the ClawHub cli.ts), BUN (default "bun"), POLL_SECONDS
(default 600), POLL_INTERVAL (default 30), and the standard GITHUB_WORKSPACE,
GITHUB_REPOSITORY, GITHUB_SHA, GITHUB_REF, GITHUB_OUTPUT, GITHUB_STEP_SUMMARY.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RELEASE = re.compile(r"\d+\.\d+\.\d+")
SUBMITTED = {"published", "pending-publication", "submitted"}


def fail(message: str) -> None:
    print(f"::error::{message}")
    sys.exit(1)


def summary(line: str) -> None:
    print(line)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def release_key(version: str, label: str) -> tuple[int, int, int]:
    if not RELEASE.fullmatch(version):
        fail(f"{label} {version!r} is not a plain MAJOR.MINOR.PATCH release.")
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def handle(value: object) -> str:
    return str(value or "").strip().lstrip("@").lower()


class ClawHubApi:
    """Public read endpoints that say whether a version is really available to users."""

    def __init__(self, registry: str, slug: str, owner: str) -> None:
        self.registry = registry.rstrip("/")
        self.slug = slug
        self.owner = owner

    def _request(self, method: str, path: str, body: dict | None = None) -> tuple[int | None, str]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.registry + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as error:
            return None, str(error)

    def availability(self, version: str) -> tuple[bool, bool, str]:
        """Return (available, blocked, detail) from the two owner-scoped endpoints."""
        slug = urllib.parse.quote(self.slug)
        listed_query = urllib.parse.urlencode({"ownerHandle": self.owner})
        listed, listed_text = self._request(
            "GET", f"/api/v1/skills/{slug}/versions/{urllib.parse.quote(version)}?{listed_query}")
        file_query = urllib.parse.urlencode({"path": "SKILL.md", "version": version, "ownerHandle": self.owner})
        served, served_text = self._request("GET", f"/api/v1/skills/{slug}/file?{file_query}")

        if listed == 200 and served == 200:
            return True, False, "published and downloadable"
        parts = []
        if listed is None or served is None:
            parts.append(f"ClawHub unreachable: {listed_text if listed is None else served_text}")
        if listed not in (200, None):
            parts.append(f"not listed as published (HTTP {listed}: {listed_text.strip()[:100]})")
        if served not in (200, None):
            parts.append(f"files not served (HTTP {served}: {served_text.strip()[:100]})")
        return False, served == 403, "; ".join(parts)

    def security_verdict(self, version: str) -> tuple[str, str | None]:
        """Describe ClawHub's scan result for this release. Returns (text, raw scan state or None).

        The endpoint is not scoped to a publisher, so an answer about another
        publisher's skill or another version is reported as unavailable.
        """
        status, text = self._request(
            "POST", "/api/v1/skills/-/security-verdicts", {"items": [{"slug": self.slug, "version": version}]}
        )
        if status != 200:
            return f"security verdict unavailable (HTTP {status})", None
        try:
            item = json.loads(text)["items"][0]
        except (ValueError, KeyError, IndexError, TypeError):
            return "security verdict unreadable", None
        if item.get("error"):
            error = item["error"]
            return f"security verdict: {error.get('code')} ({error.get('message')})", None
        if handle(item.get("publisherHandle")) != handle(self.owner) or item.get("version") != version:
            return "security verdict not available for this publisher's release", None
        security = item.get("security") or {}
        raw = str(security.get("verdict") or security.get("rawStatus") or security.get("status") or "").lower()
        reasons = ", ".join(str(reason) for reason in item.get("reasons") or []) or "none"
        return f"security verdict: {item.get('decision')}, scan {raw or 'unknown'}, reasons {reasons}", raw or None

    def diagnose(self, version: str) -> tuple[bool, bool, str, str | None]:
        """Returns (available, blocked, detail, raw scan state); the verdict only adds wording."""
        available, blocked, detail = self.availability(version)
        if available:
            return True, False, detail, None
        verdict, raw = self.security_verdict(version)
        return False, blocked, f"{detail}; {verdict}", raw


def blocked_advice(raw: str | None) -> str:
    if raw in {"failed", "error"}:
        return ("ClawHub's security scan failed rather than finding a problem; ask ClawHub to rescan "
                "this version before changing the skill.")
    if raw == "malicious":
        return "ClawHub's scan flagged the content; fix the skill and publish a new version."
    return ("If the scan failed, ask ClawHub to rescan this version; if it flagged the content, fix the "
            "skill and publish a new version.")


def wait_until_available(api: ClawHubApi, version: str, seconds: float,
                         interval: float) -> tuple[bool, bool, str, str | None]:
    """Poll until the version is available or blocked, or the deadline passes."""
    deadline = time.monotonic() + seconds
    while True:
        available, blocked, detail, raw = api.diagnose(version)
        if available or blocked or time.monotonic() >= deadline:
            return available, blocked, detail, raw
        print(f"Not available yet ({detail}). Checking again in {interval:g}s.")
        time.sleep(interval)


def main() -> None:
    env = os.environ
    version = env.get("VERSION", "")
    dry_run = env.get("DRY_RUN", "true") == "true"
    skill_path = env.get("SKILL_PATH", "skills/dnasp")
    slug = Path(skill_path).name
    workspace = Path(env.get("GITHUB_WORKSPACE", ".")).resolve()
    registry = env.get("REGISTRY", "https://clawhub.ai")
    poll_seconds = float(env.get("POLL_SECONDS", "600"))
    poll_interval = float(env.get("POLL_INTERVAL", "30"))
    release_key(version, "VERSION")
    api = ClawHubApi(registry, slug, env["OWNER"])

    command = [
        env.get("BUN", "bun"), str(workspace / env["CLI_ENTRY"]),
        "--workdir", str(workspace),
        "--site", env.get("SITE", "https://clawhub.ai"),
        "--registry", registry,
        "skill", "publish", skill_path,
        "--json",
        "--owner", env["OWNER"],
    ]

    def clawhub(*extra: str) -> dict:
        completed = subprocess.run([*command, *extra], cwd=workspace, capture_output=True, text=True)
        if completed.returncode != 0:
            fail("clawhub skill publish failed: "
                 + (completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"))
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError:
            fail(f"clawhub skill publish printed something other than JSON: {completed.stdout[:500]}")

    # 1. Where does this exact content stand on ClawHub? Nothing is uploaded.
    probe = clawhub("--dry-run")
    latest = probe.get("latestVersion")
    print(f"ClawHub latest public version: {latest or '(none)'}; this content: {probe.get('status')}")
    if probe.get("status") == "unchanged":
        stored = probe.get("version")
        if stored != version:
            fail(f"This exact content is already stored on ClawHub as {slug}@{stored}, but the skill "
                 f"says {version}. Publishing it again would duplicate that release.")
        available, blocked, detail, raw = api.diagnose(version)
        if available:
            summary(f"{slug}@{version} is already published and downloadable. Nothing to do.")
            return
        if blocked:
            fail(f"This exact content was already submitted as {slug}@{version}, but ClawHub blocks it "
                 f"({detail}). Nothing was uploaded. {blocked_advice(raw)}")
        fail(f"This exact content was already submitted as {slug}@{version}, but it is not available yet "
             f"({detail}). Nothing was uploaded. If ClawHub is still checking it, re-run later.")

    # 2. Never reuse a version or go backwards.
    if latest and release_key(version, "VERSION") <= release_key(latest, "ClawHub latest version"):
        fail(f"{slug}@{version} is not greater than ClawHub's latest version {latest}. "
             "Bump the version before publishing changed content.")

    # 3. Publish at the recorded version, or show the plan.
    if dry_run:
        plan = clawhub("--dry-run", "--version", version)
        if plan.get("version") != version:
            fail(f"ClawHub planned version {plan.get('version')}, expected {version}.")
        summary(f"Dry run: would publish {slug}@{version} ({plan.get('fileCount')} files, "
                f"latest on ClawHub: {latest or 'none'}).")
        return

    source = ["--source-repo", env["GITHUB_REPOSITORY"], "--source-commit", env["GITHUB_SHA"],
              "--source-path", skill_path]
    if env.get("GITHUB_REF"):
        source += ["--source-ref", env["GITHUB_REF"]]
    result = clawhub("--version", version, "--tags", "latest", *source)
    status = result.get("status")
    attempt = result.get("attemptId") or "n/a"
    if result.get("version") != version or status not in SUBMITTED:
        fail(f"Unexpected publish result: {json.dumps(result)}")
    output("attempt_id", attempt)
    output("publication_status", str(status))
    print(f"ClawHub accepted {slug}@{version}: status {status}, attempt {attempt}, "
          f"version id {result.get('versionId') or 'n/a'}.")

    available, blocked, detail, raw = wait_until_available(api, version, poll_seconds, poll_interval)
    if available:
        summary(f"Published {slug}@{version}: ClawHub lists it and serves it for download (attempt {attempt}).")
        return
    if blocked:
        fail(f"{slug}@{version} was submitted (attempt {attempt}) but ClawHub blocks it: {detail}. "
             f"{blocked_advice(raw)}")
    fail(f"{slug}@{version} was submitted (status {status}, attempt {attempt}) but is not available "
         f"after {poll_seconds:g}s: {detail}. Re-run this workflow later: it will not upload identical "
         "content again and will report whether the version became available or was blocked.")


if __name__ == "__main__":
    main()
