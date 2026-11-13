---
name: test-impact-selector
description: "Map changed files to the tests that cover them, run that subset first, and report which tests you skipped and why. Use when you run tests after an edit, when the full suite is slow or noisy, or before you report that tests pass. Run the full suite when shared or configuration code changed."
compatibility: "Works in claude.ai, Claude Code and the Skills API. The bundled CLI needs Python 3.8 or later (standard library only). Enforcement hooks are optional and exist only in the Claude Code plugin form."
metadata:
  version: "2.1.0"
allowed-tools: 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" test-impact *)'
---
# Test impact selector

Running the full suite after every edit is slow and fills the context with passing output. Running no tests, or the wrong ones, lets a false "tests pass" through. This skill maps the changed files to the tests that cover them, runs that subset first, and states what was skipped.

## When to use
- You edited code and are about to run tests.
- The full suite takes long or prints a lot.
- You are about to report a test result.

## When not to use
- You are writing the completion claim itself. Use completion-evidence-gate, if installed.
- The user asked for the full suite. Run the full suite.

## Procedure
1. Get the mapping (see Tooling). Read the keys `run`, `full_suite_reason`, `unmapped` and `advice`.
2. Run the tests in `run` with the narrowest invocation, for example `pytest tests/test_parser.py -q`, `jest PATH -t NAME` or `go test ./pkg/parser/...`.
3. Say what you ran and what you skipped (see Output).
4. Run the full suite when `full_suite_reason` is set, before you open a pull request, or when the user asks.
5. On a failure, read only the failure block. Fix the cause, re-run the single failing test, then re-run the subset.
6. If `unmapped` lists a changed source file, say that no test maps to it. Then write a test, or say why none is needed.
7. If `advice` says that no changes were detected, check that you are in the right repository before you do anything else.

## Output
```
Ran 2 of 41 test files (impacted by src/parser.py): 14 passed, exit 0.
Skipped 39; full suite deferred until before the pull request.
No test maps to src/cli_flags.py; added tests/test_cli_flags.py.
```

## Rules
- Do not report "tests pass" for tests you did not run. Name the subset.
- The mapping is a heuristic by file name and by reference. A test file maps to a source file when its name contains the source file's name, or when its content mentions that name. Read `run` critically, and add a test you know is relevant.
- A flaky failure is a failure until you show otherwise. Show the test passing on a re-run and name the cause of the first failure.
- Keep the exit code when you shorten long test output. A pipe reports the exit code of its last command, so `pytest | tail` reports success for a failing run. Use this form:

```
pytest tests/test_parser.py -q > test.log 2>&1; echo "exit=$?"; tail -50 test.log
```

- If context-budget-governor is installed, its `trim` sub-command can shorten `test.log` and keep the failures.

## Tooling
Run the bundled CLI from any working directory:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" <sub-command>
```

`${CLAUDE_SKILL_DIR}` is the directory that contains this SKILL.md. Claude Code fills it in. If the placeholder appears unfilled, replace it with that directory's absolute path. State lives in `.agent/` at the repository root (override with `AGENT_STATE_DIR`).

- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" test-impact` maps the uncommitted changes (staged, unstaged and untracked files). It prints the result and exits 2 outside a git repository.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" test-impact --base main` also includes the commits on this branch since `main`.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" test-impact --root DIR` reads the repository at DIR.

The output keys:

| Key | Meaning |
|---|---|
| `run` | the test files to run first |
| `full_suite_reason` | set when a shared or configuration file changed; run the full suite |
| `unmapped` | changed source files with no matching test |
| `skipped_count` | the number of test files not in `run` |
| `total_tests` | the number of test files found |
| `advice` | one sentence on what to do next |

## Without a shell
List the files you changed. For each one, name the test file that covers it, by file name or by a search for the changed function. Ask the user to run those tests and to paste the result line. Report the subset by name.

## Enforcement (optional)
No hook backs this skill. It is advisory on every host.

## Related skills
- completion-evidence-gate: the evidence block for the claim that tests pass.
- narrow-read-discipline: reading only the failure block of a long log.
