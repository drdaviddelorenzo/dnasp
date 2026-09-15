"""Work out the version to publish to ClawHub and check the skill agrees with itself.

The version is read from four places, which must all match:
  - SKILL.md frontmatter `version`
  - SKILL.md frontmatter `metadata.version`
  - `__version__` in dnasp.py
  - the latest `## [X.Y.Z] - date` entry in CHANGELOG.md

It must be a plain MAJOR.MINOR.PATCH release. A real publish also needs that
CHANGELOG entry to carry a YYYY-MM-DD date; a dry run only warns.

Environment: SKILL_PATH (default skills/dnasp), DRY_RUN ("true" or "false").
Writes `version=X.Y.Z` to $GITHUB_OUTPUT when that variable is set.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

import yaml

RELEASE = re.compile(r"\d+\.\d+\.\d+")
CHANGELOG_ENTRY = re.compile(r"^## \[([^\]]+)\] - (.+?)\s*$", re.MULTILINE)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def fail(message: str) -> None:
    print(f"::error::{message}")
    sys.exit(1)


def frontmatter(skill_md: Path) -> dict:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        fail(f"{skill_md} has no YAML frontmatter")
    data = yaml.safe_load(text.split("---", 2)[1])
    if not isinstance(data, dict):
        fail(f"{skill_md} frontmatter is not a mapping")
    return data


def module_version(script: Path) -> str:
    for node in ast.parse(script.read_text(encoding="utf-8")).body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)):
            return str(node.value.value)
    return ""


def main() -> None:
    skill = Path(os.environ.get("SKILL_PATH", "skills/dnasp"))
    dry_run = os.environ.get("DRY_RUN", "true") == "true"

    meta = frontmatter(skill / "SKILL.md")
    entry = CHANGELOG_ENTRY.search((skill / "CHANGELOG.md").read_text(encoding="utf-8"))
    if entry is None:
        fail(f"{skill / 'CHANGELOG.md'} has no '## [X.Y.Z] - date' entry")

    found = {
        "SKILL.md version": str(meta.get("version", "")),
        "SKILL.md metadata.version": str((meta.get("metadata") or {}).get("version", "")),
        f"{skill.name}.py __version__": module_version(skill / f"{skill.name}.py"),
        "CHANGELOG.md latest entry": entry.group(1).strip(),
    }
    for source, value in found.items():
        print(f"{source}: {value or '(missing)'}")

    values = set(found.values())
    if len(values) != 1 or "" in values:
        fail("Version numbers disagree or are missing; make all four match before publishing.")
    version = values.pop()
    if not RELEASE.fullmatch(version):
        fail(f"Version {version} is not a plain MAJOR.MINOR.PATCH release.")

    date = entry.group(2)
    if not DATE.fullmatch(date):
        message = f"CHANGELOG.md entry {version} is marked '{date}', not a YYYY-MM-DD release date."
        if not dry_run:
            fail(message + " Date the entry before a real publish.")
        print(f"::warning::{message} A real publish will refuse this.")

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"version={version}\n")
    print(f"Release version: {version}")


if __name__ == "__main__":
    main()
