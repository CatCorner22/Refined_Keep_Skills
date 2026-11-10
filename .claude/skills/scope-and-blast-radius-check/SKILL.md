---
name: scope-and-blast-radius-check
description: "Resolve every target, classify the action as reversible or irreversible, and get the user's go-ahead before a destructive or wide-reaching action. Use before delete, drop, reset, overwrite, force push, deploy, migrate or publish, before writing outside the project, and when development and production might be confused."
compatibility: "Works in claude.ai, Claude Code and the Skills API. The bundled CLI needs Python 3.8 or later (standard library only). Enforcement hooks are optional and exist only in the Claude Code plugin form."
metadata:
  version: "2.0.0"
allowed-tools: 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" fence-check *) Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" scope show) Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" approvals show)'
---
# Scope and blast-radius check

The costly mistakes share 1 pattern: the agent acts on a path or a target that it did not resolve, in an environment that it did not confirm. This skill makes you resolve the target, classify the action, and stop for the user's go-ahead before a confirm-first action.

## Confirm-first action
A confirm-first action is an action that needs the user's explicit go-ahead before it runs. An action is confirm-first when it loses data that no commit and no backup holds, changes a remote or shared system, publishes, spends money, or sends a message to a person. The scope fence recognizes these families:

- recursive delete (`rm -rf`, and `find` with `-delete`);
- force push, and a push to a protected branch such as `main`;
- a git command that discards uncommitted work (`git reset --hard`, `git clean -f`, `git checkout -- PATH`, `git restore PATH`, `git stash drop`);
- history rewrite (`git filter-branch`, `git branch -D`);
- destructive SQL (`DROP`, `TRUNCATE`, `DELETE` or `UPDATE` with no `WHERE`);
- a database client or a migration runner pointed at production;
- infrastructure delete (`terraform destroy`, `kubectl delete`, cloud `delete` commands);
- publish or deploy (`npm publish`, a production deploy, `gh pr merge`, `docker push`);
- system-level destruction (`mkfs`, `dd of=`, `shutdown`, `killall`);
- inline code that deletes files (`python3 -c` with `rmtree`).

The list is not complete. An action with 1 of the effects above is confirm-first even when no family names it, for example a connector action that sends an email or deletes a shared file.

## When to use
- Before any action in the families above.
- Before a write outside the project directory.
- When a command contains `~`, a variable or a glob in a target position.
- When development and production might be confused.

## When not to use
- You are recording a permission that the user gave: use autonomy-ledger, if installed.
- The command failed because of its form or its arguments: use tool-call-validator, if installed.

## Procedure
1. Declare scope once per repository. Check the declared roots with `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" scope show`. The default root is the repository root.
2. Resolve every target. Print the absolute path, what `~`, each variable and each glob expand to, and which database, cluster or account the command reaches.
3. Classify. Reversible: an edit to a tracked file with a clean commit behind it, or deleting a file you created in this task. Irreversible: every confirm-first action. When unsure, classify as irreversible.
4. Test the command: `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" fence-check '<command>'`.
5. For a confirm-first action: finish all reversible preparation, show the exact command and the resolved targets, and ask for a one-word go-ahead.
6. After the user's explicit yes, run `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" approve -- '<exact command>'`. Then run the identical command. The approval lasts 30 minutes by default and covers that exact command only.
7. After any write, do a read-after-write check (`ls -la`, `git status --short`, `wc -l`, `SELECT count(*)`, an HTTP status). Report the number.

## Output
```
About to run: rm -rf /home/dev/app/build
Resolves to: /home/dev/app/build (inside the declared roots; 214 files; not tracked by git)
Irreversible: recursive delete. Reply "go" to proceed.
```

## Rules
- Ambiguity between development and production is a hard stop. Name the environment in the command, or do not run it.
- Do not widen scope silently to make a blocked command pass. For a write outside the declared roots, fix the path, or after the user agrees run `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" scope add DIR`.
- A denial is information that the path was probably wrong. Read the reason. If the reason misreads the command, tell the user.
- A ledger entry does not unlock the scope fence. Only an approval does, and only the user's yes justifies an approval.
- The scope fence is a seatbelt against mistakes, not a sandbox.
- Hard rules can also live in `.claude/settings.json` under `permissions.deny`, for example `Bash(rm -rf *)` and `Bash(git push --force *)`. A deny rule covers the command form Claude usually writes; it is not a security boundary.

## Tooling
Run the bundled CLI from any working directory:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" <sub-command>
```

`${CLAUDE_SKILL_DIR}` is the directory that contains this SKILL.md. Claude Code fills it in. If the placeholder appears unfilled, replace it with that directory's absolute path. State lives in `.agent/` at the repository root (override with `AGENT_STATE_DIR`).

- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" fence-check '<command>'` prints ALLOW, or BLOCK with the label and the reason. Exit code 0 for ALLOW, 1 for BLOCK.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" scope show` prints the declared roots.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" scope set ROOT --allow REGEX` replaces the declared roots. `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" scope add DIR` adds 1 root. Both prompt the user.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" approve --minutes 10 -- '<exact command>'` records an approval. It prompts the user.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" approvals show` prints the unexpired approvals.

## Without a shell
Do steps 2, 3, 5 and 7 in the conversation. State the resolved target and the classification, and wait for the user's go-ahead before any connector action that deletes, sends, publishes or merges.

## Enforcement (optional)
In the Claude Code plugin form, the scope fence hook denies an unapproved command in the families above and a write outside the declared roots. Without the hook this skill is advisory.

## Related skills
- autonomy-ledger: records what the user permitted and forbade.
- tool-call-validator: checks the form of a call and handles repeated failures.
- ask-or-assume: whether an open point needs a question.
