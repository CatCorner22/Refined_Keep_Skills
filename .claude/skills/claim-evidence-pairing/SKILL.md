---
name: claim-evidence-pairing
description: "Pair every load-bearing claim in a written deliverable with its source, a verbatim quote and a confidence level, and quote tool output when it is the evidence. Use when you write a report, a diagnosis such as the bug is in X, a summary of sources, or any number, date or version."
compatibility: "Works in claude.ai, Claude Code and the Skills API. The bundled CLI needs Python 3.8 or later (standard library only). Enforcement hooks are optional and exist only in the Claude Code plugin form."
metadata:
  version: "2.1.0"
allowed-tools: 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" provenance *)'
---
# Claim-evidence pairing

In a written deliverable, a claim without a source reads the same whether it is right or wrong. This skill attaches to each load-bearing claim the source, a verbatim quote and a confidence level, so that a reader can check the claim. A claim is load-bearing when a reader would act differently if it were false.

## When to use
- You are writing a report, a review, a comparison or a summary of sources.
- You are stating a diagnosis, for example "the bug is in X".
- The deliverable contains numbers, dates, versions or error causes.

## When not to use
- The claim is about a document the user supplied. Use retrieval-verification-gate, if installed.
- The claim is that work is done or passing. Use completion-evidence-gate, if installed.
- The text is conversation, a plan or a style remark. Those need no bracket.

## Procedure
1. Mark the load-bearing claims in the draft. Numbers, dates, versions, error causes and "the code does X" are load-bearing.
2. For each claim, find the source: a file and line, a URL, or a tool call.
3. Copy a verbatim quote from the source (default: at most 40 words).
4. Choose the confidence level from the table below.
5. Write the bracket after the claim, and set the verb to match the level.
6. If you find no source, write `unknown` and say what you searched.
7. Record the source for each section, then audit the deliverable (see Tooling).

## Output
```
<claim> [src: <file, URL or tool call> | "<verbatim quote>" | confidence: <level>]
```

Example of a diagnosis:

```
Root cause: `user` is null at auth.ts:42 [src: stack trace | "TypeError: cannot read 'id' of null" | confidence: probable]
```

| Level | Definition | Verb |
|---|---|---|
| established | an official source plus an independent confirmation | "is" |
| probable | one strong source and no contradiction | "appears", "likely" |
| contested | sources disagree; say how | "sources disagree" |
| single-source | one report, not verified | "one report says" |
| unknown | not found; say what you searched | "unknown" |

## Rules
- When tool output is the evidence, quote it: the exit code, the test count, the line. Paraphrase only after the quote.
- A diagnosis is a claim. Give it a bracket.
- The quote must be verbatim. Do not repair or shorten the wording inside the quotation marks.
- `unknown` with what you searched is a valid answer. Do not replace it with a guess.
- The verb must follow the confidence level. Do not write "is" for a single-source claim.
- Where the host has a citations feature, use it for answers from documents. Use the bracket form for tool output and web results.

## Tooling
Run the bundled CLI from any working directory:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" <sub-command>
```

`${CLAUDE_SKILL_DIR}` is the directory that contains this SKILL.md. Claude Code fills it in. If the placeholder appears unfilled, replace it with that directory's absolute path. State lives in `.agent/` at the repository root (override with `AGENT_STATE_DIR`).

- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" provenance add "SECTION" "SOURCE" --quote "QUOTE" --confidence probable` records one source row for a section of the deliverable.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" provenance show` prints all rows. Add a section name to print the rows of 1 section.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" provenance audit FILE` lists the headings in FILE that have no row. It exits 1 when a heading has no row, and 0 otherwise.

The audit works at the level of headings. It does not check each claim, so the bracket after each claim remains your job.

## Without a shell
Write the brackets in the deliverable itself. Before you send it, read the draft once and confirm that each number, date, version and diagnosis has a bracket. Keep a short source list at the end if the deliverable is long.

## Enforcement (optional)
No hook backs this skill. It is advisory on every host.

## Related skills
- retrieval-verification-gate: claims about the user's documents.
- completion-evidence-gate: completion claims.
