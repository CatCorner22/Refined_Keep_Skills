---
name: inventory-before-fetch
description: "Check what is already available before downloading, fetching, cloning or asking the user to upload a file, and state the result in one inventory line. Use when a plan includes a download or re-download, when the user says a file is in a project, folder or attachment, or before saying a file is not accessible."
compatibility: "Works in claude.ai, Claude Code and the Skills API. The bundled CLI needs Python 3.8 or later (standard library only). Enforcement hooks are optional and exist only in the Claude Code plugin form."
metadata:
  version: "2.0.0"
allowed-tools: 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" manifest *) Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" fetch-check *)'
---
# Inventory before fetch

A file that the user can see in a project or folder is not necessarily in your context. Project knowledge, attachments and earlier tool results are separate stores, and some of them load only when you search. This skill prevents 2 failures: fetching a file you already hold, and telling the user a file is missing when you did not look.

## When to use
- Your plan contains a download, a re-download, a fetch or a clone of data.
- The user says a file is in the project, in a folder or in an attachment.
- You are about to write "please upload", "please provide" or "I don't have access to".

## When not to use
- You hold the file and are recording what you read: use read-manifest, if installed.
- You are making a claim about a document's content: use retrieval-verification-gate, if installed.

## Procedure
Run the 4 steps in order. Stop at the first hit.

1. State directory. Run `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" manifest check NAME`. If the status is `UNCHANGED`, use the summary or read a range.
2. Host stores. Search with the file name and 2 synonyms, for example `survey_2026.parquet`, "survey data" and "2026 survey". Use the host's search for project knowledge, attached files or connected sources.
3. Conversation. Look at attachments and tool results earlier in this conversation, and at the reinjection after compaction.
4. Filesystem. Search by name and by extension in the workspace, the downloads directory and the data directories.
5. Write the inventory line.
6. Fetch only after a NOT AVAILABLE line and the user's choice. Check the command first: `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" fetch-check '<command>'`.
7. After the fetch, record the file: `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" manifest record PATH --url URL --summary "..."`.

## Output
The inventory line, before any fetch, in 1 of 2 forms:

```
Inventory: FOUND survey_2026.parquet in project knowledge (412 MB). Using it.
Inventory: NOT AVAILABLE TO ME in this conversation (checked: read manifest, project search with 3 terms, attachments, ./data). Options: (a) you attach it again, (b) I download 412 MB. Say which.
```

## Rules
- "Not available to me" is different from "does not exist". Say which stores you checked.
- Do not ask the user to upload again what a search can find.
- Do not write "I don't have access to your files" before you have searched.
- Do not fetch a file to be safe, to get "the latest copy", or because compaction removed your memory of it. The read manifest remembers.
- When the inventory finds the file, name the file and the store when you use it.
- When the fetch guard blocks a fetch, show the user the block reason and ask. After the user says yes, run `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" approve -- '<exact command>'`, then retry the identical command. The host shows the approve command to the user. A ledger entry does not unlock a fetch.
- In a claude.ai Project that uses retrieval, a listed file is in context only after a search returns it. If your tool list contains a project knowledge search tool, call it. If it contains none, look for the text in your context. If you do not find it there, say that you cannot see the file in this conversation.
- After a search, say "not in the passages I retrieved", not "not in the project".

## Tooling
Run the bundled CLI from any working directory:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" <sub-command>
```

`${CLAUDE_SKILL_DIR}` is the directory that contains this SKILL.md. Claude Code fills it in. If the placeholder appears unfilled, replace it with that directory's absolute path. State lives in `.agent/` at the repository root (override with `AGENT_STATE_DIR`).

- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" manifest check NAME` prints the status of a recorded file, matched by path, by recorded URL or by a unique file name. Exit code 0 for `UNCHANGED`, 1 otherwise.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" fetch-check '<command>'` prints ALLOW or BLOCK with the reason. Exit code 0 for ALLOW, 1 for BLOCK.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" manifest record PATH --url URL --summary "..."` records a fetched file with its source.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" approve -- '<exact command>'` records an approval for that exact command. It is not pre-approved: the host asks the user.

## Without a shell
Do steps 2 and 3 with the host's search and the conversation. Write the inventory line and name the stores you checked. Keep a list in the conversation of the files you found and where.

## Enforcement (optional)
In the Claude Code plugin form, the fetch guard hook denies a fetch that duplicates a recorded file that still exists, and an unapproved fetch of a large data file type. Without the hook this skill is advisory.

## Related skills
- read-manifest: records what was read or fetched.
- retrieval-verification-gate: what you may say about a file once it is found.
