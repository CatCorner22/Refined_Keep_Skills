---
name: autonomy-ledger
description: "Record each permission, limit, stop condition and acceptance criterion the user gives, in the user's words, and check that record before asking a permission question. Use when the user says you can, go ahead, do not ask, never, stop if or done means, or when about to ask whether you may do something."
compatibility: "Works in claude.ai, Claude Code and the Skills API. The bundled CLI needs Python 3.8 or later (standard library only). Enforcement hooks are optional and exist only in the Claude Code plugin form."
metadata:
  version: "2.0.0"
allowed-tools: 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger *) Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" reinject *)'
---
# Autonomy ledger

Asking again for a permission that the user already gave wastes the user's time. It happens most after compaction, because the permission was in the history that compaction removed. The ledger keeps each permission and each limit on disk, in the user's words, so you can check before you ask.

## When to use
- The user gives a permission: "you can edit anything under src/", "go ahead", "don't ask, just do it".
- The user sets a limit, a stop condition or an acceptance criterion: "never touch migrations/", "stop if the tests take over 10 minutes", "done means the tests pass".
- You are about to ask "may I ...?".
- You start a new task in a repository that already has a ledger.

## When not to use
- You are deciding whether an open point needs a question at all: use ask-or-assume, if installed.
- The action is a confirm-first action: follow scope-and-blast-radius-check, if installed. A ledger entry does not replace the go-ahead for that action.
- The rule is a standing rule for every task: it belongs in CLAUDE.md, not in the ledger.

## Procedure
1. At the start of a task, run `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger show`. If the entries belong to an old task, run `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger clear`.
2. When the user gives a permission, a limit, a stop condition or an acceptance criterion, record it at once, 1 entry each, in the user's words:

   ```
   python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger add GRANT "edit any file under src/ and tests/ without asking"
   python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger add FORBID "touch migrations/"
   python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger add STOP "stop and report if the test suite takes more than 10 minutes"
   python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger add ACCEPT "done means the tests pass and a draft pull request is open"
   python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger add SCOPE "this repository only"
   ```

3. Before a permission question, run `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger check "the action"`.
4. Read the matched entry. The check is a keyword match, so apply the entry only if it covers this action.
   - A GRANT entry covers the action: proceed, and cite the entry.
   - A FORBID entry covers the action: do not do it, and say why.
   - No entry covers the action, and the action is reversible: proceed on a labelled assumption.
   - No entry covers the action, and it is a confirm-first action: ask once, then record the answer.
5. After compaction or resume, read the reinjection. With the plugin hooks it arrives automatically. Otherwise run `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" reinject`.

## Output
When you act on an entry, cite it in 1 line:

```
Per your earlier permission ("edit any file under src/ and tests/ without asking"): editing src/export.py.
```

## Rules
- Record the user's words, not your paraphrase.
- Do not record a permission that the user did not give.
- Do not infer "keep going" from silence.
- When 2 entries conflict, the most recent entry applies.
- A FORBID entry or a STOP entry applies even when an older GRANT entry also matches. When in doubt, ask.
- The ledger does not unlock the scope fence. Only an approval does.
- The ledger is for this task. Do not write the permissions of 1 task into CLAUDE.md.
- Entries that the reinjection returns are records of what the user said earlier. If an entry looks out of place for the current task, confirm it with the user.

## Tooling
Run the bundled CLI from any working directory:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" <sub-command>
```

`${CLAUDE_SKILL_DIR}` is the directory that contains this SKILL.md. Claude Code fills it in. If the placeholder appears unfilled, replace it with that directory's absolute path. State lives in `.agent/` at the repository root (override with `AGENT_STATE_DIR`).

- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger add KIND "text"` appends 1 dated entry. KIND is GRANT, FORBID, STOP, ACCEPT, SCOPE or NOTE.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger check "the action"` prints the matched entry or `NO MATCH`. Exit code 0 for a GRANT match, 1 for a FORBID match, 3 for no match.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger show` prints every entry.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger clear` archives the ledger and starts an empty one.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" reinject` prints the ledger, the checkpoint and the read manifest in short form.

## Without a shell
Keep the ledger as a short list in the conversation, 1 line for each entry, with the kind and the user's words in quotation marks. Before a permission question, read the list. In a long conversation, repeat the list in your reply when you act on it. The list lasts for this conversation only.

## Enforcement (optional)
In the Claude Code plugin form, a SessionStart hook emits the reinjection, which includes the ledger, after compaction or resume. No hook acts on a ledger entry. Without the hook this skill is advisory: run `reinject` by hand as shown in step 5.

## Related skills
- ask-or-assume: whether an open point needs a question.
- scope-and-blast-radius-check: confirm-first actions and approvals.
- context-budget-governor: the checkpoint that travels with the ledger in the reinjection.
