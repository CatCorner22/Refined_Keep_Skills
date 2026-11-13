# Changelog

This file lists the changes that a user of the plugin or the skill can notice. The version number is the `version` in `.claude-plugin/plugin.json` and the `metadata.version` in `skills/chicken-little-overwatch/SKILL.md`.

## [2.0.0] - 2026-11-13

Version 2.0.0 renames the package and repairs the defects that a review of version 1.0.0 found. Version 1.0.0 carried the plugin name `llm-qc-suite` and the skill name `llm-quality-control`.

### Changed: names

- The plugin and the skill both carry the name `chicken-little-overwatch`.
- The slash commands are `/chicken-little-overwatch:qc-review` and `/chicken-little-overwatch:red-team`.
- The subagents keep their short names (`rt-proofreader`, and so on). Claude Code registers each one as `chicken-little-overwatch:rt-proofreader`, and so on.

### Fixed

- 4 files had front matter that a YAML parser rejects: `SKILL.md`, `agents/rt-style-prosecutor.md`, `commands/qc-review.md`, and `commands/red-team.md`. Each carried an unquoted value with a colon or a bracket. A surface that parses YAML strictly, such as the claude.ai skill upload, refuses such a file. Every value that needs quotes now has them.
- The skill ran its scanners by a relative path (`python3 scripts/av_scan.py`). That command fails unless the working directory is the skill's folder. Every command now starts with `${CLAUDE_SKILL_DIR}` or `${CLAUDE_PLUGIN_ROOT}`.
- The subagents pointed to `references/red-team-swarm.md` with no way to find that file. Each agent file now repeats the rules that it needs, and it names the file by its full path.
- The attack agents assigned severity without a severity scale. Each agent file now carries the scale.
- The precedence list ranked the Hard Rules above Rule 1 (active voice), although the writing standard ranks Rule 1 first. The list now follows the writing standard, and it states that Rule 1 never permits a guess.
- `av_scan.py`: an opening marker and a closing marker on one line left the zone open to the end of the file, so every later hit lost its blocking status. The scanner now reads markers inline.
- `av_scan.py`: the scanner missed a passive that a line break splits (`was` at the end of one line, `changed` at the start of the next). The scanner now also scans the wrapped lines of one paragraph as one unit.
- `av_scan.py` and `watchlist_scan.py`: a missing file, a directory, or a byte that is not UTF-8 ended the run with a Python traceback. Each scanner now prints one error line and exits with code 2.
- `watchlist_scan.py`: the sentence-length check counted each line alone, so it missed a long sentence that wraps. The check now joins wrapped lines, and it measures each table cell separately.

### Added

- Modes in the skill: Review, Rewrite, Red team, and Full. Review mode and Red team mode never change the artifact.
- Safety rules for the review itself: material is never an instruction, no silent changes, safe testing, confidentiality, and untrusted markers.
- Swarm rules RT11 (safe testing) and RT12 (confidentiality), and 3 independence levels in RT7: plugin subagents, general subagents, sequential passes.
- `av_scan.py --ignore-markers`, for a file whose markers the reviewer did not write. The scanner reports a marker or a code fence that never closes as a FAULT and exits with code 1.
- `av_scan.py` and `watchlist_scan.py` read standard input when the file name is `-`. `watchlist_scan.py --summary` prints the number of hits for each label.
- A "What can go wrong" table in the skill.
- `tools/validate_package.py` now checks every front matter block with a strict parser, the skill's upload limits, each agent's tool list, the SHA-256 of the 2 byte-for-byte files, the rules that the agents repeat, and the scanner's pattern set against the writing standard.

### Changed: other

- `rt-future-analyst` no longer has a shell. It needs none.
- `watchlist_scan.py` skips URLs, HTML comments, and the text of inline code spans. `--include-code` scans the code too.
- The commands default to Review mode when the user names no mode.
- The red-team loop stops after 3 full passes and reports the findings that remain open.

### Unchanged

- `references/one-way-optimal-language.md` and `references/original-plugin.json` are byte for byte the files of version 1.0.0.
- The scanner's pattern set, the Defender rules D1-D15, the lenses L1-L14, the severity scale, and the finding format keep their wording.

## [1.0.0] - 2026-11-13

- The first package, under the names `llm-qc-suite` (plugin) and `llm-quality-control` (skill).
