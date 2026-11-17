---
name: "verified-build-loop"
description: "Sets up and repairs an enforced Claude Code build loop: spec and feature list, hooks that block stopping until checks pass and block weakening tests, and a read-only reviewer. Use when the user invokes /verified-build-loop."
---

# Verified build loop

## Purpose

Claude stops when work looks done. This skill makes "done" something a check proves. It installs five layers in a project:

| Layer | What it is | Who controls it |
|---|---|---|
| 1. Definition of done | SPEC.md and feature_list.json | Instruction and file |
| 2. Checks | Test, typecheck, lint, and end-to-end commands in .claude/verify.json | Instruction and file |
| 3. Enforcement hooks | Stop, PreToolUse, and PostToolUse hooks | Claude Code enforces |
| 4. Independent reviewer | Read-only `reviewer` subagent | Fresh context |
| 5. Session discipline | progress.md, init.sh, one feature per session, one commit per feature | Instruction and file |

Claude Code enforces only layer 3. Everything else is an instruction that Claude chooses to follow. That is why layer 3 exists.

## Terms

- **Check**: a command that exits 0 on pass and nonzero on fail.
- **Fast checks**: checks the Stop hook runs each time Claude tries to end a turn after a change (for example, unit tests and typecheck).
- **Full checks**: checks the Stop hook also runs when a feature changes to `"passes": true` (for example, the whole test suite and the end-to-end test).
- **Protected file**: a file Claude may read but never change. Only the user can unprotect it.
- **Lock**: .claude/verify-lock.json. The Stop hook records hashes and snapshots there and compares against them.
- **Evidence report**: the exact commands Claude ran and their output, pasted at the end of a turn.

## When to use each phase

- The project has no .claude/verify.json: run **Phase 1 (Setup)**, then **Phase 2** for the first feature.
- The project has .claude/verify.json: skip to **Phase 2 (Feature loop)**.
- A hook misbehaves or a file is missing: run **Phase 3 (Repair)**.

---

## Phase 1: Setup (once per project)

Do every step in order. Tell the user what each step found before moving to the next step.

### Step 1. Preflight

Run these and report the result of each:

1. `git rev-parse --is-inside-work-tree`. If the folder is not a git repository, ask the user whether to run `git init`. The loop depends on git to restore files and record each feature.
2. `git status --porcelain`. If the tree has uncommitted changes, ask the user whether to commit them first, so setup changes stay separate.
3. `python3 --version`. If that fails, try `python --version`. Use whichever works in every hook command in Step 6. If neither works, stop: the hooks need Python 3.8 or later.
4. Check whether `.claude/settings.json` exists. If it exists, Step 6 merges into it instead of replacing it.
5. Check whether `.claude/verify.json` exists. If it exists, this project already has the loop; go to Phase 3.

### Step 2. Find or build the checks

1. Read the project's build files (for example, package.json, pyproject.toml, Makefile, Cargo.toml, go.mod) and any CI configuration.
2. Propose four commands to the user: fast checks, full checks, lint-on-edit (with a `{file}` placeholder), and an end-to-end test.
3. Exclude the `.claude/` folder from every check (for example, `ruff check . --extend-exclude .claude`, or an `ignorePatterns` entry for ESLint). The hooks protect their own files, so a check that reports on those files can never pass.
4. Run each proposed command once and show the output. A command that cannot run is not a check. Every check must pass on the current code before setup continues. If a check fails now (for example, old lint errors), fix the cause or narrow the command, and get the user's approval for either choice. Otherwise the Stop hook blocks every turn on problems that predate the build.
5. If the project has no tests, build the smallest working test setup first (one passing smoke test), and run it.
6. If the project has a user interface, the end-to-end check drives it the way a person would (for example, Playwright for a web app). Unit tests alone do not prove a feature works.
7. Ask the user to confirm the four commands before writing them anywhere.

Keep fast checks fast. The Stop hook runs them on every turn that changes a file. A suite that takes more than about two minutes belongs in full checks.

### Step 3. Write SPEC.md by interviewing the user

1. Ask the user questions until you could write the spec without guessing. Ask with multiple-choice questions where the tool allows. Cover: purpose, users, every requirement, edge cases for each requirement, what is out of scope, and constraints.
2. Write SPEC.md from the template in the appendix. Number every requirement.
3. Show SPEC.md to the user and get approval before Step 4.

### Step 4. Write feature_list.json

1. Turn each numbered requirement into one or more features. Each feature is small enough to build and test in one session.
2. Give each feature an `id`, a `description`, a `spec_section`, and `steps` that a person follows to test it end to end.
3. Set every feature to `"passes": false`.
4. After setup, the hooks allow only two kinds of change to this file: setting `passes`, and adding a new feature with `"passes": false`. Get every other field right now; once you install the hooks, only the user can change it.

### Step 5. Write progress.md and init.sh

1. Write progress.md from the template.
2. Write init.sh with the project's real install and smoke-check commands. Run `bash init.sh` and confirm it exits 0.

### Step 6. Install the hooks and the reviewer

