---
name: unambiguous-language
description: Apply Blake Reagan's always-on language rules to every reply and document that Claude writes for him — active voice, "might" for possibility, and a living list of ambiguous words and Ken Adams MSCD usages that Claude avoids, each with a precise replacement.
metadata:
  version: "1.0.0"
  source: "CatCorner22/Cursor_Skills@5cf5106 skills/legal/unambiguous-language"
---
# Unambiguous Language

## Purpose

This skill keeps every sentence Claude writes for Blake to one meaning. It combines three rule sets:

1. Active voice in every sentence.
2. A living list of ambiguous words that Claude never uses unless quoting a source.
3. Ken Adams's recommendations from *A Manual of Style for Contract Drafting* (MSCD, 5th ed. 2023) and his blog, Adams on Contract Drafting.

## When this skill applies

Apply this skill to everything Claude writes for Blake: chat replies, documents, contracts, emails, skills, and memory entries. Apply it together with any other writing skill (for example, mscd-contracts or one-way-optimal-language). If two skills conflict, the stricter rule controls.

## Procedure

Run every step on every draft, in this order.

**Step 1. Draft.** Write the full text first.

**Step 2. Voice check.** For each sentence, find the main verb. If a form of "be" (is, are, was, were, be, been, being) or "get" comes before a past participle ("was signed," "got approved"), the sentence uses passive voice. Rewrite it so the actor comes first as the subject: "The board approved the deal," not "The deal was approved." If nobody knows the actor, say so in active voice: "An unknown person signed the form." A linking verb before an adjective ("The clause is ambiguous") is not passive voice and needs no change.

**Step 3. Word check.** Compare every word against List A, List B, and List C below. Replace each hit with the replacement the list gives.

**Step 4. Possibility check.** Find each "may." If it expresses possibility, replace it with "might." If the event is likely and a party is the subject, "expects to" also works. Keep "may" only for permission or discretion.

**Step 5. Time check.** For every time period, state whether each end date counts ("through and including March 1"). Never use "midnight"; write "at the start of March 2" or "at the end of March 1" instead. Include the time zone when the parties sit in different zones.

**Step 6. Small-word check.** Look at every "and," "or," "all," "any," "each," "every," plural noun, and opening or closing modifier. Ask: "Can a reader find a second meaning?" If yes, restructure the sentence. Enumerate the items, split the sentence, or move the modifier next to the word it modifies.

**Step 7. Final pass.** Run Steps 2 through 6 again on the revised text. Revisions can introduce new problems.

## Contingencies

- **Quoting a source.** Keep the source's exact words inside quotation marks, even if they contain a word on the lists. If the meaning matters and Claude can verify which meaning the source intends, state that meaning in a separate sentence.
- **Term of art in a statute, regulation, or opinion.** Quote the term, then explain it in plain words.
- **Blake asks about a word on the lists.** Mention the word in quotation marks. Mentioning a word differs from using it.
- **Revising Blake's own wording.** Flag each word on the lists, give the replacement, and explain the grammar rule behind the change.
- **No precise replacement exists.** Define the term at first use, then use it the same way every time.
- **Unsure whether a word has a second meaning.** Treat the word as ambiguous and replace it.
- **Proper names.** Leave names of people, places, and products as they are.
- **Counterparty insists on a traditional term.** Explain Adams's reasoning, and leave the final decision to Blake.

## List A: Words with two meanings (never use unless quoting)

| Word | Meaning 1 | Meaning 2 | Use instead |
|---|---|---|---|
| sanction | approve | penalize | approve, authorize / penalize, penalty |
| table (verb) | postpone (US) | propose for discussion (UK) | postpone / propose |
| moot | debatable or irrelevant | raise for discussion (verb) | unsettled / irrelevant / raise |
| oversight | supervision | omission | supervision / omission, error |
| overlook | consider or supervise | fail to notice | review, supervise / miss |
| transparent | invisible | obvious | see-through / obvious, open |
| scan | glance at | examine closely | skim / examine |
| fine (as a rating) | excellent | merely acceptable | excellent / acceptable |
| toss out | suggest | discard | suggest / discard |
| cleave | split | cling | split / cling |
| dust (verb) | remove dust | sprinkle powder | clean / sprinkle |
| bolt (verb) | fasten | flee | fasten / flee |
| left (meaning remaining or departed) | still there | gone | remaining / departed |
| rent, lease (verb) | act as landlord | act as tenant | use only with "to" or "from," and name the landlord and the tenant |
| forthwith | depends on context | depends on context | "within [number] days after [event]" |
| midnight | start of a day | end of a day | "at the start of [date]" / "at the end of [date]" |
| biweekly, bimonthly, biannual, biennial, and every other "bi-" frequency word | twice per period | once every two periods | write the interval: "every two weeks," "twice a year" |
| may (for possibility) | permission | possibility | "might" for possibility; "may" for discretion only |

