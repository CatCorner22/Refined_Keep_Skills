---
name: model-sanity-regression
description: "Run a fixed personal regression set against a model and record dated results, to tell a change in the model from a change in your own prompts and rules. Use when the model feels off, after a vendor update, or before you rely on a new model for real work."
compatibility: "Works in claude.ai, Claude Code and the Skills API. The bundled CLI needs Python 3.8 or later (standard library only). Enforcement hooks are optional and exist only in the Claude Code plugin form."
metadata:
  version: "2.1.0"
allowed-tools: 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" regress *)'
---
# Model sanity regression

When output gets worse, the cause can be the model, the infrastructure, or a change you made to your own prompts and rules. An impression cannot separate these. A fixed set of prompts, scored the same way each time and recorded with the date and the model, can.

## When to use
- The user says the model "feels off" or "got worse".
- The vendor released an update, or the user switched models.
- The user is about to rely on a new model for real work.
- The user changed a rules file or a skill and wants to know the effect.

## When not to use
- 1 known failure needs a fix. Use the skill that matches that failure.
- The user wants a public benchmark. This set is personal and small.

## Procedure
1. Create the regression set once (see Tooling). The default set has 12 items. Each item has an id, a setup, 1 or more turns to send, and yes-or-no checks.
2. Ask the user to add items from the user's own recurring failures, and to edit items that do not fit. The set file is `.agent/regress/set.json`.
3. Print the set. The user runs each prompt in a new session with the usual rules and skills loaded. A session cannot test itself: the session that runs a prompt does not score it.
4. Score each transcript strictly:
   - pass: every check is yes.
   - fail: no check is yes.
   - partial: anything else.
5. Record each result with the exact model identifier and the date.
6. Print the scoreboard and read it with the table under Output.

## Output
One recorded result per item, then the scoreboard by model and date. Read the scoreboard this way:

| Pattern | Suspect | Next step |
|---|---|---|
| Many items drop on 1 date, with the same prompts | the model or the infrastructure | Check the vendor's status page and changelog. Select a fixed model version if the host allows. |
| 1 item drops after you edited a rules file | your change | Revert the edit and run that item again. |
| Counts are flat, but the work feels worse | the set no longer represents your tasks | Add a representative item. |

## Rules
- Do not change a prompt between runs. A changed prompt starts a new item with a new id.
- Record the model identifier exactly as the host shows it. In Claude Code, `/status` shows the version and the model.
- Score against the written checks, not against an impression.
- Record a fail as a fail. A scoreboard with generous scores cannot show a drop.
- Run the whole set each time. A partial run cannot be compared with a full one.
- State the limit when you report: a small set shows a large change, and it does not prove a small one.

## Tooling
Run the bundled CLI from any working directory:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" <sub-command>
```

`${CLAUDE_SKILL_DIR}` is the directory that contains this SKILL.md. Claude Code fills it in. If the placeholder appears unfilled, replace it with that directory's absolute path. State lives in `.agent/` at the repository root (override with `AGENT_STATE_DIR`).

- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" regress init` writes the default set. It keeps an existing set unless you add `--force`.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" regress show` prints each item: id, setup, turns and checks.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" regress record ID pass "MODEL" --note "TEXT"` appends 1 result. The result is `pass`, `partial` or `fail`. It refuses an ID that is not in the set unless you add `--force`.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" regress report` prints the scoreboard by model and date.

Example: `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" regress record F1-inventory pass "MODEL-ID 2026-11-10" --note "searched the project first"`.

## Without a shell
Keep the set and the scoreboard in 1 file that the user stores, because a chat does not keep state between conversations. Use a table with the columns date, model, item id, result and note. Ask the user to upload the file at the start of each run, and return the updated file at the end.

## Enforcement (optional)
No hook backs this skill. It runs only when the user asks for it.

## Related skills
- The skill that matches each failing item is the fix for that item. For example, a failing inventory item points to inventory-before-fetch, if installed.