Write the files in this order. The order matters: once .claude/verify.json exists, the PreToolUse hook protects the other files, so verify.json goes last.

1. **Hook scripts.** Create `.claude/hooks/` and put four files in it: `vbl_common.py`, `stop_check.py`, `protect_paths.py`, `post_edit_lint.py`. If this skill's folder holds a `scripts/` folder, copy the files from there. Otherwise write each file exactly as the appendix gives it, with no changes.
2. **Reviewer.** Write `.claude/agents/reviewer.md` from the appendix.
3. **Settings.** Add the `hooks` block from the appendix to `.claude/settings.json`. If the file exists, merge: keep every existing setting and hook, and append these three hook groups. If Step 1 found `python` instead of `python3`, change the commands to match. Show the user the final file.
4. **verify.json.** Write `.claude/verify.json` with the commands confirmed in Step 2. Leave `"protected": []` for now; Phase 2 fills it as tests get written.
5. **CLAUDE.md.** Add the "Verified build loop" section from the appendix to CLAUDE.md (create the file if needed), with the real check commands filled in. Keep the section short.
6. **.gitignore.** Add `.claude/verify-lock.json` to .gitignore. The lock holds timestamps that differ on each machine; each machine builds its own lock on its first Stop hook run.

### Step 7. Smoke-test the hooks

1. Ask the user to type `/hooks` and confirm that PreToolUse, PostToolUse, and Stop entries appear for this project. If they do not appear, ask the user to restart the Claude Code session and check again. Project hooks also wait until the user accepts the workspace trust prompt for the folder.
2. Run each script by hand with a sample input and show the exit code:
   - `echo '{"tool_name":"Write","tool_input":{"file_path":"'"$PWD"'/.claude/verify-lock.json","content":"{}"}}' | python3 .claude/hooks/protect_paths.py; echo "exit $?"` must print `exit 2`.
   - `echo '{"stop_hook_active":false}' | python3 .claude/hooks/stop_check.py; echo "exit $?"` must print `exit 0` if the fast checks pass. This first run also creates the lock.
3. If either result differs, go to Phase 3.

### Step 8. Commit the setup

Commit everything from Phase 1 in one commit with the message `Set up verified build loop`. Then tell the user to run `/clear` and say "build the next feature."

---

## Phase 2: Feature loop (once per feature, one feature per session)

### Startup
1. Read progress.md (newest entry first) and run `git log --oneline -5`.
2. Run `bash init.sh`. If it fails, fix the project before starting new work; a broken start means the last session ended badly.
3. Pick the first feature in feature_list.json with `"passes": false`. State its ID and description.

### Build
4. **Tests first.** Write tests for the feature, including its edge cases from SPEC.md and an end-to-end test that follows the feature's `steps`. Run them and confirm they fail for the right reason (the feature is missing), not for a broken test. Fix every lint error in the test files now.
5. **Protect the tests.** Add each new test file to `"protected"` in .claude/verify.json. From then on, nobody but the user can change those tests, so a defect that remains in a test at this point (a typo, a lint error, a wrong expected value) blocks the build until the user unlocks it.
6. **Implement.** Write the code. The PostToolUse hook lints each edited file; fix what it reports right away.
7. **Run the fast checks** yourself and fix every failure. Do not wait for the Stop hook to find them.

### Verify
8. **Independent review.** Ask the `reviewer` subagent to compare the changed files with SPEC.md for this feature. Give it the feature ID, the changed files (`git diff --name-only`), and the SPEC.md path. Fix every correctness gap it reports. Do not act on style comments.
9. **Run the full checks**, including the end-to-end test. Fix every failure.
10. **Set `"passes": true`** for this one feature only. When you end the turn, the Stop hook runs the full checks again. If they fail, the hook sends you back: fix the cause, or set the feature back to `false` if it is not done.

### Finish
11. Commit with a message that names the feature ID.
12. Add an entry to progress.md (use the template).
13. End with an evidence report: each command you ran in steps 7 through 10 and the last lines of its output, plus the reviewer's findings and what you did about each one.
14. Tell the user the next feature ID and to run `/clear` before starting it.

---

## Phase 3: Repair

Use this when a hook blocks something it should allow, allows something it should block, or a setup file is missing.

1. Run `python3 -m unittest -v` on the skill's tests if the skill folder holds a `tests/` folder.
2. Compare each file in `.claude/hooks/` with the appendix or the skill's `scripts/` folder. A difference means something changed the file; tell the user. Claude cannot replace these files itself while the hooks are active, because the hooks protect them. The user replaces them, then runs `python3 .claude/hooks/vbl_common.py relock`.
3. If .claude/verify.json is missing, rebuild it from Phase 1, Step 2, and show it to the user before writing it.

---

## What to do when a check cannot pass

- **The code is wrong:** fix the code. That is the normal case.
- **The test is wrong** (it tests something SPEC.md does not require, or it has a defect): stop. Tell the user which test, which line, and why. Only the user can unprotect it, with `python3 .claude/hooks/vbl_common.py unlock <path>`.
- **The environment is broken** (a missing dependency, a service that is not running): fix the environment if it is inside the project. Otherwise stop and tell the user exactly what is missing.
- **The same failure repeats:** after three identical failures in a row with no change, the Stop hook lets the turn end and shows the user a message with the failing output. Do not hide this. Explain what you tried.

