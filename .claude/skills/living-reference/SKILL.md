---
name: living-reference
description: "Build and maintain a living reference: one Markdown file of sourced rules with permanent section IDs, a source list, and a generated contents list, cite index, subject index and health report. Use when the user asks for a living document, master reference, outline, project bible or single source of truth that must stay current."
compatibility: "Works in claude.ai, Claude Code and the Skills API. The bundled scripts need Python 3.8 or later (standard library only); export also needs pandoc."
metadata:
  version: "2.0.0"
allowed-tools: 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/refresh_reference.py" *)'
---

# Living reference

A reference file that people edit often fails quietly: a rule loses its source, a cite points at nothing, a section goes unchecked for a year. This skill fixes the shape of the file (1 rule in each section, permanent IDs, 1 source list) and regenerates 4 blocks with a script, so that the file reports its own gaps.

## When to use

- The user asks for a living document, master reference, outline, project bible, knowledge file or single source of truth.
- The user will update a file often and look things up in it constantly.
- An existing living reference needs an edit, a refresh, a health check or an export.

## When not to use

- A report that nobody will update: write it directly.
- Formatting a bibliography in a citation style.
- An agent instruction file such as CLAUDE.md — use rules-hygiene, if installed.

## Procedure

To create a file:

1. Settle 4 decisions. Ask once, in 1 message. For each decision the user leaves open, choose and write "Assumed: X".
   - Reader: who looks things up, and which words that reader uses.
   - Unit: organise by rule, principle or decision. Do not organise by source, meeting or date.
   - Scope: 1 sentence on what the file covers and what it does not cover.
   - Cadence: the number of days after which an unchecked section is stale (default 90).
2. Copy `templates/living-reference.template.md` from this skill's directory to the place the user names. Fill in the title, the scope sentence and the `Stale-after:` line.
3. Write 1 `###` section for each rule, in the layout of [references/format.md](references/format.md). The heading states the rule as a sentence. The Rule line ends with a cite.
4. Refresh the file (see Tooling) and clear the findings.

To edit a file:

1. Edit the rule section. Change its `Last verified:` date only when you checked the rule against its source again. A wording edit does not verify a fact.
2. When a rule changes, update the attack sheet in `[01]` and add a dated line to the changelog in `[85]`.
3. Add each new source to `[90]` under a new key. Mark a source that no longer applies as `(retired YYYY-MM-DD)`; keep its key.
4. Refresh the file. Fix every error. Fix each warning, or tell the user why it stays.
5. Report as shown under Output.

## Output

After each refresh, give the user the summary line that the script prints and every finding that remains:

```
notes/reference.md: 18 sections, 4 sources, 5 index terms; cadence 120 days (from the Stale-after line)
Remaining: Warning: §20.02: last verified 2026-03-01, older than the 120-day cadence.
```

Write `Remaining: none` when the script prints `findings: none`.

## Rules

- A section ID must be permanent. Do not reuse an ID and do not renumber. Leave gaps (10, 20, 30) for later topics.
- A source key must be permanent. Do not reuse a key and do not renumber.
- Each rule has 1 home. A source may support many rules.
- Refer to a section as `§12.04`. Do not write "see above".
- Write a claim that has no source as `[cite needed]`. Do not invent a cite.
- Do not edit text between a `start` marker and its `end` marker. The script replaces it.
- Do not delete a rule that stopped being true. Mark it superseded, point to the new section, and log the change.
- Keep the reference in 1 file. The script checks 1 file at a time and does not resolve a cite or a `§` reference across files.

Format details: [references/format.md](references/format.md). Design rules, indexing advice, common mistakes and a review checklist: [references/design-rules.md](references/design-rules.md). Standards behind the format: [references/sources.md](references/sources.md).

## Tooling

Run the bundled scripts from any working directory:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/refresh_reference.py" FILE.md
python3 "${CLAUDE_SKILL_DIR}/scripts/refresh_reference.py" FILE.md --check
python3 "${CLAUDE_SKILL_DIR}/scripts/export_reference.py" FILE.md --to docx
```

`${CLAUDE_SKILL_DIR}` is the directory that contains this SKILL.md. Claude Code fills it in. If the placeholder appears unfilled, replace it with that directory's absolute path.

- `refresh_reference.py FILE.md` rewrites only the lines inside the 4 marker pairs (contents, cite index, index, health). It prints 1 summary line for each file, then each error and each warning. It exits 0 after a refresh, and it exits 2 without writing when it cannot read the file or when the structure is unsafe: a missing or misplaced marker, a code fence or an HTML comment that never closes, or no heading with an ID.
- `--check` writes nothing. It exits 1 when a finding exists or when a generated block is out of date, and 0 when the file is clean. Add `--warnings-ok` to fail on errors only.
- `--stale-days N` overrides the `Stale-after:` line of the file. `--today YYYY-MM-DD` sets the date for a reproducible run.
- The health block holds no day counts. Its date changes only when other generated content changes, so a refresh of an unchanged file on a later day changes nothing.
- `export_reference.py FILE.md --to docx|html|pdf` never changes the source file. It regenerates the blocks in memory, prints the findings on standard error, and reads the text as GitHub-flavoured Markdown. It refuses to replace an existing output file unless you pass `--force`. It removes raw HTML and script links unless you pass `--allow-raw-html`. It needs pandoc. For PDF output it uses the first route that exists: a pandoc PDF engine, then LibreOffice, then a Chromium browser. With none of the 3, it exits 2 and names what it looked for.

The frontmatter pre-approves the refresh command for the turn that invokes this skill. On a later turn, and for every export, a permission prompt is normal. Every option, every finding and each known limit: [references/script-reference.md](references/script-reference.md).

## Without a shell

In a chat with no code execution, apply the same format by hand:

1. Keep the skeleton, the IDs, the source list and the rule layout of [references/format.md](references/format.md).
2. Rewrite the contents list, the cite index and the index yourself after each edit, in the block formats that [references/script-reference.md](references/script-reference.md) shows.
3. In the health block, write `Maintained by hand on YYYY-MM-DD; the script has not checked this file.` Tell the user that the checks did not run.

## Enforcement (optional)

No plugin hook backs this skill, so it is advisory. In a repository, the user may add the `--check` command to CI or to a pre-commit hook. It then fails the build when a finding exists or a block is out of date.

## Related skills

- claim-evidence-pairing, if installed: pairs each claim in a deliverable with a source and a quote before the claim enters the reference.
- retrieval-verification-gate, if installed: checks what a user's document says before you cite it.
- rules-hygiene, if installed: maintains agent instruction files, which are not living references.
- ask-or-assume, if installed: decides when to ask the 4 opening questions and when to proceed on a labelled assumption.
