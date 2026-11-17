---
name: "verified-build-loop"
description: "Sets up and repairs an enforced Claude Code build loop in a project: a Stop hook that blocks the end of a turn while a check fails, a plan gate that requires acceptance checks, lint after each edit, protected tests, and a read-only reviewer. Use when the user invokes /verified-build-loop or asks to make Claude Code verify its own code."
metadata:
  version: "2.0.0"
---

# Verified build loop

## Purpose

Claude stops when work looks done. This skill makes "done" something that a check proves. It installs 6 layers in a project:

| Layer | What it is | Who controls it |
|---|---|---|
| 1. Definition of done | Acceptance checks in every plan; in a full setup, also SPEC.md and feature_list.json | Instruction, file, and the plan gate |
| 2. Checks | Test, typecheck and lint commands in `.claude/verify.json` | File |
| 3. Enforcement hooks | Stop, PreToolUse and PostToolUse hooks | Claude Code enforces |
| 4. Protected tests | Test files that Claude may read and never change | Claude Code enforces |
| 5. Independent reviewer | Read-only `reviewer` subagent | Fresh context |
| 6. Session discipline | Tests first, small steps, an evidence report | Instruction |

Claude Code enforces layers 3 and 4, and the plan gate of layer 1. Everything else is an instruction that Claude chooses to follow. That is why the hooks exist.

## Terms

- **Check**: a command that exits 0 on pass and nonzero on fail.
- **Fast checks**: the checks that the Stop hook runs each time Claude tries to end a turn after a project file changed.
- **Full checks**: the checks that the Stop hook also runs when a feature changes to `"passes": true`. Only a full setup uses them.
- **Acceptance check**: a check that a plan names, before any code exists, as the proof that the planned work is done.
- **Protected file**: a file that Claude may read and never change. Only the user can unprotect it.
- **Lock**: `.claude/verify-lock.json`. The Stop hook records hashes and snapshots there and compares against them.
- **Project file**: in a git repository, a file that git does not ignore. Elsewhere, a file outside the dependency and cache folders.
- **Evidence report**: the exact commands that Claude ran and their output, at the end of a turn.
- **Skill folder**: `${CLAUDE_SKILL_DIR}`, the folder that holds this SKILL.md. Claude Code fills it in. If the placeholder appears unfilled, replace it with that folder's absolute path.

## Which phase to run

- The project has no `.claude/verify.json`: run **Phase 1 (Setup)**.
- The project has `.claude/verify.json` and no feature_list.json: run **Phase 2A (Task loop)**.
- The project has `.claude/verify.json` and feature_list.json: run **Phase 2B (Feature loop)**.
- A hook misbehaves or a file is missing: run **Phase 3 (Repair)**.

---

## Phase 1: Setup (once per project)

First ask the user which setup the project needs:

| Setup | What it installs | Use it when |
|---|---|---|
| **Quick** | Checks, hooks and the reviewer. Steps 1, 2, 6, 7 and 8. | The project exists and the user gives Claude tasks one at a time. |
| **Full** | Everything in Quick, plus SPEC.md, feature_list.json, progress.md and init.sh. Steps 1 through 8. | Claude builds a product over many sessions from a specification. |

A quick setup can become a full setup later: run Steps 3, 4 and 5 then.

Do every step in order. Tell the user what each step found before the next step.

### Step 1. Preflight

Run these and report the result of each:

1. `git rev-parse --is-inside-work-tree`. If the folder is not a git repository, ask the user whether to run `git init`. The loop depends on git to restore files and to tell project files from ignored files.
2. `git status --porcelain`. If the tree has uncommitted changes, ask the user whether to commit them first, so that the setup changes stay separate.
3. `python3 --version`. If that fails, try `python --version`. Use whichever works in every hook command in Step 6. If neither works, stop: the hooks need Python 3.8 or later.
4. Check whether `.claude/settings.json` exists. If it exists, Step 6 merges into it and does not replace it.
5. Check whether `.claude/verify.json` exists. If it exists, this project already has the loop; go to Phase 3.

### Step 2. Find or build the checks

