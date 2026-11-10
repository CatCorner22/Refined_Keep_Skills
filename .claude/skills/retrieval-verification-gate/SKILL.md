---
name: retrieval-verification-gate
description: "Back every claim about a user's document with the source name, the location and a verbatim excerpt, and say whether the document was only visible, indexed, retrieved or read. Use when about to write that a file, report, attachment or project document says something, or that you reviewed it."
compatibility: "Instruction-only skill. Works in claude.ai, Claude Code and the Skills API."
metadata:
  version: "2.0.0"
---
# Retrieval verification gate

A document can be listed in a project without being in your context. This skill prevents the sentence "I reviewed your report" when no part of the report was loaded. It separates 4 states and ties each claim to an excerpt.

## When to use
- You are about to write "according to your file", "the report shows" or "I reviewed the document".
- A claim rests on a project document, an attachment, a URL or a memory of a document.
- A search over the user's documents returned passages, or returned nothing.

## When not to use
- You have not located the file yet: use inventory-before-fetch, if installed.
- The claim rests on tool output, a web result or your own reasoning: use claim-evidence-pairing, if installed.
- You are describing source code that you read with a file tool in this session. Cite the path and the line; the excerpt is optional.

## Procedure
1. Name the state of the document:

   | State | Meaning | What you may say |
   |---|---|---|
   | Visible | The user sees it in a folder or a project list. | "The file is listed. I have not read it." |
   | Indexed | The host has prepared it for search. | "The file is searchable. I have not read it." |
   | Retrieved | A search returned passages from it. | Claims about those passages only. |
   | Read | You loaded the content, whole or as a range. | Claims about the range you loaded. |

2. If the state is visible or indexed, search or read before you make any claim about the content.
3. For each claim, collect 3 items: the source name, the location (page, section, line or passage number) and a verbatim excerpt. Default: at most 40 words in the excerpt. Quote more when the wording itself is in dispute.
4. Write the claim in the Output form.
5. If a search returns nothing, write the "returned nothing" sentence. Then locate the file with inventory-before-fetch, if installed.

## Output
A claim:

```
Per annual_report.pdf, section 4.2 (retrieved, passage 3): "Revenue rose to 4.1 million".
```

A search that returned nothing:

```
The search for "revenue" returned no passages from annual_report.pdf. I have not read the file.
```

## Rules
- Do not upgrade a state. Retrieved passages are not the whole document. Write "the retrieved passages do not mention X", not "the document does not mention X".
- Quote when the quotation is the evidence. Paraphrase only after the quotation.
- A summary that the host made of a file is in the retrieved state, not the read state. Label it as a summary.
- After compaction, your memory of a file is a summary. Re-verify against the file before you quote a number.
- Do not describe a part of a document that no search returned and that you did not read.
- Where the host has a citations feature, use it for answers about documents.
- In a claude.ai Project that uses retrieval, a search returns passages, not files. Name the file and quote the passage.

## Enforcement (optional)
No hook backs this skill. It is advisory on every surface.

## Related skills
- inventory-before-fetch: finds the file before any claim about it.
- claim-evidence-pairing: the evidence format for claims that do not rest on a user's document.
