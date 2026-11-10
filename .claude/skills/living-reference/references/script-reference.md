# Living reference: script reference

Both scripts use the Python standard library only and run on Python 3.8 or later. Run them from any working directory:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/refresh_reference.py" FILE.md
python3 "${CLAUDE_SKILL_DIR}/scripts/export_reference.py" FILE.md --to html
```

## refresh_reference.py

```
refresh_reference.py FILE.md [FILE.md ...] [--check] [--warnings-ok]
                     [--stale-days N] [--today YYYY-MM-DD] [--allow-missing-blocks]
```

| Option | Effect |
|---|---|
| `--check` | Write nothing. Exit 1 when a finding exists or a generated block is out of date. |
| `--warnings-ok` | With `--check`: fail on errors and out-of-date blocks only. |
| `--stale-days N` | Use N days as the cadence for this run. Overrides the `Stale-after:` line. |
| `--today YYYY-MM-DD` | Use this date as today. For tests and reproducible runs. |
| `--allow-missing-blocks` | Accept a file that lacks 1 or more of the 4 marker pairs. |

Options may stand before or after the file names. The script processes every file and returns the highest status.

| Exit status | Meaning |
|---|---|
| 0 | Without `--check`: the file is refreshed or was already up to date. With `--check`: no finding and every block up to date. |
| 1 | `--check` only: a finding exists, or a generated block is out of date. |
| 2 | Usage error, a file that cannot be read or written, text that is not UTF-8, or a structure error. Nothing is written. |

Without `--check` the script exits 0 also when it prints findings. Read the printed findings, or run `--check`.

### Structure errors (exit 2, nothing written)

- A code fence or an HTML comment that never closes.
- A block with a missing marker, 2 start markers or 2 end markers, an end marker above its start marker, or a heading or another marker between the 2 markers.
- A missing block, unless you pass `--allow-missing-blocks`.
- No heading of the form `## [12] Title` in the file.

### Findings

Errors:

- a heading without a valid ID and title;
- a section ID that is used 2 times;
- a cite key that the source list does not hold;
- a malformed cite;
- a source key that appears 2 times, or a source line that is not in the form `- [S12] citation`;
- a `superseded by [S40]` note whose key does not exist;
- a `§` reference to a section that does not exist;
- a `Last verified:` date that is not a valid date or is in the future;
- an index tag without a term, a brace tag that never closes, an alias that points to 2 terms, a `see also` target that is not in the index;
- a `Stale-after:` value that is not a whole number greater than 0, or 2 different values;
- no `[90]` Sources section.

Warnings:

- a section whose `Last verified:` date is older than the cadence;
- a rule section without a `Last verified:` line;
- a section that holds `[cite needed]`;
- a Rule line with no cite;
- a source that no section cites, unless it is marked `(retired ...)`;
- an index term with more than 7 locators, an alias that is also a preferred term, a term spelled 2 ways.

The script has no way to accept 1 single warning. Fix the warning, or run `--check --warnings-ok` and tell the user which warnings remain.

### Block formats

```markdown
<!-- toc:start -->
- [10 Topic](#10-topic)
  - [10.01 Rule heading](#1001-rule-heading)
<!-- toc:end -->

<!-- authorities:start -->
- [S1] Author, *Title*, Container (2025) — §10.01, §20.02
- [S2] Author, *Other title* (2024) — (not cited)
<!-- authorities:end -->

<!-- index:start -->
**P**

- **preferred term** — §10.01; *see also* related term
<!-- index:end -->

<!-- health:start -->
_12 sections, 2 sources, 1 index term. Cadence: 90 days. Generated content last changed 2026-03-14._

- Warning: source [S2] is not cited; cite it, or mark it "(retired YYYY-MM-DD)".
<!-- health:end -->
```

- Contents: every heading with an ID, apart from a level-1 title at the top of the file and a section titled "Contents". Each link uses the anchor that GitHub builds for the heading (lower case, punctuation removed, each space a hyphen, repeats numbered).
- Index: alias lines read `- alias — *see* preferred term`. Terms that start with a digit or a symbol stand under "Symbols".
- Health: the stamp line holds no day count. Its date changes only when other generated content changes. A refresh of an unchanged file on a later day therefore leaves the file byte-identical. When a section crosses the cadence, a warning appears and the date changes.

### How the script writes

- It writes only when a block changes. It writes to a temporary file in the same directory and then replaces the original in 1 step, so an interrupted run leaves the original complete.
- It keeps each existing line ending (LF or CRLF) and a UTF-8 byte-order mark. Generated lines take the line ending that the file uses most.
- It prints UTF-8 whatever the locale is.

## export_reference.py

```
export_reference.py FILE.md [--to docx|html|pdf] [--out PATH] [--force] [--strict]
                    [--allow-raw-html] [--pdf-engine NAME] [--stale-days N] [--today YYYY-MM-DD]
```

| Option | Effect |
|---|---|
| `--to` | Output format: `docx` (default), `html` or `pdf`. |
| `--out PATH` | Output file. Default: the source name with the new extension, next to the source. |
| `--force` | Replace an existing output file. The script never accepts the source file as the output. |
| `--strict` | Export nothing and exit 1 while the health block has a finding. |
| `--allow-raw-html` | Keep raw HTML and script links from the source. |
| `--pdf-engine NAME` | PDF engine for pandoc. Default: the first of `pdflatex`, `xelatex`, `lualatex`, `tectonic`, `typst`, `weasyprint`, `wkhtmltopdf` found on PATH. |

What the script does:

1. It reads the source and regenerates the 4 blocks in memory. It never writes the source file. A file without marker pairs can be exported.
2. It prints every finding on standard error. The exported health block holds the same findings.
3. It removes the block markers and the index tags, outside code only.
4. It runs pandoc with the GitHub-flavoured reader (`-f gfm`), so that the generated contents links resolve and a flag such as `--check` stays as written. The page title comes from the first level-1 heading.
5. Unless you pass `--allow-raw-html`, a pandoc Lua filter removes raw HTML, and it turns a link whose target starts with `javascript:`, `vbscript:` or `data:` into plain text.
6. It writes the output through a temporary file in the output directory.

Exit status: 0 exported; 1 with `--strict` when a finding exists; 2 for every error (usage, unreadable source, structure error, existing output without `--force`, missing output directory, missing pandoc, missing PDF engine, pandoc failure).

Requirements:

- pandoc on PATH. When pandoc is absent, the script uses the copy that the Python package `pypandoc_binary` bundles, if that package is installed.
- For PDF: a pandoc PDF engine. Without one the script exits 2 and names the engines it looked for. Export DOCX or HTML in that case, and convert with another tool if the user needs a PDF.

## Permissions in Claude Code

The skill's frontmatter pre-approves `refresh_reference.py` for the turn that invokes the skill. The grant ends with the user's next message. A later refresh, and every export, goes through the normal permission prompt unless a settings rule allows the command.

## Limits

- 1 file at a time: the script does not resolve a cite or a `§` reference across files.
- The script does not compare the glossary with the index.
- The script does not check that a source line holds a URL or another locator.
- The script does not recognise an indented code block without a fence, and it expects an inline code span to close on its own line.
- The contents anchors follow GitHub's rule. Another renderer can build different anchors.
