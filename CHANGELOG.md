# Changelog

This file lists the changes that a user of the skills can notice. The format follows "Keep a Changelog". Version numbers are the `version` in `.claude-plugin/plugin.json`, the `VERSION` in `lib/ad_core.py` and the `metadata.version` in every `SKILL.md`.

## [2.1.0] - 2026-11-13

### Added

- New skill `backward-review-gate` (scripted). Before Claude presents a plan, sends a reply, delivers work or acts on a plan, Claude reviews the work product from its last part to its first part, corrects every error, re-reads it from first to last, and ends it with a review record. The repository now holds 18 skills, 12 of them scripted.
- `references/always-on-rule.md` in that skill: 6 numbered lines for the instructions that a surface loads in every session (claude.ai personal preferences, claude.ai project instructions, `~/.claude/CLAUDE.md`, a repository `CLAUDE.md`), with the steps for each surface.
- `CLAUDE.md` at the root of this repository, with the always-on rule.
- New sub-command `review [TEXT...] [--file PATH] [--plan]`: checks a reply or a plan for a complete review record. Exit code 0 for PASS, 1 otherwise.
- New hook names: `review-reminder` (UserPromptSubmit), `pre-plan` (PreToolUse on ExitPlanMode), `review-gate` (SubagentStop) and `stop` (Stop).
- New settings: `AD_REVIEW=off` turns the review gate and its hooks off. `AD_REVIEW_MIN_CHARS` sets a length below which a reply needs no review record (default 0: every reply needs it).

### Changed

- The Stop entry in `hooks/hooks.json` and in `docs/hooks-settings-example.json` runs `hook stop`, which runs the review gate and the completion gate in 1 process and prompts once with both reasons. `hook completion-gate` still works and runs the completion gate alone.
- With the hooks enabled, every final message and every plan now needs a review record. If you copied the hooks into a project settings file, copy them again to get the 3 new entries.

## [2.0.0] - 2026-11-10

Version 2 is a rewrite after a review of version 1. A GRANT entry in the ledger no longer unlocks anything: record an approval instead.

### Changed: approvals and the scope fence

- An approval replaces ledger matching. `ad.py approve -- '<exact command>'` stores the hash of 1 exact command with an expiry time (default 30 minutes, maximum 1440). In version 1, any ledger line with similar words unlocked the scope fence.
- The scope fence parses a command into segments before it classifies the command. It looks through wrappers such as `sudo` and `env`, through `sh -c`, `$( )`, `xargs` and `find -exec`, and it ignores text inside the quoted arguments of programs that do not execute them.
- The scope fence checks write targets only (redirection targets and the operands that a tool writes to), resolved to real paths. In version 1 it scanned every path-like string, file content included.
- The scope fence denies a direct write to `approvals.json`, `scope.json` and `ledger.md`.
- The fetch guard matches a fetch against the read manifest by URL, by output path, or by a unique file name. The `size:` comment bypass and the "any GRANT that mentions download" bypass are gone.
- The retry rule counts identical failures in a row inside 1 session and resets when another change happens in between.
- Every denial ends with the exact next step.
- The guards read only the command, the file path or the URL of a tool call. They never read file content or the description field.

### Changed: state

- 1 state directory for each repository. The CLI walks upward to the repository root. Version 1 created `.agent/` in every working directory.
- The state directory ignores itself in git (`.gitignore` with `*`), has mode 0700, and refuses state files that are symbolic links.
- Writes are atomic and locked.
- `ledger add` rejects an unknown kind and stores each entry on 1 line, so text with a line break cannot forge a second entry.
- Read manifest entries carry merged line ranges, a fingerprint, the session and the agent. Change detection compares size and modification time first and hashes only when they differ.
- The tool log redacts obvious secrets and rotates at 1 MB.
- Read-only sub-commands do not create the state directory.

### Changed: hooks

