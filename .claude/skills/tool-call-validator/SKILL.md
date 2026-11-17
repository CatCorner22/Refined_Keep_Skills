---
name: tool-call-validator
description: "Check a tool call before and after it runs: the working directory, the arguments, a bound on the output, then the exit code and the error text. Use before a shell, file or HTTP call that carries a path, a URL or a destructive flag, and whenever a call fails or returns nothing."
compatibility: "Instruction-only skill. Works in claude.ai, Claude Code and the Skills API."
metadata:
  version: "2.1.0"
---
# Tool-call validator

Many tool failures are mechanical: the wrong working directory, a glob that matched nothing, a flag that this version of the tool does not have, or the same failing command sent again unchanged. This skill puts a short check before the call and a short reading of the result after it.

## When to use
- A call carries a path, a URL or a destructive flag.
- A call failed, or returned empty output.
- You are about to send a call that already failed.

## When not to use
- The call deletes, overwrites or reaches outside the project. Use scope-and-blast-radius-check, if installed, for the confirm-first action.
- You are deciding whether to download a file. Use inventory-before-fetch, if installed.
- A read-only call on a path you have already confirmed in this session.

## Procedure
Before the call:

1. Confirm the working directory. Check that it is the repository you mean to touch, and that each relative path resolves where you expect.
2. Check the arguments against the tool's schema or its `--help` output: each required argument is present, each value has the right type, and each flag exists in this version.
3. Bound the output. Use the tool's own quiet or limit option where it has one.
4. If the call has a destructive flag such as `-f`, `--force`, `--hard` or `-r`, stop and follow scope-and-blast-radius-check.

After the call:

5. Read the exit code and the error text before you do anything else.
6. Report a failure with the exit code and the error text verbatim.
7. If the output is empty, check that empty is the expected result and not the sign of a wrong path or a pattern that matched nothing.
8. After 2 identical failures, stop. Change the input, the route or the diagnosis, and say what you changed.

## Output
For a failed call:

```
Command: npm test -- parser
Exit code: 1
Error: "Cannot find module './lexer'"
Changed before retry: import path corrected to ./lib/lexer
```

## Rules
- Do not repeat a failing call unchanged. A third identical attempt gives the same result.
- Do not hide the error stream. Do not append `|| true` to make a command look successful.
- Do not guess at flags. Read the `--help` output once.
- Keep the exit code when you shorten output. A pipe reports the exit code of its last command, so `cmd | tail` hides a failure. Use this form:

```
cmd > out.log 2>&1; echo "exit=$?"; tail -50 out.log
```

- Let the host limit long output where it does so. Claude Code returns a long shell output as a file path plus a short preview.
- Prefer a dedicated file tool to its shell equivalent where the host has one. Where the host has no search tool, use `grep -n` or `rg -n` in the shell.
- If the tool or its wrapper rejects a call as malformed, check the shape of the call before you conclude that the tool is broken.
- "It errored" is not a report. Quote the error.

## Enforcement (optional)
In the Claude Code plugin form, a PreToolUse hook denies a shell call that failed twice in a row with nothing changed in between. Without the hook, this skill is advisory.

## Related skills
- scope-and-blast-radius-check: the check and the user's go-ahead before a destructive call.
- inventory-before-fetch: the check before a download.
