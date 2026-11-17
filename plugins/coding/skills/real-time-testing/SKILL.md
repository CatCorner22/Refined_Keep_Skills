---
name: real-time-testing
description: "Test code continuously while writing it: red-green-refactor, watch mode, typecheck and lint after every slice, and never report done without fresh command output. Use when implementing features, fixing bugs, or when the user asks for TDD, test as you go, verify while coding, or real-time testing. Scope boundary: full browser/product verification after the feature works → `verification`; Playwright CLI mechanics → `playwright-cli`; Adobe Jest patterns → `appbuilder-testing`; CI loop on a PR → `loop-on-ci`/`fix-ci`."
metadata:
  version: "2.0.0"
  source: "CatCorner22/Cursor_Skills@5cf5106 skills/coding/real-time-testing"
---
# Real-time testing

**Rule:** Code is not written in bulk and tested at the end. Every meaningful edit is followed by the **narrowest command that proves the edit**, before the next edit.

This skill **tests itself in real time** — you run commands, read output, fix, re-run. No "should pass" without evidence.

## The loop (mandatory)

```
1. Define the next smallest behavior (from deliverable-first checklist)
2. RED   — run a check; capture failing output (or type error)
3. GREEN — minimal change; re-run until pass
4. REFACTOR — clean-minimal-code; re-run same command
5. Repeat until acceptance checklist complete
```

**Never skip step 2.** If you cannot fail the check, the check is too weak.

## Pick the narrowest proof

| Change type | First command to run |
|---|---|
| Pure function / domain rule | Unit test for that function, or `node -e` / `python -c` one-liner |
| API route / handler | Single request test (supertest, httpx, fetch to local dev) |
| React component logic | Component test or Storybook interaction test |
| Type-only change | `tsc --noEmit` or `pnpm typecheck` |
| Lint/format | `eslint` / `ruff check` on touched files |
| DB migration | Migrate up on local DB + one integration test |
| Full slice uncertain | Smallest test file covering the slice, not whole suite |

Escalate to full suite or E2E only after slice tests are green.

## Watch mode (preferred when available)

Keep a watcher running while editing. In Claude Code, start the watcher with the Bash tool's `run_in_background` option; a watch command never exits, so never run one in the foreground. If you cannot read the output of a background command, run the related test file once after each edit. In another environment, use a **tmux** terminal:

| Stack | Watch command |
|---|---|
| Vitest | `pnpm vitest --watch related` or `--changed` |
| Jest | `pnpm jest --watch --findRelatedTests path/to/file.test.ts` |
| pytest | `pytest --lf -x` (last failed) or `ptw` (pytest-watch) |
| TypeScript | `tsc --noEmit --watch` in parallel |
| Go | `go test ./... -count=1` after saves, or `air` for apps |

If watch is unavailable, run the related test file manually after **each** save batch.

## After every slice (minimum bar)

Before moving to the next file or feature area:

1. **Related tests** — pass (show exit code 0 or summary line)
2. **Typecheck** — if TS project, no new errors in touched packages
3. **Lint** — on changed files if the repo uses it

Store evidence: last command + relevant output lines in your working notes. `proactive-agency` requires this before claiming done.

## TDD micro-rules

- One behavior assertion per test when learning a module; merge later if noisy.
- Test **behavior**, not implementation (avoid asserting private method calls).
- Fixtures: smallest factory that satisfies the type; no 200-line JSON blobs.
- Flaky test = broken product — fix or quarantine immediately, never ignore.

## When no tests exist

1. Read `package.json` / `pyproject.toml` / `Makefile` for the canonical test script.
2. Add **one** test file next to the code you change (match repo convention).
3. If repo truly has zero test infra, run the **next best proof**: script invocation, curl, or typecheck — and note the gap.

Do not use missing tests as an excuse to skip the loop.

## Integration with other skills

| Phase | Skill |
|---|---|
| Define what to prove | `deliverable-first` (acceptance checklist) |
| Structure test doubles | `stable-architecture` (ports/adapters) |
| Browser proof of full story | `verification` (after unit/integration green) |
| PR CI red | `fix-ci` / `loop-on-ci` |

## Anti-patterns

| Do not | Do instead |
|---|---|
| "Tests pass" without running them | Paste command + exit code |
| Run full E2E for every line change | Related unit/integration first |
| Commit with `@ts-ignore` to go green | Fix types or narrow the boundary |
| Disable a test to go green | Fix product or test |
| Batch 10 files then test once | Slice + loop per checkbox |

## Done definition

A task is **done** when:

- Every acceptance checkbox from `deliverable-first` has a **fresh** passing check
- The same checks would pass on CI (same scripts, no local-only env hacks)
- You can name the exact commands to reproduce green state

## In Claude Code

This skill is part of the `coding` plugin. Load a skill that this text names with the Skill tool: `coding:<name>` for a skill of this plugin, or the name that the session lists for a skill of another pack. If the session does not list a named skill, continue without it.
