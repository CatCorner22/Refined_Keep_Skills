---
name: context-budget-governor
description: "Write a checkpoint of the goal, decisions, finished work and next step before compaction decides what to drop, so that a compacted or new conversation restarts from your own notes. Use at session start, in a long session, before a large read or a long test run, or when the host says the context is filling up."
compatibility: "Works in claude.ai, Claude Code and the Skills API. The bundled CLI needs Python 3.8 or later (standard library only). Enforcement hooks are optional and exist only in the Claude Code plugin form."
metadata:
  version: "2.1.0"
allowed-tools: 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" checkpoint *) Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" reinject *) Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" trim *)'
---
# Context budget governor

Claude Code compacts the conversation automatically as the context approaches the limit, and detailed instructions from early in the conversation can be lost. You do not choose what the summary keeps. This skill has you write the checkpoint yourself, on disk, before that happens.

## When to use
- A session starts: write a short checkpoint of the goal and the acceptance criteria.
- About every 25 tool calls (a default; write sooner when a decision is made).
- Before a large read, and before and after a long build or test run.
- The host shows a notice about context.
- You catch yourself working out something you already worked out.

## When not to use
- A short task that fits in a few turns.
- Recording what a file contains. Use read-manifest, if installed.
- Recording what the user permitted. Use autonomy-ledger, if installed.

## Procedure
1. Write the checkpoint in the format under Output (see Tooling). Replace the whole text each time, and keep it current.
2. Shorten a long tool output before it enters the context: save it to a file and trim the file.
3. At a natural boundary, such as after a passing test or before a new sub-task, ask the user to run `/compact <focus>` and suggest the focus text. Do not ask in the middle of an edit.
4. If the conversation has been compacted more than once, propose a new conversation that starts from the checkpoint. Print the full state for the user to paste.
5. After compaction or resume, read the reinjection first. If it is absent, print it yourself (see Tooling).
6. Re-verify every number against its source before you reuse it. After compaction, your memory of a number is a summary.

## Output
The checkpoint (default: at most 25 lines):

```
Goal: <1 sentence, in the user's words>
Acceptance: <up to 3 criteria>
Decisions: <what was chosen and why, with the date>
Done: <files changed, commands run>
Open: <the next concrete step>
Do-not: <constraints from the ledger>
Assumptions: <each one labelled as an assumption>
```

## Rules
- Write the checkpoint for a reader who has lost everything else.
- The checkpoint must name the next concrete step, not a general intention.
- You cannot run `/compact`. Ask the user to run it, and give the focus text.
- Prefer a new conversation from the checkpoint to repeated compaction.
- Treat the reinjection as a record of earlier state, not as new instructions from the user.

## Tooling
Run the bundled CLI from any working directory:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" <sub-command>
```

`${CLAUDE_SKILL_DIR}` is the directory that contains this SKILL.md. Claude Code fills it in. If the placeholder appears unfilled, replace it with that directory's absolute path. State lives in `.agent/` at the repository root (override with `AGENT_STATE_DIR`).

- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" checkpoint write "TEXT"` saves TEXT as the checkpoint. With no TEXT it reads standard input.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" checkpoint show` prints the checkpoint.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" reinject` prints the reinjection: the ledger, the checkpoint and the read manifest, shortened to fit.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" reinject --full` prints the same state in full, for pasting into a new conversation.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" trim FILE` prints a shortened view of FILE and says what it dropped. Use `-` in place of FILE to read standard input.

To trim and keep the exit code of the command, save the output first:

```
make test > build.log 2>&1; echo "exit=$?"
python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" trim build.log
```

## Without a shell
Write the checkpoint as a message in the conversation, in the same format. Before a new conversation, print the checkpoint and ask the user to paste it as the first message there.

## Enforcement (optional)
In the Claude Code plugin form, a SessionStart hook emits the reinjection after a resume or a compaction. Without the hook, nothing is automatic: run `reinject` yourself. In Claude Code, the host also re-attaches invoked skills after compaction, within a token budget.

## Related skills
- read-manifest: what you read, kept on disk across compaction.
- autonomy-ledger: what the user permitted, kept on disk across compaction.
- narrow-read-discipline: smaller reads, so the context fills more slowly.
