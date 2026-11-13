---
name: backward-review-gate
description: "Review every plan, reply and deliverable from its last part to its first part, correct every error, re-read it from first to last, and end it with a review record, before you present it or act on it. Use for every task and every reply: before you present a plan, before you act on a plan, before you send an answer, and before you say that work is done."
compatibility: "Works in claude.ai, Claude Code and the Skills API. The bundled CLI needs Python 3.8 or later (standard library only). Enforcement hooks are optional and exist only in Claude Code."
metadata:
  version: "2.1.0"
allowed-tools: 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" review *)'
---
# Backward review gate

An author who reads a draft in the order of writing reads what the author meant, not what the draft says. Reading the parts in reverse order breaks that flow, so each part has to stand alone. For a plan, the reverse order also starts at the goal and asks of each step what must already be true, which exposes a missing prerequisite and a wrong order. This skill makes you do that review, then re-read the corrected work product, before you move forward.

## Terms
- Work product: anything that you are about to present, send, deliver or act on. A plan, a reply, a document, a code change, a sequence of commands and a report from a sub-agent are each a work product.
- Part: the unit that you review. See the table in step 1.
- Backward pass: the review of the parts from the last part to the first part.
- Forward re-read: the reading of the whole corrected work product from the first part to the last part.
- Review record: the line that ends the work product and states what the review did.
- Review point: a moment at which the review is due.

## When to use
Always. Every work product gets the review. The review points are:
- Before you present a plan. In plan mode, this is before you call ExitPlanMode.
- Before you act on a plan: re-read the whole plan first, in the version that the user approved.
- Before each step of a plan that is hard to undo: re-read that step and the steps it depends on.
- When the result of a step differs from what the plan expected: stop, revise the remaining steps, and review the revised steps.
- After a compaction or a resume: re-read the plan before the next step.
- Before you send a reply, however short.
- Before you deliver a file, a commit, a pull request or a message to another person.
- Before you rely on the report of a sub-agent, and before you return a report as a sub-agent.

## When not to use
- No work product is exempt. The size of the review follows the size of the work product: a reply of 1 sentence has 1 part and takes a moment.
- Do not review text that the user wrote, unless the user asks. Review your own work product.
- The checks of a single tool call (directory, arguments) belong to tool-call-validator, if installed.
- The evidence for a claim that work is done belongs to completion-evidence-gate, if installed. That evidence block stands above the review record.

## Procedure
1. Finish the draft, split it into parts, and count the parts.

   | Work product | Part |
   |---|---|
   | Plan | step |
   | Reply or document | paragraph, list item or table row; in a reply of 1 paragraph, the sentence |
   | Code change | hunk, or function when a hunk spans several |
   | Sequence of commands | command |
   | More than 30 parts | 2 levels: the sections last to first, then the parts inside each section last to first |

2. Re-read the user's request. Write down the goal and each requirement in the user's words.
3. Do the backward pass. Start at the last part and check that it delivers the goal. Then, for each part from the last to the first, answer 4 questions:
   - Correct: is every fact, name, number, path, command and quotation in this part right? Did you verify it, or do you assume it? Label what you assume.
   - Supplied: what must be true before this part can work, and which earlier part or known fact supplies it? If nothing supplies it, a part is missing or the order is wrong.
   - Needed: which later part, or which requirement of the user, uses this part? If none does, the part is surplus or it aims at the wrong target.
   - Failure: what can go wrong at this part, and does the work product say what happens then?
4. At the first part, check that it starts from the state that exists now, not from a state that you assume.
5. Correct every finding in the work product itself.
6. Do the forward re-read against the list from step 2. Check that a part meets each requirement, that each term means 1 thing, that no part contradicts another part, and that each correction fits the parts around it.
7. If the forward re-read finds an error, correct it, repeat the backward pass for the corrected part and for every part that depends on it, and do the forward re-read again. After 3 rounds, stop and report the open finding in the review record.
8. Write the review record as the last line of the work product.
9. Move forward only now: present, send, deliver or act.

## Output
The review record is 1 line with 4 elements in this order: the number of parts, the direction, the forward re-read, and the corrections.

```
Backward review: 7 parts, last to first; forward re-read done. Corrections: step 5 read a file that step 6 creates, so I swapped them.
Backward review: 1 part, last to first; forward re-read done. Corrections: none.
Backward review: 12 parts, last to first; forward re-read done. Corrections: fixed the port number in step 3. Open: I could not verify the API version in step 9.
```

## Rules
- Do the review before the work product leaves you. A review after the user has seen the work product is a repair, not a review.
- Write `Corrections: none` when you found nothing. Do not invent a finding to make the record look useful.
- Do not write the record from memory of the draft. Read the parts as they stand.
- If you change the work product after you wrote the record, the record is stale. Review the changed part and every part that depends on it, then write a new record.
- If a correction changes something that the user has already seen, state the correction plainly. Do not change it in silence.
- If you cannot fix a finding, report it under `Open:` in the record and say what would resolve it.
- If the user tells you to skip the review for 1 work product, skip it and end that work product with `Backward review: not done, at the user's request.`
- The record states what you did. It is not proof, so the review itself must be real.

## What can go wrong
| Situation | What to do |
|---|---|
| The work product is 1 sentence | 1 part. Read it once against the request, then write the record. |
| The work product is very long | Use the 2 levels from step 1. Do not sample: review every part. |
| The backward pass finds that the goal itself is unclear | Stop and use ask-or-assume, if installed, before you correct anything. |
| A fact in a part cannot be checked now | Label it as an assumption in the part and list it under `Open:`. |
| The user edited the plan before approving it | Review the approved version. Your earlier record does not cover it. |
| A hook blocks the reply because the record is missing | Do the review now, state each correction plainly, and end with the record. |
| The context was compacted and the plan is no longer visible | Read the plan file or the checkpoint again before the next step. Do not act from a summary. |

## Tooling
Run the bundled CLI from any working directory:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" <sub-command>
```

`${CLAUDE_SKILL_DIR}` is the directory that contains this SKILL.md. Claude Code fills it in. If the placeholder appears unfilled, replace it with that directory's absolute path.

- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" review --file DRAFT.md` checks a draft reply in a file. It prints `PASS` and exits 0, or prints what the record lacks and exits 1.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" review --plan --file PLAN.md` checks a plan. Same output and exit codes.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" review "TEXT"` checks the text you pass.

The check reads the form of the record. It ignores a record inside a code fence or a quoted line.

## Without a shell
Check the draft by hand: the last line starts with `Backward review:`, gives the number of parts, says `last to first`, says that the forward re-read is done, and has a `Corrections:` value.

## How to keep this skill engaged in every session
A skill loads only when Claude judges that its description fits the task, so no skill is engaged in every session by itself. To engage this skill in every session, add the always-on rule in `references/always-on-rule.md` to the instructions that the surface loads every time. That file gives the rule and the steps for claude.ai and for Claude Code.

## Enforcement (optional)
In Claude Code, 4 hooks back this skill. A UserPromptSubmit hook adds the rule to the context of every prompt. A PreToolUse hook on ExitPlanMode denies a plan that has no complete review record. A Stop hook and a SubagentStop hook prompt once when the final message has no complete review record. `AD_REVIEW=off` turns the 4 hooks off. Without the hooks, this skill is advisory.

## Related skills
- completion-evidence-gate: the evidence block for a claim that work is done.
- premise-check: a fact in the request that the work depends on.
- tool-call-validator: the checks of a single tool call.
- ask-or-assume: an open point about the goal.