- Every hook entry uses the exec form and a bootstrap that exits 0 when the script is missing. In version 1, a missing script blocked every matched tool call.
- A denial is a JSON decision with exit code 0. `ad.py hook` never exits non-zero.
- The matchers cover the PowerShell tool. `MultiEdit`, which is not a tool, is gone.
- The PostCompact entry is removed, because its output never reaches the model. The SessionStart hook handles `compact` and `resume`.
- 1 `pre-bash` process replaces 3 separate shell hooks.
- At startup the SessionStart hook adds a 1-line summary, not the full reinjection. The reinjection labels its entries as records, not instructions.
- The Read hook adds a note only for a true re-read by the same session and agent. It never blocks a read.
- The completion gate prompts once for each stop attempt, uses anchored phrase patterns, and compares the cited command with the tool log.
- Output trimming in the log hook is off by default (`AD_TRIM_HOOK=1` turns it on).
- New: `docs/hooks-settings-example.json`, the same hooks for a project `.claude/settings.json`. This route works in cloud sessions.

### Changed: CLI

- `argparse` sub-commands with fixed exit codes: 0 success or allowed, 1 a check said no, 2 usage error. A bad argument no longer ends in a traceback.
- New sub-commands: `version`, `approve`, `approvals`, `scope add`, `ledger clear`. New hook names: `session-start`, `pre-bash`, `pre-write`, `pre-fetch`, `log`, `log-failure`. The version 1 hook names still work.
- `rules compile` prints `permissions.deny` entries and an exec-form hook fragment. The version 1 output resolved only inside the plugin.
- `rules rewrite` prints a fill-in template. It no longer presents a mechanical rewrite as a finished rule.
- `test-impact` reads NUL-separated git output, includes untracked files, validates `--base`, and reports unmapped files.
- `regress` takes item IDs from `set.json` and warns on an unknown ID.
- New module `ad_shell.py` (command parsing). The library has 8 files.
- `ad.py` runs from any working directory and writes no bytecode into skill folders.

### Changed: skills

- Every command example uses `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py"`. Version 1 printed `python3 scripts/ad.py`, which ran whatever file the current directory held.
- Frontmatter holds only `name`, `description`, `compatibility`, `metadata` and `allowed-tools`, which the claude.ai upload accepts.
- `allowed-tools` lists 1 rule for each sub-command that the skill uses. No skill pre-approves `approve`, `approvals clear`, `scope set` or `scope add`.
- Descriptions are at most 400 characters with the key use case first. No description says that a hook enforces the skill.
- Every skill has the same sections, 1 term for each concept, and a "Without a shell" section for chats with no code execution.
- Skill texts no longer tell Claude to run `/compact`. They tell Claude to ask the user to run it.
- Statistics, incident stories and attributions that the review did not verify are removed.
- Personal names and personal data examples are replaced by neutral examples.
- `tool-call-validator` is now instructions only and carries no copy of the library.

### Added: packaging

- `lib/` is the only hand-edited copy of the library. `tools/build.py sync` generates the copy in each of the 11 scripted skills.
- `tools/build.py check` fails on drift, on frontmatter defects, on a command without the placeholder, on an unknown sub-command or sibling name, on differing versions, and on a stale zip.
- `tools/build.py zip` writes deterministic zips to `dist/`, 1 for each skill, with a single top-level folder.
- `tools/build.py validate` re-implements the upload validator with the standard library.
- `.claude-plugin/marketplace.json`, so that `/plugin marketplace add` and `/plugin install agent-discipline@refined-keep-skills` work. The version 1 README gave an install command that failed.
- The plugin manifest points at `./.claude/skills/`, so project skills and plugin skills are the same files.
- `.gitignore`, this changelog, and `tests/test_packaging.py`.

### Not decided

- License. The repository has no LICENSE file and `plugin.json` has no `license` field.

## [1.0.0]

The original bundle: 17 skills in 2 copies (plugin and standalone), 9 hook entries, 7 library files copied into 12 skill folders by hand, and 17 zips with no build script.

## 2.0.1

- living-reference: PDF export now works without a pandoc PDF engine. The export script uses the first route that exists: a pandoc PDF engine, then LibreOffice, then a Chromium browser. Tests cover both fallback routes.
- The retry rule no longer counts the CLI's own negative answers (for example `ledger check` with no match) as failed retries.
