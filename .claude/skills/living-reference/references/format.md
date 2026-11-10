# Living reference: file format

This file defines the format that `scripts/refresh_reference.py` reads. The template in `templates/` and the example in `examples/` follow it.

## Skeleton

| ID | Section | Purpose |
|---|---|---|
| `[00]` | Title | Title, version, owner, scope sentence, `Stale-after:` line. |
| `[01]` | Attack sheet | The 10 to 20 lines used most. Each line ends with a `§ID`. |
| `[02]` | Contents | Generated. |
| `[03]` | How to read this file | The conventions, in about 5 bullets. |
| `[10]` to `[79]` | Body | 1 `##` heading for each topic and 1 `###` heading for each rule. |
| `[80]` | Glossary | Preferred term, `UF:` aliases, definition, `§ID`. |
| `[85]` | Changelog | 1 dated line for each change. |
| `[90]` | Sources | The source list: 1 line for each source, keyed `[S1]`, `[S2]`. |
| `[91]` | Cite index | Generated: each source with every section that cites it. |
| `[92]` | Index | Generated: each concept with its sections, with *see* and *see also* entries. |
| `[99]` | Health | Generated: a stamp line and the findings. |

## Headings and section IDs

- Write every heading as `## [12] Title` or `### [12.04] Title`. An ID is 2 digits, or 2 digits, a dot and 2 or 3 digits.
- The script reports every other heading outside code as an error, because the contents, the index and the checks cannot see a section without an ID.
- Assign each ID once. Do not reuse an ID and do not renumber, also when a section moves. Leave gaps (10, 20, 30) so that a new topic fits.
- Make a rule heading informative: write "A short cite needs a key in the source list", not "Short cites".
- Use sentence case. Use at most 4 heading levels.

## Rule section

Write each field as a list item, so that a Markdown renderer shows 1 field on each line. Keep the labels and their order identical in every section. Omit a label that has no content.

```markdown
### [12.04] Heading that states the rule as a sentence

<!-- index: preferred term | alias one; alias two; see also: related term -->

- **Rule.** One sentence. [S3 at 12]
- **Elements.** What must be true for the rule to apply.
- **Exceptions.** When the rule does not apply.
- **Test.** The steps a reader runs.
- **Examples.** A short, concrete case with its outcome. [S7]
- **Policy.** The reason for the rule, in 1 or 2 lines.
- **Open.** What is unverified, contested or pending.
- Last verified: 2026-03-14
```

The script treats a section as a rule section when it holds a `**Rule.**` line, or when its ID has a dot and its topic number is 10 to 79. For a rule section the script expects:

- a `Last verified:` line with a valid `YYYY-MM-DD` date that is not in the future (the last such line in the section counts);
- a cite or the text `[cite needed]` in the Rule field.

## Cross-references

- Write `§12.04` for a section of the same file. The script checks that the section exists.
- For a range (`§10.01-10.03`) the script checks both ends. For a list (`§10.01, §10.02` or `§10.01, 10.02`) it checks each member.
- The script reads a number as a cross-reference only when it follows the section sign directly and has the shape of an ID. Write a statute section with a space (`17 U.S.C. § 107`), so that nobody reads it as a section of the file.
- The script does not check a section sign inside a URL, inside a cite or inside the Sources section.

## Cites

| Form | Meaning |
|---|---|
| `[S3]` | source S3 |
| `[S3 at 12]` | source S3 with a pinpoint (a page, a heading, a paragraph) |
| `[S1, S2]` or `[S1; S2]` | 2 sources |
| `[S1 at 4; S2]` | 2 sources, the first with a pinpoint |
| `[S5-S7]` | sources S5, S6 and S7 |

The script reports every other bracket that starts with `S` and a digit as a malformed cite (for example `[S9 p. 4]` or `[s14]`). It reports a key that the source list does not hold.

## Source list

The source list is the `[90]` section and its sub-sections (for example `### [90.01] Cases`). The script reads source lines only there. A bullet in the body that starts with a cite is a cite, not a source.

```markdown
- [S12] Author or organisation, *Title*, Container (date). URL. Accessed YYYY-MM-DD. Grade: A. Note.
```

- Start each line with `-`, `*` or `+`, then the key in brackets, then the citation. An indented line that follows continues the citation.
- The fields follow CSL variable names (author, title, container-title, issued, URL, accessed). `Grade` is this skill's own field.
- Give each source a locator that a reader can follow: a URL, a DOI, an issue number or a page.
- Do not reuse a key and do not renumber. The script reports a key that appears 2 times.
- Retire a source in place: `- [S12] (retired 2026-05-01, superseded by [S40]) Author, ...`. The script does not report a retired source as uncited, and it checks that the superseding key exists.
- The cite index lists the sources in the order of the source list. It shortens each citation at the URL, the `Accessed` field or the `Grade` field.

Grade each source by its relation to the claim:

| Grade | Meaning |
|---|---|
| A | The primary source for the fact: a vendor page about its own product, a standard, a statute, an original dataset. |
| B | A peer-reviewed study. |
| C | A preprint or a reputable secondary report. |
| D | One person's report, a forum post or an issue thread. |

## Index tags

Tag each rule section with 1 or more tags. The script accepts 2 forms:

```markdown
<!-- index: preferred term | alias one; alias two; see also: related term, other term -->
{{index: preferred term | alias one}}
```

- The comment form is invisible in rendered Markdown. The brace form shows as text; it exists for older files.
- The text before `|` is the preferred term. Use the glossary term.
- Each alias produces a *see* entry that points to the preferred term.
- Each `see also:` term must itself be a term or an alias in the index.
- The script merges terms without regard to case and lists locators in file order.
- The script reports: a tag without a term, a brace tag that never closes, an alias that points to 2 terms, an alias that is also a preferred term, a `see also` target that does not exist, and a term with more than 7 locators.

## Generated blocks

The script owns the lines between these 4 marker pairs. Each marker stands alone on its line.

```html
<!-- toc:start -->          <!-- toc:end -->
<!-- authorities:start -->  <!-- authorities:end -->
<!-- index:start -->        <!-- index:end -->
<!-- health:start -->       <!-- health:end -->
```

Each block needs exactly 1 start marker and 1 end marker, the start above the end, with no heading and no other marker between them. When that is not so, the script names the lines, exits 2 and writes nothing.

## Cadence

Store the cadence in the file, on a line of its own under the title:

```markdown
Stale-after: 120
```

The script reports a section whose `Last verified:` date is older than that number of days. Without the line, the cadence is 90 days. The `--stale-days` option overrides the line for 1 run.

## Code and comments

The script ignores everything inside a fenced code block (backticks or tildes), inside inline code and inside an HTML comment, apart from the comment-form index tag and the block markers. A reference can therefore show its own conventions in a code example.

Limits:

- The script does not recognise an indented code block that has no fence. Put code in a fence.
- An inline code span must close on the line where it opens.

## Glossary and changelog

- Glossary line: `- **Preferred term** (UF: alias one, alias two): definition. §10.01`. `UF` means "used for". The script does not compare the glossary with the index; keep them consistent by hand.
- Changelog line: `- 2026-03-14 v1.2: what changed. §12.04`. Raise the minor version for a changed rule and the major version for a reorganisation.
