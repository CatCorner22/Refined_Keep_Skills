---
name: completion-evidence-gate
description: "Attach an evidence block to every completion claim: what counts as done, the command you ran, its quoted output, the diff, and what you did not verify. Use when you are about to say that work is done, fixed, passing or implemented, or when you write a pull request description or a status report."
compatibility: "Works in claude.ai, Claude Code and the Skills API. The bundled CLI needs Python 3.8 or later (standard library only). Enforcement hooks are optional and exist only in the Claude Code plugin form."
metadata:
  version: "2.0.0"
allowed-tools: 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" gate *)'
---
# Completion evidence gate

An agent can write "all tests pass" without running a test, or "fixed" without reproducing the fault. This skill ties every completion claim to an evidence block, so that the reader can see what you ran and what you did not check.

## When to use
- You are about to write that work is done, fixed, passing, implemented or ready for review.
- You are writing a pull request description, a status report or a handoff.

## When not to use
- The claim is a fact or a diagnosis, not a completion claim. Use claim-evidence-pairing, if installed.
- You are choosing which tests to run. Use test-impact-selector, if installed.
- The message is a plan, a question or a progress note that claims nothing is finished.

## Procedure
1. Find the acceptance criteria: the ACCEPT entry in the ledger, or the user's words.
2. Run the check that tests those criteria: the tests, the build, or a read-after-write check.
3. Copy the result line exactly, with its number.
4. Write the evidence block below the claim.
5. List under `Not verified` everything you did not check.
6. If part of the work is open, add a `Status: partial` line and say which criteria are met.
7. Check the draft before you send it (see Tooling). If the check prints a reason, fix the draft and check again.

## Output
The evidence block has 5 labels, in this order:

```
Acceptance: the parser accepts quoted fields (the user's request)
Command: python3 -m pytest tests/test_parser.py -q
Output: "47 passed in 3.2s"
Diff: src/parser.py (+31 -4), tests/test_parser.py (+18)
Not verified: Windows paths; behavior under concurrent writes
```

Optional line: `Status: partial (2 of 3 acceptance criteria met)`.

## Rules
- If you did not run it, you may not say it passes. Run it, or write `Command: not run` and say so in the claim.
- The `Output` line must quote the real result with its number: a test count, an exit code, a response code or a row count. A paraphrase such as "passed" or "ok" is not a result.
- The `Command` line must name a command that you ran in this session.
- A read-after-write check counts as evidence, for example `git status --short` or `ls -la out/` after a write.
- Do not write "should work" or "this will fix it" in place of a result. Say what you ran, or say that you did not run it.
- `Status: partial` is welcome. An honest partial report is more useful than a confident wrong one.
- The gate checks the form of the message. It does not rerun the command, so the quoted output must be the real output.

## Tooling
Run the bundled CLI from any working directory:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" <sub-command>
```

`${CLAUDE_SKILL_DIR}` is the directory that contains this SKILL.md. Claude Code fills it in. If the placeholder appears unfilled, replace it with that directory's absolute path. State lives in `.agent/` at the repository root (override with `AGENT_STATE_DIR`).

- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" gate --file DRAFT.md` checks a draft message in a file. It prints `PASS` and exits 0, or prints the reason and exits 1.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" gate "TEXT"` checks the text you pass. Same output and exit codes.

When the tool log holds commands, the gate also checks that the command in the `Command` line appears there.

## Without a shell
Check the draft by hand. Confirm that all 5 labels are present, that `Output` is a quotation with a number, and that you ran the command in this conversation. If you ran nothing, write `Command: not run` and move the claim to `Not verified`.

## Enforcement (optional)
In the Claude Code plugin form, a Stop hook backs this skill. The hook acts only when the final message claims completion and the turn changed something. It then asks for the evidence block and checks that the cited command appears in the tool log of this session. It prompts once for each stop attempt and does not loop. Without the hook, this skill is advisory.

## Related skills
- claim-evidence-pairing: evidence for facts and diagnoses inside a deliverable.
- test-impact-selector: which tests to run before you claim that tests pass.
