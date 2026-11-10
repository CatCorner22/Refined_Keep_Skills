# Living reference: design rules, indexing and review

A living reference serves 2 readers at once: the reader who needs 1 fact in 10 seconds, and the reader who needs to trust that the whole file is still true. The rules below follow from those 2 needs. [sources.md](sources.md) lists the standards behind them.

## Why the format looks like this

- Organise by rule, because a reader looks up a rule. A source can support many rules; a rule has 1 home.
- Give every section a permanent ID, because links, notes and memory point at IDs. A renumbered file breaks all of them.
- Keep 1 source list with short keys, because a short cite is safe only when the full citation is easy to find.
- Generate the contents, the cite index, the index and the health block, because hand-kept copies drift from the text.
- Store the cadence in the file, so that every run and every export applies the same number of days.

## Writing rules

- Write for the 10-second reader first: the answer in the heading, the rule in the first line, the cite at the end of the line.
- Put 1 idea in each paragraph. Use a table for parallel facts (elements, thresholds, deadlines) and a list for steps. Use prose only for the reason behind a rule.
- Use bold for field labels only. Use italics for titles and for *see* and *see also*. Do not underline. Do not combine bold and italic.
- Write dates as `YYYY-MM-DD`. Give every number its unit. Do not write "recently", "currently" or "the new version".
- Put a number, its unit, its source and its date on 1 line.
- Keep a table to 6 columns or fewer.
- Use a callout only for something that harms the reader who misses it: `> **Warning.**` or `> **Changed 2026-03-14.**`.
- Keep the attack sheet to 20 lines or fewer. Rewrite it whenever a rule below it changes.

## Indexing

The script builds the index from the tags. Choosing the tags is the author's work.

- Tag the concept that the reader will look for, not every noun. Ask: "If I forgot where this is, which word would I search for?" Add that word.
- Use the reader's word as the preferred term and the source's word as an alias. A clinician and a member of the public look up the same condition under different words.
- Add an alias for each synonym that the audience uses. A reader's word must not end nowhere.
- Split a term that points at more than 7 sections into narrower terms, for example `negligence, duty` and `negligence, breach`. The script warns above 7.
- Use the glossary term as the preferred term.

## Common mistakes

| Mistake | Correction |
|---|---|
| Sections named by date or meeting | Reorganise by rule. |
| 1 section for each document read | Put sources in the source list and rules in the body. |
| A number with no source and no date | Add both, or move the number to the Open field. |
| Renumbering sections or sources | Leave gaps and keep every ID and key. |
| A tag on every noun | Tag what the reader will search for. |
| A rule that silently disappears | Mark it `(superseded YYYY-MM-DD by §12.05)` and log the change. |
| A hand-kept contents list or index | Let the script generate it. |
| A new `Last verified:` date after a wording edit | Change the date only after you checked the source again. |

## Review checklist

Run this list before you tell the user that the file is ready.

- The scope sentence is present.
- Each attack-sheet line ends with a `§ID`.
- Each rule section uses the fixed labels in the fixed order.
- Each Rule line has a cite or `[cite needed]`.
- Each rule section has a `Last verified:` date that someone earned by checking the source.
- Each source line has a locator that a reader can follow, and a grade.
- The index terms are the reader's words.
- The changelog has a line for this change.
- The refresh ran after the last edit, and the user has seen every finding that remains.