## List B: Adams MSCD strike list (never use unless quoting)

| Avoid | Use instead |
|---|---|
| "best efforts"; "reasonable best efforts"; "commercially reasonable efforts" | "reasonable efforts" |
| "material" | "nontrivial" or "dealbreaker" (pick the meaning the parties intend) |
| "represents and warrants" | "states" |
| "provided that"; "provided, however, that" | "but" (after a period), "except," or "on condition that" |
| "including without limitation"; "including but not limited to" | "including" |
| "indemnify and hold harmless"; "hold harmless" | "indemnify" |
| "at its sole discretion"; "may at its sole discretion" | "may" |
| "may require" | "At X's request, Y shall ..." |
| "condition precedent"; "condition subsequent" | state the condition directly with an "if" clause |
| "except as provided below" and every other cross-reference without a location | cite the section number |
| "terms and conditions" | "terms" |
| "true and correct" | "accurate" |
| other synonym doublets and triplets | one word |

Adams's 2009 "Keep This Stuff Out of Your Contracts" post also lists these phrases to omit: "at no time"; "covenant"; "for the avoidance of doubt"; "hereinafter referred to as"; "in consideration of the foregoing"; "incorporated by reference"; "in lieu of"; "in the event of"; "in witness whereof"; "it being understood"; Latinisms; "moral turpitude"; "notwithstanding"; "now therefore"; "of any kind"; "prior to"; "pursuant to"; "reserves the right to"; and "(s)" for plurals. Common plain-English replacements: "in the event of" becomes "if"; "prior to" becomes "before"; "pursuant to" becomes "under"; "in lieu of" becomes "instead of."

## List C: Words that stay, with limits

| Word | Rule |
|---|---|
| shall | Use only to mean "has a duty to," with the party that has the duty as the subject. |
| may | Use only for permission or discretion. |
| might | Use for every expression of doubt, uncertainty, or possibility. |
| such | Use only to mean "of this kind." Never use it as a pointing word; use "the," "this," "that," "these," or "those." |
| deem | Use only to create a legal fiction. |
| from, to, until, between (time) | Never use alone to mark a period. State whether each end date counts. |
| and, or, all, any, each, every, plural nouns, modifiers | Run the Step 6 check on each one. |

## Pending verification (do not apply until Claude verifies the item)

- **and/or.** Adams analyzes it in his 2006 St. John's Law Review article with Alan Kaye, but Claude has not yet confirmed his recommendation from an accessible source.

## Maintaining the living list

When Blake or Claude identifies a new ambiguous term:

1. Confirm the second meaning in at least one reliable source: a dictionary, a usage guide, MSCD, or Adams's blog.
2. Add a row with the word, both meanings, the replacement, and the source.
3. Add the same entry to Blake's memory preferences, if this session has a memory tool. If it does not, tell Blake that this step is open.
4. Propose the skill update so Blake can review and save it.
5. Commit the same change to skills/legal/unambiguous-language/SKILL.md in the catcorner22/cursor_skills repo, which holds the master copy of this skill. If this session cannot write to that repo, tell Blake that this step is open.
6. Tell Blake in one line what the update adds.

## Sources

- Adams, *A Manual of Style for Contract Drafting* (5th ed. 2023), index: https://www.adamsdrafting.com/wp-content/uploads/2023/02/MSCD5-Index.pdf
- Keep This Stuff Out of Your Contracts: https://www.adamsdrafting.com/keep-this-stuff-out-of-your-contracts/
- "Provided That": https://www.adamsdrafting.com/provided-that/
- Another Kind of "Including" Ambiguity: https://www.adamsdrafting.com/another-kind-of-including-ambiguity/
- English Case on "Best Endeavours" and "Reasonable Endeavours": https://www.adamsdrafting.com/english-case-best-reasonable-endeavours/
- "Material" Is Ambiguous. That's Big News: https://www.adamsdrafting.com/material-is-ambiguous-thats-big-news/
- "May" and "Might" and Degrees of Possibility: https://www.adamsdrafting.com/may-and-might-and-degrees-of-possibility/
- "May Require": https://www.adamsdrafting.com/may-require
- "At Its Sole Discretion" Outside Its Normal Habitat: https://www.adamsdrafting.com/?p=10812
- "Terms of Art That Can't Be Replaced": https://www.adamsdrafting.com/terms-of-art-that-cant-be-replaced/
- Busk, Plain Language, Michigan Bar Journal (Feb. 2015): https://www.michbar.org/file/barjournal/article/documents/pdf4article2562.pdf
- Table (parliamentary procedure): https://en.wikipedia.org/wiki/Table_(parliamentary_procedure)
- Travers Smith, Top 10 Contract Drafting Tips: https://www.traverssmith.com/knowledge/knowledge-container/avoiding-an-abu-qatada-situation-our-top-10-contract-drafting-tips/
- Lawyerspeak & Contranyms: https://readthereporter.com/lawyerspeak-contranyms/