Never weaken a check to make it pass: no skipping tests, no loosening assertions, no deleting checks, no editing lint configuration to silence a rule.

## User-only commands

The PreToolUse hook blocks Claude from running these. The user runs them in a terminal:

- `python3 .claude/hooks/vbl_common.py unlock <path>`: stop protecting one file.
- `python3 .claude/hooks/vbl_common.py relock`: accept the current state of every protected file, check, and feature. The next Stop hook run records it.

## What each hook enforces

| Hook | When it runs | What it blocks |
|---|---|---|
| PreToolUse (`protect_paths.py`) | Before every Write, Edit, MultiEdit, NotebookEdit, and Bash call | Writes to protected files, the hook files, `.claude/settings.json`, the reviewer, and the lock; feature-list changes other than `passes` or a new failing feature; verify.json changes that remove or change a check, a protected path, or a setting; Bash commands that name a protected path and also write, move, or delete; the user-only commands |
| PostToolUse (`post_edit_lint.py`) | After every Write, Edit, and MultiEdit call | Nothing (the edit already happened). Shows lint errors to Claude. |
| Stop (`stop_check.py`) | Each time Claude tries to end a turn | Ending the turn while: a protected file, a check, or a feature changed against the rules (by any route, including scripts); any fast check fails; or a feature changed to `"passes": true` and any full check fails |

The Stop hook skips the checks when no project file changed since the last passing run. Claude Code ends the turn anyway after eight consecutive blocks with no tool call in between.

## Contingencies

| Situation | What happens | What to do |
|---|---|---|
| The PreToolUse hook blocks a Bash command by mistake (for example, `cp tests/test_a.py /tmp/`) | The PreToolUse heuristic blocks any write-type command that names a protected path | Split the command so the protected path and the write are separate, or read the file instead |
| Claude changes a protected file through a route the PreToolUse hook cannot see (a script, `git stash`, `git reset`) | The Stop hook's hash check catches it and blocks | Restore the file with git, or ask the user |
| Something deletes the lock file | The next Stop hook run treats the project as new and records the current state | The user should check `git diff` for protected files; the hooks block Claude from deleting the lock through file tools and recognized Bash commands |
| A check reports problems in a protected file (a hook script, or a locked test) | Claude cannot fix the file, so the check fails on every turn | Exclude `.claude/` from checks (Setup, Step 2); for a locked test, stop and ask the user to unlock it |
| Fast checks are slow | Every turn that changes a file waits for them | Move slow checks to full checks; the user edits verify.json (Claude may only add checks) |
| Python is missing on the machine | Hooks fail; Claude Code treats a failed command hook as a non-blocking error, so the action proceeds without the check | Install Python 3.8 or later; run Phase 1, Step 7 again |
| Windows | Tested on Linux. Quoting in `lint_on_edit` uses POSIX rules | Run the Step 7 smoke test before relying on the hooks |
| A determined workaround | Local hooks cannot stop every possible workaround by a program that can run code | The reviewer, the git history, and the user's review of the diff are the backstop |
| Checks pass but the feature is wrong | Checks prove only what they cover | The reviewer compares with SPEC.md; the user tries the feature |

## Optional step map to the user's other skills

If the user has these skills, call them at these steps. They are optional instructions; the hooks do not depend on them.

| Step | Skill |
|---|---|
| Phase 1, Step 3 (interview and spec) | `premise-check`, `ask-or-assume`, `unambiguous-language` |
| Phase 2, step 4 (designing the end-to-end test) | `validation-design` |
| Phase 2, step 6, when a change touches many files | `scope-and-blast-radius-check` |
| Phase 2, step 13 (evidence report) | `completion-evidence-gate` |
| Reviewing SPEC.md or a plan before building | `backward-review-gate` |

## Settings that help

- Use `/effort high` for feature work. Save `max` for a hard problem Claude works through alone.
- Use `/rename <project>-<feature>` and `claude --resume` to pick up multi-day work.
- After two failed corrections of the same problem, run `/clear` and write one better prompt.

---

## Appendix: file contents

Write these files exactly as shown when the skill folder has no `scripts/` or `templates/` folder.

### A.1 SPEC.md (project root)

```markdown
# Specification: <project name>

## 1. Purpose
One paragraph: who uses this, and what problem it solves.

## 2. Requirements
Number every requirement so a feature can cite it (for example, "2.1").

### 2.1 <requirement name>
- What the user does:
- What the system does in response:
- Edge cases this requirement must handle:
- How to test it end to end:

## 3. Out of scope
List what this project does not do, so the build does not drift.

## 4. Constraints
Languages, libraries, data rules, performance limits, and anything else the build must respect.

## 5. Definition of done
The project is done when every feature in feature_list.json has "passes": true and the full checks pass.
```

### A.2 feature_list.json (project root)