1. Read the project's build files (for example package.json, pyproject.toml, Makefile, Cargo.toml, go.mod), its CI configuration, and its CLAUDE.md.
2. Propose the commands to the user: the fast checks, the lint-on-edit command (with a `{file}` placeholder), and, for a full setup, the full checks and an end-to-end test.
3. Exclude the `.claude/` folder from every check (for example `ruff check . --extend-exclude .claude`). The hooks protect their own files, so a check that reports on those files can never pass.
4. Run each proposed command once and show the output. A command that cannot run is not a check. Every check must pass on the current code before setup continues. If a check fails now, fix the cause or narrow the command, and get the user's approval for either choice. Otherwise the Stop hook blocks every turn on problems that predate the work.
5. If the project has no tests, build the smallest working test setup first (1 passing smoke test), and run it.
6. If the project has a user interface, the end-to-end check drives it the way a person would (for example Playwright for a web app). Unit tests alone do not prove that a feature works.
7. Ask the user to confirm the commands before you write them anywhere. After Step 6, only the user can change or remove a check; Claude can only add one.

Keep the fast checks fast. The Stop hook runs them on every turn that changes a project file. In a full setup, a suite that takes more than about 2 minutes belongs in the full checks. In a quick setup, the full checks never run, so every check goes in the fast checks. The Stop hook's own timeout is 1,800 seconds: keep the sum of the check timeouts below it.

### Step 3. Write SPEC.md by interviewing the user (full setup only)

1. Ask the user questions until you could write the specification without guessing. Ask multiple-choice questions where the tool allows. Cover: purpose, users, every requirement, the edge cases of each requirement, what is out of scope, and constraints.
2. Copy `${CLAUDE_SKILL_DIR}/templates/SPEC.md` to the project root and fill it in. Number every requirement.
3. Show SPEC.md to the user and get approval before Step 4.

### Step 4. Write feature_list.json (full setup only)

1. Copy `${CLAUDE_SKILL_DIR}/templates/feature_list.json` to the project root. Turn each numbered requirement into 1 or more features. Each feature is small enough to build and test in 1 session.
2. Give each feature an `id` (text, for example `"F001"`), a `description`, a `spec_section`, and `steps` that a person follows to test it end to end.
3. Set every feature to `"passes": false`.
4. After setup, the hooks allow only 2 kinds of change to this file: setting `passes`, and adding a new feature with `"passes": false`. Get every other field right now.

### Step 5. Write progress.md and init.sh (full setup only)

1. Copy `${CLAUDE_SKILL_DIR}/templates/progress.md` to the project root.
2. Copy `${CLAUDE_SKILL_DIR}/templates/init.sh` to the project root and replace its example lines with the project's real install and smoke-check commands. Run `bash init.sh` and confirm that it exits 0.

### Step 6. Install the hooks and the reviewer

Write the files in this order. The order matters: once `.claude/verify.json` exists, the PreToolUse hook protects the other files, so verify.json goes last.

1. **Hook scripts.** Copy the 5 scripts. Do not retype them and do not change them.

   ```bash
   mkdir -p .claude/hooks .claude/agents && cp "${CLAUDE_SKILL_DIR}"/scripts/*.py .claude/hooks/
   ```

   Then confirm that each copy is identical. This command prints nothing when every copy matches:

   ```bash
   for f in "${CLAUDE_SKILL_DIR}"/scripts/*.py; do cmp "$f" ".claude/hooks/$(basename "$f")"; done
   ```

2. **Reviewer.** Copy `${CLAUDE_SKILL_DIR}/templates/reviewer.md` to `.claude/agents/reviewer.md`.
3. **Settings.** Add the `hooks` object of `${CLAUDE_SKILL_DIR}/templates/settings-hooks.json` to `.claude/settings.json`. If the file exists, merge: keep every existing setting and every existing hook, and append these 4 hook groups to the lists of their events. If Step 1 found `python` and not `python3`, change the commands to match. Show the user the final file.
4. **CLAUDE.md.** Add a section to CLAUDE.md (create the file if needed), with the real check commands filled in: `${CLAUDE_SKILL_DIR}/templates/CLAUDE-section-quick.md` for a quick setup, `${CLAUDE_SKILL_DIR}/templates/CLAUDE-section.md` for a full setup.
5. **.gitignore.** Add 2 lines to .gitignore: `.claude/verify-lock.json` and `.claude/hooks/__pycache__/`. The lock holds timestamps that differ on each machine; each machine builds its own lock on its first Stop hook run. Python writes the cache folder when a hook runs.
6. **verify.json.** Copy `${CLAUDE_SKILL_DIR}/templates/verify.json` to `.claude/verify.json` and replace its example commands with the commands that the user confirmed in Step 2. In a quick setup, set `"full_checks": []`. Leave `"protected": []`; Phase 2 fills it. Leave `"fingerprint_exclude": []` unless the user names a folder of generated files that git tracks and that no check reads.

