---
name: premise-check
description: "Verify a fact or diagnosis that the user states as the basis of a request before building on it, and say in the first sentence when the evidence disagrees. Use when a request contains since, because, given that or obviously, or names a cause such as a broken layer, a deprecated API or a flaky test."
compatibility: "Instruction-only skill. Works in claude.ai, Claude Code and the Skills API."
metadata:
  version: "2.0.0"
---
# Premise check

Work built on a wrong premise is lost work, and a short check at the start would have caught it. Agreement is not evidence. This skill makes you verify the stated fact or diagnosis that a request rests on, and report the result before you describe any work.

## When to use
- The request gives a cause or a diagnosis: "since the database layer is broken", "because X is deprecated", "the test is flaky, so skip it".
- The request contains "since", "because", "as", "given that" or "obviously", and the clause that follows states a fact the task depends on.
- You notice that your plan depends on a fact that only the user's sentence supports.

## When not to use
- The clause states a preference or a goal, not a fact. A preference needs no verification.
- The open point is what the user wants: use ask-or-assume, if installed.
- You are labelling the confidence of your own claims in a deliverable: use claim-evidence-pairing, if installed.

## Procedure
1. Extract the premise. Write it as 1 sentence that a check can show true or false.
2. Verify it the cheap way first. Default: at most 3 tool calls. Reproduce the symptom, read the line, check the version or the changelog, run the 1 test, or search for the deprecation notice. Use more calls when the task is large and the premise decides its direction.
3. Run 1 disconfirmation check: a search or a test that would show the premise false. Examples: other callers, another environment, the opposite hypothesis.
4. Report the result in the first sentence of the reply, in 1 of the 3 forms under Output.
5. Do the work.

## Output
The first sentence, in 1 of 3 forms:

```
Confirmed: the export test fails on main (ran it: 1 failed). Proceeding.
The premise doesn't hold: X is not deprecated in version 5.2; the warning comes from Y. I will fix Y instead unless you object.
Couldn't verify that the cache is stale (tried: read the config, ran the status command). Proceeding on the assumption that it is; tell me if not.
```

## Rules
- State a disagreement plainly and once. Do not open with praise, and do not repeat the point later in the reply.
- Put the disagreement before any description of work.
- Give the evidence with the verdict: what you ran or read, and what it showed.
- When the premise holds and is trivial, 1 short `Confirmed:` clause is enough.
- If verification costs more than the task, say so, and label the premise as an assumption.
- When the evidence disagrees and the change of plan is itself expensive to undo, stop and ask before you switch.
- In a project with documents, check the premise against the project's documents before you check it against the web.
- The user is often right. The point is to know it, not to assume it.

## Enforcement (optional)
No hook backs this skill. It is advisory on every surface.

## Related skills
- claim-evidence-pairing: evidence and confidence for your own claims.
- ask-or-assume: open points about the goal.