```json
{
  "features": [
    {
      "id": "F001",
      "description": "One sentence that states what the user can do when this feature works.",
      "spec_section": "SPEC.md section 2.1",
      "steps": [
        "First thing a person does to test the feature end to end",
        "What the person sees when the feature works"
      ],
      "passes": false
    }
  ]
}
```

### A.3 progress.md (project root)

```markdown
# Progress log

Newest entry first. Each session adds one entry when it ends.

## Session template
- Date:
- Feature worked on (ID):
- Result: passes / still failing (state why)
- Commits:
- Evidence: commands run and their result
- Open problems for the next session:
- Next feature to build (ID):
```

### A.4 init.sh (project root)

```bash
#!/usr/bin/env bash
# Startup routine for each session: install dependencies, then run a quick smoke check.
# Setup replaces these lines with the project's real commands.
set -euo pipefail
cd "$(dirname "$0")"
echo "== install =="
# example: python3 -m pip install -r requirements.txt
echo "== smoke check =="
# example: python3 -m pytest -x -q tests/test_smoke.py
echo "init.sh finished"
```

### A.5 .claude/verify.json (example for a Python project; use the commands confirmed in Setup, Step 2)

```json
{
  "fast_checks": [
    { "name": "unit", "command": "python3 -m pytest -x -q", "timeout_seconds": 600 }
  ],
  "full_checks": [
    { "name": "all-tests", "command": "python3 -m pytest -q", "timeout_seconds": 1200 }
  ],
  "lint_on_edit": { "command": "ruff check {file}", "extensions": [".py"], "timeout_seconds": 120 },
  "protected": [],
  "feature_list": "feature_list.json",
  "fingerprint_exclude": []
}
```

### A.6 hooks block for .claude/settings.json

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash",
        "hooks": [
          { "type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/protect_paths.py\"", "timeout": 30 }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          { "type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/post_edit_lint.py\"", "timeout": 180 }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/stop_check.py\"", "timeout": 1800 }
        ]
      }
    ]
  }
}
```

### A.7 .claude/agents/reviewer.md

```markdown
---
name: reviewer
description: Reviews changed files against SPEC.md and the feature being built. Use after implementing a feature and before setting "passes" to true.
tools: Read, Grep, Glob
---
You are reviewing code you did not write. You did not see the conversation that produced it.

Input you receive: a feature ID, the list of changed files, and the path to SPEC.md.

Do this:
1. Read the feature's entry in feature_list.json and the SPEC.md sections it cites.
2. Read every changed file and the tests for the feature.
3. For each requirement and each listed edge case, decide whether the code implements it and whether a test exercises it.
4. Look for correctness defects: wrong logic, unhandled errors, off-by-one errors, missing input validation, state that can become inconsistent, and tests that pass without testing the requirement.

Report only gaps that affect correctness or a requirement. Skip style, naming, and formatting.
For each gap, give: the file and line, the requirement it breaks, and a one-sentence description of a failing input or scenario.
If you find no gap, say "No correctness gaps found" and list what you checked.
```

### A.8 section to add to CLAUDE.md

```markdown
## Verified build loop
This project uses verified-build-loop. Hooks enforce the checks; these lines say how to work.
- Start every session: read progress.md, run `git log --oneline -5`, run `bash init.sh`.
- Build one feature per session: the first feature in feature_list.json with "passes": false.
- Write the feature's tests first, confirm they fail for the right reason, then add them to "protected" in .claude/verify.json.
- After implementing, have the `reviewer` subagent compare the changes with SPEC.md. Fix correctness gaps; skip style.
- Set "passes": true only after the full checks pass. The Stop hook reruns them.
- Finish with a commit, a progress.md entry, and an evidence report (commands run and their output). Then tell the user to run /clear.
- Never change a protected file, a check in verify.json, or a feature's fields other than "passes". If one is wrong, stop and ask the user.
- Check commands: <fast checks>; <full checks>; <lint>.
```

### A.9 .claude/hooks/vbl_common.py

```python
#!/usr/bin/env python3
"""Shared helpers for the verified-build-loop hooks.

Standard library only. Python 3.8 or later.

The hooks read two files in the project:
  .claude/verify.json       the check configuration (Claude may add to it, never remove)
  .claude/verify-lock.json  the integrity record (only the Stop hook and the user write it)

User-only commands (run these yourself in a terminal; the PreToolUse hook blocks Claude from running them):
  python3 .claude/hooks/vbl_common.py unlock <path>   stop protecting one file
  python3 .claude/hooks/vbl_common.py relock          accept the current state of every protected file
"""

import fnmatch
import hashlib
import json
import os
import subprocess
import sys

CONFIG_REL = ".claude/verify.json"
LOCK_REL = ".claude/verify-lock.json"

# Paths that Claude may never change through a file tool or a Bash command.
ALWAYS_PROTECTED = [
    ".claude/verify-lock.json",
    ".claude/hooks/*",
    ".claude/settings.json",
    ".claude/agents/reviewer.md",
]

OUTPUT_TAIL_LINES = 150


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def project_dir(hook_input=None):
    """Return the absolute project root."""
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root and hook_input:
        root = hook_input.get("cwd")
    return os.path.abspath(root or os.getcwd())


