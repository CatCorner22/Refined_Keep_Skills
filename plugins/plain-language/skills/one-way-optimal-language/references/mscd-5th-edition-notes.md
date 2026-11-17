# A Manual of Style for Contract Drafting, Fifth Edition (MSCD)

- **Source**: Manual_of_Style_Contract_Drafting_5th_Fifth.pdf (the user uploaded it on 9 November 2026; 961 pages)
- **Type**: book
- **Author/Origin**: Kenneth A. Adams; American Bar Association
- **Published**: 2023 (PDF metadata: 25 August 2023)
- **Ingested**: 2026-11-09 (first pass); re-ingested 2026-11-09 with two chapter audits of ambiguity and vagueness
- **Tags**: drafting-style, contract-language, ambiguity, vagueness, deontic-language, plain-language, typography

## Summary

MSCD sets a comprehensive, rule-based style for the *language* of business contracts — how to say a thing, not what to say. Its core method: for every sentence, pick the "category of contract language" (the kind of meaning) first, then use the one verb structure that MSCD assigns to that category. It also diagnoses the sources of uncertain meaning (ambiguity, vagueness, and four others) in more depth than any other drafting text. Blake uses MSCD as his house style; this ingestion supports the "One Way Optimal Language" adaptation for provider-facing and patient-facing medical text.

## Coverage of this ingestion (read honestly)

- **Read in full:** Ch. 1 (characteristics), Ch. 3 (categories of contract language, ¶¶3.1–3.512 plus 3.536–3.551), Ch. 7 (uncertain meaning), Ch. 10 (references to time), Ch. 11 (part versus whole), Ch. 12 (syntactic ambiguity), Ch. 17 (drafting as writing). The second pass read Ch. 7, 10, 11, and 12 in full, plus Ch. 8's drafting paragraphs (8.130–8.176) and every Ch. 3 and Ch. 13 range that the skill cites on ambiguity or vagueness.
- **Read in key sections:** Intro (why a style manual), Ch. 4 (layout: 4.38–4.46, 4.63–4.66, 4.72–4.81), Ch. 6 (defined terms 6.1–6.10), Ch. 8 (efforts; the second pass skimmed the caselaw sections), Ch. 9 (material, 9.23–9.27, 9.61, 9.125–9.130), Ch. 13 (selected entries: *including*, *only*, *provided that*, *notwithstanding*, *for the avoidance of doubt*, *please*, *very*, *likely*), Ch. 14 (14.1–14.21), Ch. 16 (typography).
- **Headings only:** Ch. 2 (front of contract), Ch. 5 (back of contract), Ch. 15 (internal rules of interpretation), Ch. 18 (amendments), Ch. 19 (letter agreements), Appendices A–B, the rest of Ch. 13.
- **Extraction note:** The PDF text layer uses a font encoding that shifts each character by 29 code points (cid N → chr(N+29)); glyph IDs 177–182 map to – — “ ” ‘ ’; 134 → §. Tables and figures in the PDF are images and did not extract (e.g., Figure 1 quick-reference chart; Tables 1–16 examples).

## Key concepts

- **Optimal contract language (Ch. 1):** twelve principles — not archaic, not legalistic, not confusing (incl. "reader miscues," 1.34), no redundancy (strings, needless elaboration), no repetition, consistent (one word per meaning, 1.57), concise, accessible, does not persuade (no rhetorical emphasis, 1.64), restrains itself in preempting judicial discretion, serves a purpose, and does not have to be simple.
- **Categories of contract language (Ch. 3):** agreement (lead-in only), performance (*hereby* + present tense), obligation (*shall* = "has a duty to" only; *must* for duties on non-subjects and for conditions), discretion (*may*), absence of obligation (*is not required to*), prohibition (*shall not*), policy (present tense; *will* for contingent future events), declaration (*states*, *acknowledges*), intention (*intends that*), recommendation (*recommends*). Conditions: conditional clause, language of obligation with explicit consequence, or language of policy (*It is a condition to…*).
- **The *has a duty* test (3.92, 3.120–3.124):** replace *shall* with *has a duty to*; if the sentence stops making sense, *shall* is wrong.
- **Active voice (3.13–3.26):** use it unless the passive helps; drawbacks of passive = extra words, broken S-V-O order, hidden actor. MSCD allows passive for nonparty/non-person actors and focus on the thing.
- **Hidden-actor family:** buried-actor policies (*payable*, *due*, *subject to*, *eligible for*, 3.336–3.338), nominalizations, which bury verbs (17.7–17.10), *receive* (3.168), *is entitled to* (3.169).
- **May / might (3.231–3.240):** *may* = discretion only; *might* = possibility. *May not* has three meanings (3.307). *May … only* is ambiguous (3.222–3.226).
- **Expectation of relevance (3.213):** specific grants of discretion imply limits; state whether any limit applies to the discretion.
- ***Unless* with activity verbs (3.372–3.385):** replace with *except that if X, A will no longer be required to Y*.
- **Uncertain meaning (Ch. 7):** six sources — ambiguity (lexical, antecedent, contract-reference), not sufficiently specific, mistake, conflict, not addressing an issue, vagueness. Vagueness is a legitimate tool when a drafter uses it with restraint (7.48–7.53).
- **Syntactic ambiguity (Ch. 12):** preceding/trailing modifiers, squinting and poorly placed modifiers, closing modifiers, offsetting commas, that/which, serial comma; never rely on a comma (12.75–12.78); restructure rather than patch (12.90–12.94).
- **Part vs. whole (Ch. 11):** use *one or more*; don't use *and/or* (use *X or Y or both*); resolve *and … or* scope by enumeration.
- **Time (Ch. 10):** don't use *within*; *promptly* and *immediately* both mean "reasonable time"; don't use *periodically*; *upon* + action leaves timing open; day-month-year dates.
- **Numbers (Ch. 14):** never words-and-digits; words for one through ten, digits for 11+ (14.15), but 14.16 allows digits when numbers occur often, and 14.21 lets a drafter use digits throughout.
- **Typography (Ch. 16):** ragged right; no all caps/underline for emphasis; familiar fonts read best; ~45–90 characters per line; consider extra line spacing.
- **Efforts (Ch. 8):** use only *reasonable efforts*; add measures of performance and concrete sub-obligations (8.136, 8.140).

