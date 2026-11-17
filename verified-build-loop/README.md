# Verified build loop

Version 2.0.0.

## 1. What this package is

This folder holds 1 Claude Code plugin with 1 skill, `verified-build-loop`. The skill installs an enforced build loop in a project. Claude Code runs the loop's hooks itself, so the loop does not depend on Claude remembering an instruction.

| Hook | When Claude Code runs it | What it does |
|---|---|---|
| Plan gate (`plan_check.py`) | When Claude presents a plan in plan mode | Denies a plan with no "Acceptance checks" part that names a command, or with no "Assumptions" part |
| Edit check (`post_edit_lint.py`) | After each Write or Edit | Runs the project's lint command on the edited file and shows the errors to Claude |
| Stop gate (`stop_check.py`) | Each time Claude tries to end a turn | Blocks while a check in `.claude/verify.json` fails, and while a protected file, a check or a setting changed against the rules |
| Protection (`protect_paths.py`) | Before each Write, Edit, NotebookEdit and Bash call | Blocks changes to protected tests, to the hooks and to the checks |

The skill also installs a read-only `reviewer` subagent. Nothing enforces its use.

This folder stands alone. The 18 skills and the build tool at the root of the repository do not read it. The root `.claude/` folder holds an installed copy of the loop, because this repository uses the loop on itself; `tests/test_project_setup.py` at the root keeps that copy equal to this source.

### Layout

```
README.md                                    this file
plugin/.claude-plugin/plugin.json            the plugin manifest
plugin/skills/verified-build-loop/SKILL.md   the skill: setup, the 2 work loops, repair
plugin/skills/verified-build-loop/scripts/   the 5 hook scripts
plugin/skills/verified-build-loop/templates/ the files that setup copies into a project
plugin/skills/verified-build-loop/tests/     64 tests of the 5 scripts
tools/build.py                               builds and checks the upload zip
tests/test_package.py                        4 tests of the zip, the manifest and the marketplace entry
dist/verified-build-loop.zip                 the upload package for claude.ai (generated)
backup/original-SKILL.md                     version 1, as the claude.ai account held it on 2026-11-17
```

## 2. How to install the skill

Use 1 route in each environment. A skill installed through 2 routes loads 2 times.

| Route | Steps | Where the skill then loads |
|---|---|---|
| claude.ai account | In the claude.ai settings, remove the old `verified-build-loop` skill, then upload `dist/verified-build-loop.zip` | Every Claude Code cloud session and claude.ai. The skill only works where Claude can run commands. |
| Claude Code plugin | `/plugin marketplace add CatCorner22/Refined_Keep_Skills`, then `/plugin install verified-build-loop@refined-keep-skills` | Local Claude Code sessions, as `/verified-build-loop:verified-build-loop` |
| Project skill | Copy `plugin/skills/verified-build-loop/` into `.claude/skills/` of a repository and commit it | Sessions in that repository, cloud sessions included |

Then, in the project that you want to protect, type `/verified-build-loop`. The skill asks whether you want a quick setup or a full setup, proposes the checks, runs each check once, and installs the hooks after you confirm.

The plugin does not run the hooks itself. Setup copies the 5 scripts into `.claude/hooks/` of the project and adds 4 hook groups to `.claude/settings.json`. A committed copy works in a cloud session, and you can read exactly what runs.

## 3. What changed from version 1

Version 1 is the skill that the claude.ai account held: 1 `SKILL.md` of 1,043 lines with the 4 scripts printed in an appendix. Each finding below was reproduced by running the version 1 scripts before the fix, and a test now pins the fix.

| Finding in version 1 | What version 2 does |
|---|---|
| Setup had Claude retype 653 lines of Python from the appendix, because the uploaded skill held no `scripts/` folder | The skill ships the scripts. Setup copies them with `cp` and confirms each copy with `cmp`. `SKILL.md` has 271 lines. |
| Claude could add a folder to `fingerprint_exclude` in `verify.json`. Changes in that folder then never reran the checks, so Claude could end a turn with broken code. | Only the user can change `fingerprint_exclude`, `feature_list` and `plan_gate`. A missing key counts as its default. |
| A failing check that printed a byte that is not UTF-8 crashed the Stop hook. Claude Code treats a crashed hook as a non-blocking error, so the turn ended unchecked. | Output is decoded leniently. Any other internal error blocks once, so that Claude tells the user, and then ends the turn with a message to the user. |
| A malformed `verify.json` (for example a list) crashed the Stop hook in the same way | The Stop hook names each malformed part and blocks |
| A file that git ignores (a log, a cache) changed the fingerprint, so the checks ran on every turn. A tracked file in `dist/`, `build/` or `target/` did not count, so a change there never ran the checks. | In a git repository, the project files are the files that git does not ignore |
| The integrity message told Claude to restore a protected file with git, and the PreToolUse hook blocked `git restore <path>` | A lone `git restore <path>` or `git checkout [HEAD] -- <path>` is allowed. Every other form stays blocked. |
| The unlock command, given a pattern such as `tests/*`, left the hashes of its files in the lock, so the next Stop reported them as missing. Given a path that was not in the list, it printed "Unprotected". | The Stop hook forgets hashes that no pattern covers. The unlock command reports a path that is not in the list. |
| A timed-out check left its child processes running | The check runs in its own process group, and a timeout stops the group |
| Nothing made a plan name its checks | The plan gate (new) |
| Setup always needed a specification interview and a feature list | A quick setup installs the checks and hooks only. The task loop (Phase 2A) needs no feature list. |

42 of the 43 tests that shipped with version 1 pass against the version 2 scripts. The 1 that does not pass asserts that `git checkout -- <protected path>` is blocked, which version 2 allows on purpose.

## 4. Limits

- The hooks check what the checks cover. A check that passes does not prove that the work is right.
- The plan gate reads the form of a plan. It cannot judge whether the acceptance checks are the right ones. It acts only in plan mode.
- The Bash rule of the PreToolUse hook is a heuristic. It reads the whole command text, so it also blocks a command whose text merely mentions a user-only command or a protected path next to a write command. The Stop hook's hash check is the backstop.
- A program that can run code can find a way around local hooks. The reviewer, the git history and your review of the diff are the backstop.
- The lock is local and git ignores it. A fresh clone, which every cloud session is, rebuilds the lock and runs the fast checks at the first Stop.
- An ignored file that matters to a check (for example a local `.env`) does not rerun the checks when it alone changes.
- The scripts are tested on Linux with Python 3.13. They target Python 3.8 or later. They are not tested on Windows.

## 5. How to change the skill

1. Edit the files under `plugin/skills/verified-build-loop/`.
2. Run `python3 -B -m unittest discover -s verified-build-loop/plugin/skills/verified-build-loop/tests`.
3. Run `python3 verified-build-loop/tools/build.py zip`, then `python3 -B -m unittest discover -s verified-build-loop/tests`.
4. If a script changed, replace the installed copies in the root `.claude/hooks/` yourself, in a terminal, because the hooks stop Claude from doing it. Run these 2 commands in the root of the repository:

   ```bash
   cp verified-build-loop/plugin/skills/verified-build-loop/scripts/*.py .claude/hooks/
   ```

   ```bash
   python3 .claude/hooks/vbl_common.py relock
   ```

5. Change the version in `plugin/.claude-plugin/plugin.json` and in the `metadata.version` of `SKILL.md` together.
6. Commit the skill folder, `dist/verified-build-loop.zip` and the installed copies together.