def rel_path(root, path):
    """Return path relative to root with forward slashes, or None if outside root."""
    if not path:
        return None
    absolute = os.path.abspath(path if os.path.isabs(path) else os.path.join(root, path))
    try:
        relative = os.path.relpath(absolute, root)
    except ValueError:  # different drive on Windows
        return None
    if relative == ".." or relative.startswith(".." + os.sep):
        return None
    return relative.replace(os.sep, "/")


def matches_any(relative, patterns):
    """True if relative matches a pattern. A pattern ending in '/' covers that whole folder.
    In fnmatch, '*' also matches '/', so 'tests/*' covers nested folders."""
    for pattern in patterns:
        pattern = pattern.replace("\\", "/")
        if pattern.startswith("./"):
            pattern = pattern[2:]
        if pattern.endswith("/"):
            if relative.startswith(pattern):
                return True
        elif fnmatch.fnmatchcase(relative, pattern):
            return True
    return False


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except FileNotFoundError:
        return None


def load_json_file(path):
    """Return (data, error). data is None when the file does not exist."""
    text = read_text(path)
    if text is None:
        return None, None
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, "{} is not valid JSON: {}".format(path, exc)


def write_json_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temp_path, path)


def sha256_file(path):
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
    except FileNotFoundError:
        return None
    return digest.hexdigest()


def load_config(root):
    """Return (config, error). config is None when the project has no verify.json."""
    return load_json_file(os.path.join(root, CONFIG_REL))


def protected_patterns(config):
    patterns = list(ALWAYS_PROTECTED)
    if config:
        patterns.extend(config.get("protected", []))
    return patterns


def feature_list_rel(config):
    return (config or {}).get("feature_list", "feature_list.json")


# ---------------------------------------------------------------------------
# Change rules
# ---------------------------------------------------------------------------

def _features_by_id(data):
    features = (data or {}).get("features")
    if not isinstance(features, list):
        return None, "feature list must hold a 'features' array"
    by_id = {}
    for feature in features:
        if not isinstance(feature, dict) or "id" not in feature:
            return None, "every feature needs an 'id'"
        if feature["id"] in by_id:
            return None, "feature id {} appears twice".format(feature["id"])
        by_id[feature["id"]] = feature
    return by_id, None


def feature_list_violations(old_data, new_data):
    """Rules: keep every old feature; change no field except 'passes'; add new features only with passes false."""
    if old_data is None:
        return []
    old, error = _features_by_id(old_data)
    if error:
        return []  # the old file was already malformed; do not block repairs
    new, error = _features_by_id(new_data)
    if error:
        return [error]
    problems = []
    for feature_id, old_feature in old.items():
        new_feature = new.get(feature_id)
        if new_feature is None:
            problems.append("feature {} was removed".format(feature_id))
            continue
        old_rest = {k: v for k, v in old_feature.items() if k != "passes"}
        new_rest = {k: v for k, v in new_feature.items() if k != "passes"}
        if old_rest != new_rest:
            problems.append("feature {} changed a field other than 'passes'".format(feature_id))
    for feature_id, new_feature in new.items():
        if feature_id not in old and new_feature.get("passes") is not False:
            problems.append("new feature {} must start with \"passes\": false".format(feature_id))
    return problems


def _checks_by_name(config, key):
    return {check.get("name"): check for check in (config or {}).get(key, []) if isinstance(check, dict)}


def config_violations(old_config, new_config):
    """Rules: keep every old check unchanged; keep every protected path; keep lint and feature-list settings."""
    if old_config is None:
        return []
    if not isinstance(new_config, dict):
        return ["verify.json must hold a JSON object"]
    problems = []
    for key in ("fast_checks", "full_checks"):
        old_checks = _checks_by_name(old_config, key)
        new_checks = _checks_by_name(new_config, key)
        for name, check in old_checks.items():
            if new_checks.get(name) != check:
                problems.append("{} check '{}' was removed or changed".format(key, name))
    removed = set(old_config.get("protected", [])) - set(new_config.get("protected", []))
    for path in sorted(removed):
        problems.append("protected path '{}' was removed".format(path))
    for key in ("lint_on_edit", "feature_list"):
        if key in old_config and new_config.get(key) != old_config.get(key):
            problems.append("setting '{}' was changed".format(key))
    return problems


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def tail(text, lines=OUTPUT_TAIL_LINES):
    parts = (text or "").rstrip().splitlines()
    if len(parts) <= lines:
        return "\n".join(parts)
    return "[... {} earlier lines cut ...]\n".format(len(parts) - lines) + "\n".join(parts[-lines:])