## Notable quotes and data

> "Always start by choosing the category of contract language." — MSCD 3.5

- MSCD 3.102: eliminating *shall* "might be a good idea" for court rules, statutes, and consumer contracts — the hook for using *must* in one-way medical text.
- MSCD 4.63: consider splitting any section or subsection longer than about 15 lines.
- MSCD 17.2: contract sentences run longer than the 20–25 words that guides recommend for general legal writing.
- MSCD 3.16–3.21 (East Texas Copy Systems v. Player): passive "is terminated" let a noncompete end when the employee quit.

## Second-pass audit: what the skill got wrong and what it left out

Two audits (files in `research_notes/Evidence for one way medical text/`: `mscd_ambiguity_audit.md` and `mscd_vagueness_audit.md`) checked every ambiguity and vagueness rule in the one-way-optimal-language skill against the text. The coordinator re-read the key paragraphs (7.52, 10.13, 11.15, 11.105, 12.8, 13.522, 13.638, 3.386) and confirmed each finding below.

- **Wrong citations (2):** MSCD covers *each/every/any/all* at 11.105–11.118, not 11.3–11.11; the ban on all-number dates sits at 10.13, not 10.7–10.10.
- **Misstatements (6):**
  - Numbering alone cannot fix a trailing modifier (12.8).
  - Adding *all of* to a plural noun fixes nothing (11.15).
  - MSCD's alternative to *notwithstanding* is *subject to section X* in the yielding provision, or *except as provided in* (13.638–13.643), not *Even if*.
  - *Must* hints at a condition, but courts default to reading a duty, so the drafter must add a *to*-clause that names what the condition unlocks (3.386–3.391). A skill that uses *must* for every duty loses even that hint.
  - The prudence test for vagueness needs low stakes **and** a commonplace context (7.52), not one or the other.
  - *Likely* states a probability; it is not vague (13.522).
- **Overstated:** 8.144 lists five benchmarks that courts apply when they measure efforts; guidelines and protocols extend that list only by analogy. The skill's third keep condition (no safety-critical action turns on the term) belongs to the skill, not to MSCD.
- **Omitted tools (about 50), most important for one-way medical text:**
  - Inclusive versus exclusive *or* (11.50–11.65).
  - A negative in front of an *or*-list (11.60, 11.66–11.68).
  - *And* in a list of triggers (11.101–11.104).
  - Each, together, or any one for plural actors (11.15–11.35).
  - *Each/every/all/any* with *may* or with failure (11.105–11.118).
  - Day words: *until*, *by*, *through*, *from*, *between* (10.22–10.28).
  - Clock times, midnight, and time zones (10.29–10.56).
  - *Business day* (10.73–10.75).
  - *Notice* before or after (13.615–13.622).
  - *Such as*, *etc.*, *respectively*, the slash, *whichever is later* (13.806–13.815, 13.271–13.274, 13.739–13.748, 13.927–13.928, 13.861–13.869).
  - *Sole discretion* and limits on permissions (3.212–3.215, 3.249–3.269).
  - *Satisfactory to* and good faith versus reasonableness (13.719–13.729, 13.761–13.762).
  - Narrow any vagueness you keep (7.53).
  - Freestanding sub-duties with a deadline, not "at a minimum" (8.136, 8.140, 8.161).
  - *Anyone* in a sensitive context (13.30).
- **Not in MSCD:** a "fully versus partly" rule, a "series-qualifier canon" by name, and a rule on *a* versus *the*.
- **Gap:** the table at 3.549 (*consent not to be unreasonably withheld*) did not extract.

## Relationships

- **Agrees with:** patient-facing-comprehension-research-2026 on active voice, consistency, explicit time and dose, avoiding *may* for possibility, rejecting verbal probability terms (MSCD 13.521 on *likely*), not relying on emphasis-by-capitals.
- **Agrees with:** evidence-one-way-medical-text-2026 that ambiguity in trigger lists, dose limits, and deadlines matters most where the reader acts alone.
- **Contradicts:** evidence-one-way-medical-text-2026 on condition placement: MSCD 3.355 puts a long condition after the main clause, while Dixon's goal-first research (via Steehouder 2000) favors the condition first in branching instructions.
- **Contradicts:** patient-facing-comprehension-research-2026 on (1) *shall* vs. *must* (Federal Plain Language Guidelines, OFR, Lomotan 2010 favor *must*); (2) words vs. digits for 1–10 (USP <17> favors numerals); (3) third person vs. *you/we* (plain-language practice favors direct address); (4) imperative mood (USP <17> uses it); (5) MSCD's permitted passives vs. Blake's absolute active-voice rule.

## Raw notes

- Adams calls the categories "not rules of grammar" but his own system, which rests on standard English (3.6).
- Adams rejects "plain English/plain language" labels for contracts, preferring "standard English" (1.31–1.32).
