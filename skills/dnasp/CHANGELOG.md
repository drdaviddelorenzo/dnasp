# Changelog

All notable changes to the `dnasp` skill package are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.5.1] - unreleased

Not yet published to ClawHub or Hermes: awaiting a validated DnaSP release.

### Source
- Packaged from the development copy of skill version 0.5.1, whose validation against DnaSP 6 is
  in progress. No statistic, parser or report formula was changed by the packaging.

### Changed for packaging
- Reproducibility writers: `_repro_writers.py`, written for this package, provides
  `write_commands_sh`, `write_environment_yml` and `write_checksums`. `dnasp.py` loads it by file
  path under a private module name (`_load_repro_writers`), so an unrelated module named
  `reproducibility`, whether already imported or earlier on `sys.path`, can never supply the
  writers, and nothing is added to `sys.path` or `sys.modules`. Checksum labels always use forward
  slashes.
- Reports name the tool as DnaSP-Python in the header, the Methods section and the disclaimer.
- `LICENSE.txt` ships inside `skills/dnasp/` as well as at the repository root, so every installed
  copy carries it.
- `SKILL.md`: top-level `version` and `compatibility`, a `metadata.hermes` block, the OpenClaw
  emoji and homepage, commands written relative to the skill directory, and an Integration section
  for calling `dnasp.py` directly. Dependencies list matplotlib only: the skill never imports
  numpy, pandas or OpenTelemetry.
- `environment.yml` and the new `requirements.txt` match those dependencies.

### Added
- `tests/test_standalone_packaging.py`: writer loading under a conflicting `sys.modules` entry and
  a conflicting earlier `sys.path` entry, bundle formats (checksums verify, LF endings, executable
  `commands.sh` that replays, `environment.yml` contents), the licence inside the skill directory,
  report wording, and imports limited to the standard library, matplotlib and the skill's own
  modules.
- `.github/workflows/tests.yml` (repository root): the test suite, a `--demo` run, checksum
  verification and a bash replay of `commands.sh` on Ubuntu and Windows with Python 3.10 and
  3.13, plus an Ubuntu job without matplotlib. The Windows jobs run in Python's UTF-8 mode
  (`PYTHONUTF8=1`); see Known issues.

### Known issues
- Windows without UTF-8 mode: when stdout is redirected (as when an agent captures it), Python uses
  the ANSI code page and the console summary's non-ASCII symbols raise `UnicodeEncodeError`, so
  the run exits 1. `results.tsv` and `ld_pairs.tsv` are also written without an explicit encoding,
  and several tests read reports with the platform default. Workaround: `PYTHONUTF8=1`. A fix is
  ready and arrives with the next refresh.

### Removed
- A test of an external command-line dispatcher that is not part of this package.