def run_check(root, check):
    """Run one check. Return (passed, report_text)."""
    name = check.get("name", "unnamed check")
    command = check.get("command")
    if not command:
        return False, "Check '{}' has no command.".format(name)
    timeout = int(check.get("timeout_seconds", 600))
    try:
        result = subprocess.run(
            command, shell=True, cwd=root, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, "Check '{}' timed out after {} seconds: {}".format(name, timeout, command)
    if result.returncode == 0:
        return True, ""
    output = tail((result.stdout or "") + "\n" + (result.stderr or ""))
    return False, "Check '{}' failed (exit {}): {}\n{}".format(name, result.returncode, command, output)


# ---------------------------------------------------------------------------
# Hook input and output
# ---------------------------------------------------------------------------

def read_hook_input():
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def block(message):
    """Exit code 2: Claude Code shows stderr to Claude and blocks the action or the stop."""
    sys.stderr.write(message.rstrip() + "\n")
    sys.exit(2)


# ---------------------------------------------------------------------------
# User-only commands
# ---------------------------------------------------------------------------

def _user_unlock(root, target):
    config, error = load_config(root)
    if error or config is None:
        print(error or "No .claude/verify.json in this project.")
        return 1
    relative = rel_path(root, target) or target
    config["protected"] = [p for p in config.get("protected", []) if p != relative]
    write_json_file(os.path.join(root, CONFIG_REL), config)
    lock, _ = load_json_file(os.path.join(root, LOCK_REL))
    if lock:
        lock.get("hashes", {}).pop(relative, None)
        lock["config_snapshot"] = config
        write_json_file(os.path.join(root, LOCK_REL), lock)
    print("Unprotected {}.".format(relative))
    return 0


def _user_relock(root):
    lock_path = os.path.join(root, LOCK_REL)
    if os.path.exists(lock_path):
        os.remove(lock_path)
    print("Removed the lock. The next Stop hook run records the current state of every protected file.")
    return 0


def main(argv):
    root = project_dir()
    if len(argv) == 3 and argv[1] == "unlock":
        return _user_unlock(root, argv[2])
    if len(argv) == 2 and argv[1] == "relock":
        return _user_relock(root)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

### A.10 .claude/hooks/stop_check.py

```python
#!/usr/bin/env python3
"""Stop hook for verified-build-loop.

Runs each time Claude tries to end its turn. In order:
  1. Integrity: confirms that no protected file, check, or feature changed against the rules.
  2. Skip: if nothing in the project changed since the last passing run, lets Claude stop.
  3. Fast checks: runs every command in verify.json "fast_checks".
  4. Full checks: also runs "full_checks" when a feature changed to "passes": true.
On any failure, exits with code 2 so Claude Code sends the report back to Claude.
"""

import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vbl_common as vbl  # noqa: E402

EXCLUDED_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", "dist", "build", ".next", "target", ".idea", ".vscode",
}
REPEAT_LIMIT = 3  # identical failures in a row, while already continuing, before the hook lets Claude stop
DURATION = re.compile(r"\b\d+(?:\.\d+)?\s*(?:ms|s|sec|secs|seconds)\b")


def project_files(root, extra_excludes):
    """Yield relative paths of project files, skipping dependency and cache folders."""
    excluded = EXCLUDED_DIRS | set(extra_excludes)
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in excluded)
        for name in sorted(files):
            yield vbl.rel_path(root, os.path.join(current, name))


def fingerprint(root, extra_excludes):
    digest = hashlib.sha256()
    for relative in project_files(root, extra_excludes):
        if relative == vbl.LOCK_REL or relative.endswith(".tmp"):
            continue
        try:
            info = os.stat(os.path.join(root, relative))
        except OSError:
            continue
        digest.update("{}|{}|{}\n".format(relative, info.st_size, info.st_mtime_ns).encode("utf-8"))
    return digest.hexdigest()


def check_protected_hashes(root, config, lock):
    """Compare protected files with the lock. Record files protected for the first time."""
    problems = []
    hashes = lock.setdefault("hashes", {})
    patterns = vbl.protected_patterns(config)
    seen = set()
    for relative in project_files(root, config.get("fingerprint_exclude", [])):
        if relative == vbl.LOCK_REL or not vbl.matches_any(relative, patterns):
            continue
        seen.add(relative)
        current = vbl.sha256_file(os.path.join(root, relative))
        recorded = hashes.get(relative)
        if recorded is None:
            hashes[relative] = current
        elif recorded != current:
            problems.append("protected file '{}' changed".format(relative))
    for relative in sorted(set(hashes) - seen):
        problems.append("protected file '{}' is missing".format(relative))
    return problems


def newly_passed(old_features, new_features):
    old = {f.get("id"): f.get("passes") for f in (old_features or {}).get("features", []) if isinstance(f, dict)}
    return sorted(
        f.get("id") for f in (new_features or {}).get("features", [])
        if isinstance(f, dict) and f.get("passes") is True and old.get(f.get("id")) is not True
    )


def main():
    hook_input = vbl.read_hook_input()
    root = vbl.project_dir(hook_input)
    config, error = vbl.load_config(root)
    if error:
        vbl.block("verified-build-loop: " + error + "\nFix the JSON in .claude/verify.json.")
    if config is None:
        return 0  # project not set up for verified-build-loop

    lock_path = os.path.join(root, vbl.LOCK_REL)
    lock, lock_error = vbl.load_json_file(lock_path)
    if lock_error:
        vbl.block("verified-build-loop: the lock file is not valid JSON. Ask the user to run: "
                  "python3 .claude/hooks/vbl_common.py relock")

    feature_path = os.path.join(root, vbl.feature_list_rel(config))
    features, feature_error = vbl.load_json_file(feature_path)
    if feature_error:
        vbl.block("verified-build-loop: " + feature_error)

    first_run = lock is None
    if first_run:
        lock = {"config_snapshot": config, "feature_snapshot": features, "hashes": {}}

    # 1. Integrity
    problems = []
    problems += vbl.config_violations(lock.get("config_snapshot"), config)
    problems += vbl.feature_list_violations(lock.get("feature_snapshot"), features)
    problems += check_protected_hashes(root, config, lock)
    if problems:
        vbl.block(
            "verified-build-loop integrity check failed:\n- " + "\n- ".join(problems) +
            "\nRestore the original content (for example with git), or stop and ask the user. "
            "Only the user can unprotect a file or accept a change to a protected file."
        )

    # 2. Skip when nothing changed since the last passing run
    excludes = config.get("fingerprint_exclude", [])
    passed_now = newly_passed(lock.get("feature_snapshot"), features)
    lock["config_snapshot"] = config
    if not first_run and not passed_now and lock.get("last_pass_fingerprint") == fingerprint(root, excludes):
        vbl.write_json_file(lock_path, lock)
        return 0

    # 3 and 4. Run checks
    checks = list(config.get("fast_checks", []))
    if passed_now:
        checks += list(config.get("full_checks", []))
    failures = []
    for check in checks:
        passed, report = vbl.run_check(root, check)
        if not passed:
            failures.append(report)

    if failures:
        report = "\n\n".join(failures)
        # Durations such as "in 0.08s" differ on every run; drop them so identical failures match.
        stable = DURATION.sub("", report)
        signature = hashlib.sha256(stable.encode("utf-8")).hexdigest()
        repeats = lock.get("failure_repeats", 0) + 1 if lock.get("last_failure") == signature else 1
        lock["last_failure"] = signature
        lock["failure_repeats"] = repeats
        vbl.write_json_file(lock_path, lock)  # feature_snapshot stays old, so the full checks run again next time
        if hook_input.get("stop_hook_active") and repeats >= REPEAT_LIMIT:
            print(json.dumps({"systemMessage":
                "verified-build-loop: the same checks failed {} times in a row with no change. "
                "Claude stopped without passing them. Failing output:\n{}".format(repeats, vbl.tail(report, 40))}))
            return 0
        header = "verified-build-loop: checks failed. Fix the cause, then finish your turn again."
        if passed_now:
            header += ("\nYou set \"passes\": true on {}. The full checks must pass first; "
                       "if the feature is not done, set it back to false.".format(", ".join(passed_now)))
        vbl.block(header + "\n\n" + report)

    lock["feature_snapshot"] = features
    lock["last_failure"] = None
    lock["failure_repeats"] = 0
    lock["last_pass_fingerprint"] = fingerprint(root, excludes)
    vbl.write_json_file(lock_path, lock)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### A.11 .claude/hooks/protect_paths.py

```python
#!/usr/bin/env python3
"""PreToolUse hook for verified-build-loop.

Runs before Claude writes, edits, or runs a Bash command. Blocks (exit code 2):
  - any write to a protected path (verify.json "protected" plus the hook files, settings, and lock);
  - a change to the feature list other than flipping "passes" or adding a new failing feature;
  - a change to verify.json that removes or alters a check, a protected path, or a setting;
  - a Bash command that names a protected path and also writes, moves, or deletes files;
  - a Bash command that runs the user-only unlock or relock commands.
The Bash rule is a heuristic. The Stop hook's integrity check is the backstop.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vbl_common as vbl  # noqa: E402

FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
WRITE_COMMAND = re.compile(
    r"(^|[\s;&|(`])("
    r"rm|mv|cp|tee|truncate|dd|ln|install|rsync|chmod|unlink|shred|"
    r"sed\s+(?:-[^\s]*\s+)*-i|perl\s+(?:-[^\s]*\s+)*-[^\s]*i|"
    r"git\s+(?:checkout|restore|rm|mv|reset|stash|apply|clean)|"
    r"python3?\s+-c|node\s+-e|ruby\s+-e"
    r")\b"
)
REDIRECT_TARGET = re.compile(r"(?:^|[^<>&\d])\d*>>?\s*([^\s;&|<>()]+)")
SAFE_TARGETS = {"/dev/null", "/dev/stderr", "/dev/stdout"}


def new_content_after(tool_name, tool_input, old_text):
    """Return the file text the tool would produce, or None if it cannot be worked out."""
    if tool_name == "Write":
        return tool_input.get("content", "")
    edits = []
    if tool_name == "Edit":
        edits = [tool_input]
    elif tool_name == "MultiEdit":
        edits = tool_input.get("edits", [])
    else:
        return None
    text = old_text or ""
    for edit in edits:
        old_string = edit.get("old_string", "")
        new_string = edit.get("new_string", "")
        if old_string not in text:
            return None  # the tool call itself will fail
        text = text.replace(old_string, new_string) if edit.get("replace_all") else text.replace(old_string, new_string, 1)
    return text


def json_rule_problems(relative, config, tool_name, tool_input, root):
    """Apply the feature-list and verify.json rules to a proposed file change."""
    is_feature_list = relative == vbl.feature_list_rel(config)
    is_config = relative == vbl.CONFIG_REL
    if not (is_feature_list or is_config):
        return []
    old_text = vbl.read_text(os.path.join(root, relative))
    if old_text is None:
        return []  # creating the file is allowed
    new_text = new_content_after(tool_name, tool_input, old_text)
    if new_text is None:
        if tool_name == "NotebookEdit":
            return ["edit {} with Edit or Write, not NotebookEdit".format(relative)]
        return []
    try:
        old_data = json.loads(old_text)
    except json.JSONDecodeError:
        return []  # the old file was already broken; let Claude repair it
    try:
        new_data = json.loads(new_text)
    except json.JSONDecodeError as exc:
        return ["the new {} would not be valid JSON: {}".format(relative, exc)]
    if is_feature_list:
        return vbl.feature_list_violations(old_data, new_data)
    return vbl.config_violations(old_data, new_data)


def check_file_tool(root, config, tool_name, tool_input):
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    relative = vbl.rel_path(root, path)
    if relative is None:
        return []
    if vbl.matches_any(relative, vbl.protected_patterns(config)):
        return ["'{}' is protected. Only the user can change it.".format(relative)]
    return json_rule_problems(relative, config, tool_name, tool_input, root)


PATH_TOKEN = re.compile(r"[^\s;&|<>()'\"`=]+")


def is_guarded(root, config, token):
    relative = vbl.rel_path(root, token)
    if not relative or relative == ".":
        return None
    guarded = vbl.protected_patterns(config) + [vbl.CONFIG_REL, vbl.feature_list_rel(config)]
    if vbl.matches_any(relative, guarded):
        return relative
    # a folder that holds a protected file, such as "rm -r tests" when "tests/*" is protected
    for pattern in guarded:
        if pattern.startswith(relative.rstrip("/") + "/"):
            return relative
    return None


def check_bash(root, config, command):
    if "vbl_common.py" in command and re.search(r"\b(unlock|relock)\b", command):
        return ["unlock and relock are user-only commands. Ask the user to run them."]
    problems = []
    for target in REDIRECT_TARGET.findall(command):
        if target in SAFE_TARGETS:
            continue
        relative = is_guarded(root, config, target)
        if relative:
            problems.append("the command writes to '{}' with a redirect".format(relative))
    if WRITE_COMMAND.search(command):
        named = []
        for token in PATH_TOKEN.findall(command):
            relative = is_guarded(root, config, token)
            if relative and relative not in named:
                named.append(relative)
        for relative in named:
            problems.append("the command names '{}' and also writes, moves, or deletes files".format(relative))
    return problems


def main():
    hook_input = vbl.read_hook_input()
    root = vbl.project_dir(hook_input)
    config, error = vbl.load_config(root)
    if error or config is None:
        return 0  # not set up, or broken config that the Stop hook reports
    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input") or {}
    if tool_name in FILE_TOOLS:
        problems = check_file_tool(root, config, tool_name, tool_input)
    elif tool_name == "Bash":
        problems = check_bash(root, config, tool_input.get("command", ""))
    else:
        problems = []
    if problems:
        vbl.block("verified-build-loop blocked this action:\n- " + "\n- ".join(problems) +
                  "\nIf the change is necessary, stop and ask the user. "
                  "If a Bash command was blocked by mistake, split it so the protected path and the write are separate commands.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### A.12 .claude/hooks/post_edit_lint.py

```python
#!/usr/bin/env python3
"""PostToolUse hook for verified-build-loop.

Runs right after Claude writes or edits a file. If verify.json sets "lint_on_edit" and the
file has one of its extensions, runs the lint command on that file. On lint errors, exits
with code 2 so Claude Code shows the errors to Claude. (The edit has already happened;
this hook reports, it does not undo.)
"""

import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vbl_common as vbl  # noqa: E402


def main():
    hook_input = vbl.read_hook_input()
    root = vbl.project_dir(hook_input)
    config, error = vbl.load_config(root)
    if error or not config or not config.get("lint_on_edit"):
        return 0
    lint = config["lint_on_edit"]
    tool_input = hook_input.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    relative = vbl.rel_path(root, path)
    if not relative or not os.path.isfile(os.path.join(root, relative)):
        return 0
    extensions = lint.get("extensions", [])
    if extensions and os.path.splitext(relative)[1] not in extensions:
        return 0
    command = lint.get("command", "").replace("{file}", shlex.quote(relative))
    passed, report = vbl.run_check(root, {
        "name": "lint " + relative,
        "command": command,
        "timeout_seconds": lint.get("timeout_seconds", 120),
    })
    if not passed:
        vbl.block("verified-build-loop: lint errors in the file you just edited. Fix them now.\n" + report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```