### Step 7. Smoke-test the hooks

1. Run each script by hand with a sample input and show the exit code:
   - `echo '{"tool_name":"Write","tool_input":{"file_path":"'"$PWD"'/.claude/verify-lock.json","content":"{}"}}' | python3 .claude/hooks/protect_paths.py; echo "exit $?"` must print `exit 2`.
   - `echo '{"tool_name":"ExitPlanMode","tool_input":{"plan":"1. Write the code."}}' | python3 .claude/hooks/plan_check.py; echo "exit $?"` must print `exit 2`.
   - `echo '{"stop_hook_active":false}' | python3 .claude/hooks/stop_check.py; echo "exit $?"` must print `exit 0` if the fast checks pass. This first run also creates the lock.
2. If a result differs, go to Phase 3.
3. Treat the hooks as active from this point. Claude Code can load a changed `.claude/settings.json` in the running session, and otherwise loads it when the next session starts. In a terminal session the user can type `/hooks` to confirm that the PreToolUse, PostToolUse and Stop entries appear. Project hooks also wait until the user accepts the workspace trust prompt for the folder.

### Step 8. Commit the setup

Commit everything from Phase 1 in 1 commit with the message `Set up verified build loop`. Then tell the user that the next task can start, in this session or in a new one.

---

## Phase 2A: Task loop (quick setup; once per task)

### Plan

