# Chicken Little Overwatch (plugin)

Version 2.0.0.

A Claude plugin that holds 1 skill, 8 read-only red-team subagents, 2 slash commands, and 2 scanners. Version 1.0.0 carried the names `llm-qc-suite` (plugin) and `llm-quality-control` (skill).

**Overwatch** is the quality control: Claude checks the work against its requirements and its evidence. **Chicken Little** is the red team: it asks what will fall later, and it must prove each alarm.

## Contents

| Path | Purpose |
|---|---|
| `.claude-plugin/plugin.json` | The plugin manifest |
| `skills/chicken-little-overwatch/SKILL.md` | The workflow, the modes, the precedence, the safety rules, and the output format |
| `skills/chicken-little-overwatch/references/quality-control.md` | The verification checklists |
| `skills/chicken-little-overwatch/references/red-team-swarm.md` | The swarm: rules RT1-RT12, tiers, charters, lenses L1-L14, Defender rules D1-D15, protocol, report |
| `skills/chicken-little-overwatch/references/one-way-optimal-language.md` | The complete writing standard: the original writing skill, byte for byte |
| `skills/chicken-little-overwatch/references/original-plugin.json` | The manifest of the original writing skill, byte for byte |
| `skills/chicken-little-overwatch/scripts/av_scan.py` | The fallback active-voice scanner |
| `skills/chicken-little-overwatch/scripts/watchlist_scan.py` | The scanner for watchlist words, spacing, dose formats, and sentence length |
| `agents/rt-*.md` | The 8 subagents: A1-A6, the Arbiter, and the Defender. `tools/build.py` in the parent folder generates these files; never edit them by hand |
| `commands/qc-review.md`, `commands/red-team.md` | The 2 slash commands |
| `tools/validate_package.py` | The package check |
| `CHANGELOG.md` | What changed in each version |

## Install

Use 1 route on each surface. If you install the plugin and also upload the skill to the same account, Claude Code lists the skill 2 times.

### Claude Code, for 1 session

```bash
claude --plugin-dir /path/to/chicken-little-overwatch
```

`/path/to/chicken-little-overwatch` is this folder: the folder that holds `.claude-plugin/`.

### Claude Code, installed

From a clone of the repository, add the folder that holds this plugin as a local marketplace. That folder is the parent of this folder.

```bash
claude plugin marketplace add /path/to/Refined_Keep_Skills/chicken-little-overwatch
```

```bash
claude plugin install chicken-little-overwatch@chicken-little
```

### claude.ai (chat and Cowork): the skill alone

Upload `chicken-little-overwatch-skill.zip` under Customize > Skills > "+" > "+ Create skill" > "Upload a skill". The zip holds 1 top-level folder named `chicken-little-overwatch`. On this surface the skill has no subagents, so it runs each red-team charter as a separate pass and says so.

## Use

| You type | Claude does |
|---|---|
| `/chicken-little-overwatch:qc-review FILE` | Reviews FILE in Review mode. Claude never changes FILE. |
| `/chicken-little-overwatch:qc-review FILE rewrite` | Reviews FILE and writes a revision to a new file or to the reply. |
| `/chicken-little-overwatch:qc-review FILE full T3` | Runs every step, with the full swarm. |
| `/chicken-little-overwatch:red-team FILE` | Runs the swarm alone, at the tier that the stakes require. |
| `/chicken-little-overwatch:red-team FILE T1` | Runs the light swarm: 2 agent runs. |
| "Review this policy" or "red-team this plan", in plain words | Loads the skill by its description. |

The 3 tiers:

| Tier | When | Agent runs |
|---|---|---|
| T1 Light | Low stakes, reversible, personal use | 2 |
| T2 Standard | Shared or business use, moderate cost of error | 6 |
| T3 Full | Regulated data, money, safety, patient or customer exposure, hard-to-reverse choices | 15 to 21: 6 attacks, 6 cross-examinations, the Arbiter, the Defender, 0 to 6 rebuttals, and the Arbiter's final ruling |

T3 uses many tokens. Claude states the tier and the number of agent runs before it launches the swarm.

## Run the scanners yourself

```bash
python3 skills/chicken-little-overwatch/scripts/av_scan.py --strict FILE
```

```bash
python3 skills/chicken-little-overwatch/scripts/watchlist_scan.py --summary FILE
```

| Scanner | Exit code 0 | Exit code 1 | Exit code 2 |
|---|---|---|---|
| `av_scan.py` | no blocking hit | a blocking hit, or a marker or code fence that never closes | the scanner could not read a file |
| `watchlist_scan.py` | the scan ran | hits, with `--fail` only | the scanner could not read a file |

Both scanners need Python 3.8 or later and nothing else.

## Check the package

```bash
python3 tools/validate_package.py
```

The check prints `OK: package checks passed` and exits with code 0, or it prints each defect and exits with code 1.

## Known limits

- This package omits the full `active_voice_check.py` that the writing standard describes. The bundled `av_scan.py` uses the writing standard's fallback patterns. It flags more than it needs to, and the eye check stays mandatory.
- The writing standard's legal statements, research figures, and benchmark results are source claims. This package does not re-verify them. The writing standard gives its own test date: 9 November 2026.
- The subagents work read-only by instruction. Their tool lists hold no Write tool and no Edit tool, but 6 of the 8 have a shell, and a shell can write. After a swarm run on work that matters, run `git status`.
- A single model that plays every red-team role shares its own blind spots. Real subagents reduce that risk; they do not remove it.
- The Defender calibration thresholds in D13 (more than half defeated; none across ten or more) are judgment calls. Tune them after real runs.
- The package has no LICENSE file. The owner has not chosen a license.
