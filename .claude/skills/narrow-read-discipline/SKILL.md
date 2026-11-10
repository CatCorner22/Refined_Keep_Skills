---
name: narrow-read-discipline
description: "Read the smallest part of a file, log or tool output that answers the question: search first, then read a line range, and run the impacted tests before the full suite. Use when opening a large file, reading logs, paging through long output, or running tests after an edit."
compatibility: "Instruction-only skill. Works in claude.ai, Claude Code and the Skills API."
metadata:
  version: "2.0.0"
---
# Narrow-read discipline

Every whole-file read and every long tool output takes context that later steps need, and makes compaction arrive sooner. Locate first, then read only the part that answers the question.

## When to use
- You are about to open a file of more than about 200 lines.
- You are about to read a log or a long command output.
- You are about to run tests after an edit.
- You are about to open a file for the second time.

## When not to use
- The file is short, or its parts depend on each other and you need all of them. Read it whole and say why.
- You need a record of what you read: use read-manifest, if installed.
- You need the list of tests that a change affects: use test-impact-selector, if installed.
- You are about to edit: read every line you will change and enough around it to edit correctly.

## Procedure
1. Locate. Search for the symbol, the string or the error text first (`rg -n`, `grep -n`, `git grep -n`, or the host's search tool).
2. Read the match with about 15 lines of context on each side. Widen the range only when the answer is not in it.
3. For a file over about 400 lines, get an outline (headings, or function and class names), then read ranges.
4. For a log, read the tail, or search for error markers such as `ERROR`, `FAIL` and `Traceback`. Read around each hit.
5. For tests, run the tests that the change affects first. Run the full suite when shared or configuration code changed, before a pull request, or when the user asks. Say which tests you skipped.
6. For a command with large output, ask for less at the source (`--quiet`, `--json` with a filter, a count, a line limit). When you pipe output through `head` or `tail`, check the exit code of the command itself, not of the pipe.
7. On the second read of a file, record a summary that would have saved the read. Use read-manifest, if installed; otherwise write the summary in the conversation.

## Output
When you read a whole file, 1 clause with the reason:

```
Reading all 180 lines of settings.py: the options depend on each other.
```

When you skip tests, 1 line:

```
Ran 14 tests in tests/export/. Skipped the rest of the suite: no shared code changed.
```

## Rules
- A whole-file read needs a stated reason.
- Default reading budget for 1 task: 3 whole-file reads, 15 ranged reads, 1 full test run. Exceeding it is fine: say so and why.
- Do not paste a long result into the conversation to find 1 line in it. Search the result.
- Do not report on tests you did not run.
- A narrow read that misses the answer costs more than a wider one. When 2 ranged reads of the same file fail to answer the question, read the file whole.
- Claude Code: the Read tool takes `offset` and `limit`. A single Read call returns at most 25,000 tokens by default and refuses a whole file over 256 KB, so page through large files.
- Claude Code: the Grep and Glob tools can be absent on macOS, Linux and WSL. Use `grep -n` or `rg -n` through the shell as the fallback.
- claude.ai: for an attached document, search it for the term before you ask for or quote a whole section.

## Enforcement (optional)
No hook backs this skill. It is advisory on every surface.

## Related skills
- read-manifest: records each read with a summary, so the second read is not needed.
- test-impact-selector: maps changed files to the tests that cover them.
- context-budget-governor: writes the checkpoint before compaction.
