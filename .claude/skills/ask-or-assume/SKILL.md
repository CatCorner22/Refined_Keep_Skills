---
name: ask-or-assume
description: "Decide whether to ask the user or proceed on a labelled assumption when a request leaves the goal, an input or a constraint open. Use when a task is ambiguous at the start, when a choice is expensive to undo, or when about to interrupt the user with a question in the middle of the work."
compatibility: "Instruction-only skill. Works in claude.ai, Claude Code and the Skills API."
metadata:
  version: "2.1.0"
---
# Ask or assume

A question at the wrong moment costs the user attention. A wrong guess about the goal costs the whole task. This skill sorts each open point into 1 of 4 gap classes and gives each class a policy, so that you ask early about the goal and do not interrupt for what you can check or undo.

## When to use
- The request leaves the goal, a success measure or the audience open.
- 2 readings of the request lead to different work.
- You feel the urge to ask a question in the middle of a task.
- You reach a choice that is expensive to undo.

## When not to use
- The user already gave the permission or the limit: check autonomy-ledger, if installed.
- The open point is a fact that the user stated: use premise-check, if installed.
- The step is a confirm-first action: follow scope-and-blast-radius-check, if installed.
- The user asked for an interview, or told you not to ask. Follow the user.

## Procedure
1. List the open points. Classify each one:

   | Gap | Example | Policy |
   |---|---|---|
   | Goal | "Make the export faster": faster for whom, and by how much? | Ask before any work, in 1 message with the other goal questions. |
   | Input | Which of 2 configuration files is the current one? | Check it yourself. Ask only when you cannot decide and a wrong guess is expensive to undo. |
   | Constraint | May I add a dependency? | Reversible: assume and label. Confirm-first action: ask. |
   | Context | How is the module used elsewhere? | Read the code or the documents. Ask only when you have nothing to read. |

2. Ask all goal questions in 1 message. Do not spread them over several turns. Give options and a recommendation for each question.
3. For a reversible input gap or constraint gap, choose, write the `Assumed:` line, and continue.
4. For a choice that is expensive to undo, ask when you reach it, at whatever stage of the task.
5. After the midpoint of the task, ask only when you are blocked. Finish on labelled assumptions.
6. List every assumption in the final report under `Assumed:`, so that the user can reverse each one in 1 reply.

## Output
The question block:

```
Question 1: Which export is slow?
A (recommended): the CSV export, because the logs show it most often.
B: the PDF export.
```

The assumption line:

```
Assumed: the CSV export is the slow path (it appears most often in the logs). Tell me if not, and I will switch.
```

## Rules
- Default: at most 1 interruption per phase (plan, build, verify). Exceed it when you are blocked or when you reach a choice that is expensive to undo.
- A question must offer options and a recommendation. Do not ask an open question when you can name the likely answers.
- Do not ask what you can find by reading or by running a check.
- An irreversible step is a confirm-first action. The go-ahead for it does not count against the default above.
- If you cannot ask, as in an unattended run, proceed on the reversible reading, do not take a confirm-first action, and state each assumption in the final report.
- In Claude Code, the AskUserQuestion tool asks multiple-choice questions and fits a batched question with options. When you have more questions than 1 call takes, ask the rest in a second call in the same turn.

## Enforcement (optional)
No hook backs this skill. It is advisory on every surface.

## Related skills
- autonomy-ledger: permission that the user already gave.
- premise-check: facts that the user stated.
- scope-and-blast-radius-check: confirm-first actions.
