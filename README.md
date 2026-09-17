# DnaSP: Agent Skill

Population genetics of pre-aligned DNA sequences and multi-sample VCFs, reimplementing selected
DnaSP 6 methods in Python and computed entirely on your own machine: nucleotide and haplotype
diversity, neutrality tests, linkage disequilibrium, recombination, InDel polymorphism,
divergence and Fst, HKA, McDonald-Kreitman, Ka/Ks, Fu's Fs, site frequency spectrum, Ts/Tv,
codon usage and Fay and Wu's H.

The skill itself lives in **[`skills/dnasp/`](skills/dnasp/)**. See
[`SKILL.md`](skills/dnasp/SKILL.md) for the agent-facing instructions and
[`docs/index.md`](skills/dnasp/docs/index.md) for the statistical reference.

> **Status:** version 0.6.0 in this repository, adding coalescent-simulation P-values for
> Tajima's D, R2 and Fu's Fs (`--n-sim`). ClawHub serves 0.5.3 at
> [drdaviddelorenzo/skills/dnasp](https://clawhub.ai/drdaviddelorenzo/skills/dnasp) until 0.6.0
> is uploaded. Not yet on Hermes.
>
> Earlier ClawHub releases numbered 0.1.x predate 0.5.3 and carry that registry's own numbering:
> ClawHub's GitHub importer, like `clawhub skill publish` without `--version`, numbers a new
> skill 1.0.0 and each later import as the next patch, whatever `SKILL.md` says. To publish
> under the skill's recorded version, upload the bundle directly and set the version by hand, or
> run [`publish-clawhub.yml`](.github/workflows/publish-clawhub.yml), which pins it and needs
> the `CLAWHUB_TOKEN` repository secret.

## Where the skill is developed

Development and validation against DnaSP 6 happen in the author's development copy. This
repository packages the skill so it can be installed on its own: at each validated release,
`skills/dnasp/` is refreshed from that copy, the packaging changes listed in
[`CHANGELOG.md`](skills/dnasp/CHANGELOG.md) are reapplied, and the version is bumped.

Do not fix a statistic here first. A fix made only in this repository is overwritten at the next
refresh.

## Install

**Hermes Agent**, adding this repository as a tap:

```bash
hermes skills tap add drdaviddelorenzo/dnasp
hermes skills install dnasp
```

**OpenClaw / ClawHub:**

```bash
openclaw skills install @drdaviddelorenzo/dnasp
```

**Manually:** copy `skills/dnasp/` into your agent's skills directory (`~/.hermes/skills/` for
Hermes, `~/.claude/skills/` for Claude Code), then install the optional plotting dependency:

```bash
pip install -r skills/dnasp/requirements.txt
```

## Quick start

```bash
python skills/dnasp/dnasp.py --demo --output dnasp_output_demo
python skills/dnasp/dnasp.py --input alignment.fas --analysis polymorphism,ld --output dnasp_output_run
```

Python 3.10 or later. The statistics, report and reproducibility bundle use the standard library;
matplotlib is needed only for figures.

> **Windows:** set `PYTHONUTF8=1` before running (`set PYTHONUTF8=1` in cmd,
> `$env:PYTHONUTF8 = "1"` in PowerShell). Without it, output captured through a pipe, as agents
> do, uses the Windows code page, and the skill stops on its non-ASCII statistic symbols. A fix is
> planned.

Run the tests with:

```bash
python -m pytest skills/dnasp/tests -q
```

## Repository layout

```
skills/dnasp/                             the skill (SKILL.md, dnasp.py, docs, examples, tests)
.github/workflows/tests.yml               tests and demo replay on Linux and Windows
.github/workflows/publish-clawhub.yml     manual-only ClawHub publishing
LICENSE.txt                               MIT (a copy also ships inside skills/dnasp/)
```

The `skills/` layout is what **both** registries expect: `hermes skills tap add` looks for skills
under `skills/<skill-name>/`, and ClawHub requires the skill's `name` to match its parent
directory. Moving this folder breaks both.

## Publishing (after a validated release)

**Bump the version for every published change**, in all four places: `SKILL.md` frontmatter
(`version` and `metadata.version`), `__version__` in `dnasp.py`, and a new `CHANGELOG.md` entry
dated `YYYY-MM-DD`.

| Target | How it is fed | To update |
|---|---|---|
| **ClawHub** | `.github/workflows/publish-clawhub.yml`, run by hand | run it as a dry run, then for real |
| **Hermes skills hub** | `hermes skills tap add drdaviddelorenzo/dnasp` | `hermes skills update` |

The ClawHub workflow publishes exactly the version recorded in the skill. It stops if the four
version numbers disagree, if the `CHANGELOG.md` entry is undated, or if the version is not greater
than ClawHub's latest. A run succeeds only once ClawHub lists that version as published and
lets it be downloaded: after publishing, it waits up to ten minutes for ClawHub's security checks, and fails if they are still
running at that point or the release was blocked. Re-running it never uploads identical content
again; it reports whether the version has since become public or was blocked. Real publishes need
a `CLAWHUB_TOKEN` repository secret (from `clawhub login --device`).

Do not publish this skill with ClawHub's web importer or its reusable `skill-publish.yml` workflow:
both choose the version number themselves (1.0.0 for a new skill, then the next patch) and ignore
`SKILL.md`.

Hermes reads the repository directly, so it must be public before the tap works.

## Citation

If you use this skill, please cite DnaSP 6, whose methods it reimplements:

> Rozas J, Ferrer-Mata A, Sanchez-DelBarrio JC, Guirao-Rico S, Librado P, Ramos-Onsins SE,
> Sanchez-Gracia A (2017). DnaSP 6: DNA Sequence Polymorphism Analysis of Large Data Sets.
> *Mol. Biol. Evol.* 34:3299-3302. https://doi.org/10.1093/molbev/msx248

Full credits are in [`CONTRIBUTORS.md`](skills/dnasp/CONTRIBUTORS.md).

## Licence

MIT, see [LICENSE.txt](LICENSE.txt). The same licence ships inside the skill directory
([`skills/dnasp/LICENSE.txt`](skills/dnasp/LICENSE.txt)), so every installed copy carries it.

> **Disclaimer:** research and educational use only. Not a medical device and not clinical advice.