1. **Begin with the end.** Before you write code, write the acceptance checks for the task: each command and what its output must show. If no existing test covers the task, the first acceptance check is a new test.
2. **Verify the facts.** Run a command to verify each fact about the code that the plan rests on (a function's signature, a file's format, a library's version). List every fact that you did not verify under "Assumptions".
3. In plan mode, the plan gate denies a plan with no "Acceptance checks" part that names a command, or with no "Assumptions" part. Outside plan mode, put the same 2 parts in the plan that you show the user.

### Build

4. **Tests first.** Write the tests for the task. Run them and confirm that they fail for the right reason (the behaviour is missing), not because the test is broken.
5. **Protect the tests when the user wants that.** Adding a test file to `"protected"` in `.claude/verify.json` stops Claude from weakening it. It also means that only the user can correct a defect in it. Ask the user once for each project which they prefer, and record the answer in CLAUDE.md.
6. **Implement in small steps.** After each step, run the test that covers it. The PostToolUse hook lints each edited file; fix what it reports at once. Do not write the next step on top of a failing one.
7. **Run the fast checks** yourself and fix every failure. Do not wait for the Stop hook to find them.

### Verify and finish

8. **Independent review.** For any change beyond a few lines, ask the `reviewer` subagent to review it. Give it the task as the user stated it, the acceptance checks, and the changed files (`git diff --name-only`). Fix every correctness gap that it reports. Do not act on style comments.
9. Commit. End with an evidence report: each acceptance check, the command that you ran, and the last lines of its output, plus the reviewer's findings and what you did about each one. State what you did not verify.

## Phase 2B: Feature loop (full setup; once per feature, 1 feature per session)

### Startup

1. Read progress.md (newest entry first) and run `git log --oneline -5`.
2. Run `bash init.sh`. If it fails, fix the project before you start new work; a broken start means that the last session ended badly.
3. Pick the first feature in feature_list.json with `"passes": false`. State its ID and description.

### Build

4. **Tests first.** Write tests for the feature, including its edge cases from SPEC.md and an end-to-end test that follows the feature's `steps`. Run them and confirm that they fail for the right reason. Fix every lint error in the test files now.
5. **Protect the tests.** Add each new test file to `"protected"` in `.claude/verify.json`. From then on, only the user can change those tests, so a defect that remains in a test (a typo, a lint error, a wrong expected value) blocks the build until the user unlocks the file.
6. **Implement** in small steps, as in Phase 2A step 6.
7. **Run the fast checks** yourself and fix every failure.

### Verify

8. **Independent review.** Ask the `reviewer` subagent to compare the changed files with SPEC.md for this feature. Give it the feature ID, the changed files (`git diff --name-only`), and the SPEC.md path. Fix every correctness gap that it reports.
9. **Run the full checks**, including the end-to-end test. Fix every failure.
10. **Set `"passes": true`** for this 1 feature only. When you end the turn, the Stop hook runs the fast checks and the full checks. If they fail, the hook sends you back: fix the cause, or set the feature back to `false` if it is not done.

### Finish

11. Commit with a message that names the feature ID.
12. Add an entry to progress.md (use its template).
13. End with an evidence report, as in Phase 2A step 9.
14. Tell the user the next feature ID and to start a new session for it.

---

## Phase 3: Repair

Use this when a hook blocks something that it should allow, allows something that it should block, or reports an internal error, or when a setup file is missing.

1. Run the skill's tests: `python3 -B -m unittest discover -s "${CLAUDE_SKILL_DIR}/tests"`. A failure means that the scripts do not work on this machine; show the user the output.
2. Compare each file in `.claude/hooks/` with the skill folder, using the `cmp` command of Step 6. A difference means that something changed the file, or that the skill was updated; tell the user which. Claude cannot replace these files while the hooks are active, because the hooks protect them. The user runs the `cp` command of Step 6 in a terminal, then runs `python3 .claude/hooks/vbl_common.py relock`.
3. If `.claude/verify.json` is missing, rebuild it from Phase 1, Step 2, and show it to the user before you write it.
4. If `.claude/verify.json` is malformed, the Stop hook names each problem. Fix the file; if a hook blocks the fix, ask the user to fix it.

## What to do when a check cannot pass

- **The code is wrong:** fix the code. That is the normal case.
- **The test is wrong** (it tests something that the user did not ask for, or it has a defect): if the test is protected, stop. Tell the user which test, which line, and why. Only the user can unprotect it, with `python3 .claude/hooks/vbl_common.py unlock <path>`.
- **You changed a protected file by accident** (for example a formatter rewrote it): put it back with `git restore <path>`. The hooks allow that 1 command form.
- **The environment is broken** (a missing dependency, a service that is not running): fix the environment if it is inside the project. Otherwise stop and tell the user exactly what is missing.
- **You must stop to ask the user something while a check fails:** say so plainly in your reply, and say which check fails and why. The Stop hook blocks 2 times and then lets the turn end with a message to the user.
- **The same failure repeats:** after 3 identical failures in a row in 1 turn, the Stop hook lets the turn end and shows the user a message with the failing output. Do not hide this. Explain what you tried.

Never weaken a check to make it pass: no skipped tests, no loosened assertions, no deleted checks, no lint configuration edited to silence a rule.

## User-only commands

The PreToolUse hook blocks Claude from running these. The user runs them in a terminal, in the project root:

- `python3 .claude/hooks/vbl_common.py unlock <path>`: stop protecting 1 entry of the `"protected"` list. Give the entry as the list holds it.
- `python3 .claude/hooks/vbl_common.py relock`: accept the current state of every protected file, check, setting and feature. The next Stop hook run records it.

To change a check or a setting in `.claude/verify.json`, the user edits the file and then runs `relock`.

## What each hook enforces

| Hook | When it runs | What it blocks |
|---|---|---|
| PreToolUse (`protect_paths.py`) | Before every Write, Edit, NotebookEdit and Bash call | Writes to protected files, the hook files, `.claude/settings.json`, the reviewer and the lock; feature-list changes other than `passes` or a new failing feature; verify.json changes other than a new check or a new protected path; Bash commands that name a protected path and also write, move or delete; the user-only commands |
| PreToolUse (`plan_check.py`) | When Claude presents a plan in plan mode | A plan with no "Acceptance checks" part that names a command, or with no "Assumptions" part. The user turns it off with `"plan_gate": false`. |
| PostToolUse (`post_edit_lint.py`) | After every Write and Edit call | Nothing (the edit already happened). It shows the lint errors to Claude. |
| Stop (`stop_check.py`) | Each time Claude tries to end a turn | Ending the turn while: a protected file, a check, a setting or a feature changed against the rules (by any route, scripts included); verify.json is malformed; any fast check fails; or a feature changed to `"passes": true` and any full check fails |

The Stop hook skips the checks when no project file changed since the last passing run. Claude Code itself ends the turn after 8 consecutive blocks with no tool call in between.

## Contingencies

| Situation | What happens | What to do |
|---|---|---|
| The PreToolUse hook blocks a Bash command by mistake (for example `cp tests/test_a.py /tmp/`, or a heredoc whose text mentions a user-only command) | The hook reads the whole command text. It blocks any write-type command that names a protected path, and any command that names a user-only command | Split the command so that the protected path and the write are separate, read the file, or write the text with the Write tool |
| Claude changes a protected file through a route that the PreToolUse hook cannot see (a script, a formatter, `git stash`) | The Stop hook's hash check blocks | Run `git restore <path>`, or ask the user |
| Something deletes the lock, or the session runs in a fresh clone (every cloud session does) | The next Stop hook run treats the project as new: it records the current state and runs the fast checks once | Nothing. In a fresh clone, the committed files are the trusted state. |
| A check reports problems in a protected file | Claude cannot fix the file, so the check fails on every turn | Exclude `.claude/` from checks (Step 2); for a protected test, ask the user to unlock it |
| The fast checks are slow | Every turn that changes a project file waits for them | The user moves slow checks to the full checks (full setup) or narrows them, then runs `relock` |
| A file changes on every tool call (a log, a cache) | If git does not ignore it, the checks run on every turn | Add it to .gitignore |
| An ignored file matters to the checks (for example a local `.env`) | A change to it alone does not rerun the checks | Run the fast checks by hand after you change it |
| The Stop hook reports an internal error | It blocks once, so that Claude tells the user; then it lets the turn end with a message. The checks did not run. | Run the checks by hand; run Phase 3 |
| Python is missing on the machine | The hooks fail; Claude Code treats a failed command hook as a non-blocking error, so the action proceeds unchecked | Install Python 3.8 or later; run Step 7 again |
| The project has other hooks (for example the agent-discipline hooks) | All hooks of an event run; any of them can block | Keep both sets in `.claude/settings.json`. Step 6 merges them. |
| Windows | Tested on Linux. Check commands run through the shell; quoting in `lint_on_edit` uses POSIX rules | Run the Step 7 smoke test before you rely on the hooks |
| A determined workaround | Local hooks cannot stop every workaround by a program that can run code | The reviewer, the git history and the user's review of the diff are the backstop |
| The checks pass and the work is still wrong | Checks prove only what they cover | The reviewer compares with the request; the user tries the result |

## Optional step map to the user's other skills

If the user has these skills, call them at these steps. They are optional; the hooks do not depend on them.

| Step | Skill |
|---|---|
| Phase 1, Step 3 (interview and specification) | `premise-check`, `ask-or-assume`, `unambiguous-language` |
| Phase 2A step 2 (verify the facts) | `premise-check` |
| Phase 2A step 1, Phase 2B step 4 (designing a test that can fail) | `validation-design` |
| A change that touches many files | `scope-and-blast-radius-check` |
| The evidence report | `completion-evidence-gate` |
| A plan or a specification before building | `backward-review-gate` |

## Files in this skill

| File | Goes to | Purpose |
|---|---|---|
| `scripts/vbl_common.py` | `.claude/hooks/` | Shared helpers, and the user-only commands |
| `scripts/stop_check.py` | `.claude/hooks/` | Stop hook |
| `scripts/protect_paths.py` | `.claude/hooks/` | PreToolUse hook for file tools and Bash |
| `scripts/plan_check.py` | `.claude/hooks/` | PreToolUse hook for ExitPlanMode (the plan gate) |
| `scripts/post_edit_lint.py` | `.claude/hooks/` | PostToolUse hook |
| `templates/settings-hooks.json` | merged into `.claude/settings.json` | The 4 hook groups |
| `templates/verify.json` | `.claude/verify.json` | Check configuration, with example commands for a Python project |
| `templates/reviewer.md` | `.claude/agents/reviewer.md` | The reviewer subagent |
| `templates/CLAUDE-section-quick.md`, `templates/CLAUDE-section.md` | a section of CLAUDE.md | Working rules for a quick setup and for a full setup |
| `templates/SPEC.md`, `templates/feature_list.json`, `templates/progress.md`, `templates/init.sh` | project root | Full setup only |
| `tests/test_vbl.py` | stays in the skill | Tests of the 5 scripts; Phase 3 runs them |
