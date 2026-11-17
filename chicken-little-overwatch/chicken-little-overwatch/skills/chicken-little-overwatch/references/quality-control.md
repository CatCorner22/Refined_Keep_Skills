# Quality-control checklists

Use these checklists in Step 3 and Step 6 of the workflow. Use only the sections that fit the artifact, and say in the verification register which sections you skipped and why. Record the evidence for every item. An item without evidence has the status "not checked".

## Requirements and traceability

- Give every requirement an ID and an observable acceptance check.
- Map each requirement to a location in the artifact and to a test, inspection, or calculation.
- Check for omissions, not only for incorrect additions.
- List assumptions and unknowns separately. Confirm each consequential assumption with the owner.
- Compare names, dates, definitions, counts, rules, and conclusions across sections or components.
- Rerun earlier checks after every revision, and compare the new version with the old one for unintended deletions.

## Research and factual claims

For each decision-critical claim:

| Question | What to verify |
|---|---|
| Does the source exist? | Title, author, publisher, date, and link. |
| Does it support this exact statement? | The model did not strengthen, broaden, or reverse the finding. |
| Is it the right kind of source? | Prefer the original study, official rule, technical documentation, or underlying dataset. |
| Does it apply here? | Date, jurisdiction, population, product version, and operating conditions match. |
| What did the summary omit? | Limitations, uncertainty, exclusions, and conflicting findings. |
| Are the confirming sources independent? | Several pages that repeat one claim count as one source. |

Then:

- Separate directly supported facts, calculations, interpretations, assumptions, open questions, and recommendations.
- Look for evidence that could disprove the favored conclusion.
- Recalculate consequential totals, rates, formulas, and conversions with an independent tool. Check units, denominators, baselines, rounding, and boundaries.
- Send consequential legal, medical, financial, and safety conclusions to a qualified reviewer.

## Applications

Run the software in a scratch copy and record the environment, version, command, expected result, and actual result. If you cannot run the software, give each behavior claim the status "not checked".

- Build and start from a clean checkout with only the documented steps.
- Separate real behavior from mocks, stubs, and hard-coded responses.
- Walk each core workflow: create, validate, save, restart, retrieve, edit, and confirm persistence.
- Test authorization directly. Change identifiers and call endpoints to reach another user's records.
- Test missing, malformed, oversized, contradictory, duplicate, boundary, and unauthorized inputs.
- Test timeouts, rejected calls, dependency outages, partial writes, interruptions, retries, rollback, and backup restoration.
- Check secret handling, sensitive logging, privacy, and dependency and security scans that actually ran.
- Test the deployed version, not only the development version. Test only a system that the owner controls, with test accounts and test data; never use real credentials or real personal data.
- Use component, integration, and end-to-end tests. None replaces the others.

Verify the tests themselves:

1. Map each requirement to a test.
2. Justify each expected result independently of the implementation.
3. Plant a defect and confirm that the relevant test fails.
4. Identify every mock boundary.
5. Read the actual test output; never accept a claim that the tests passed.

For AI features, evaluate these dimensions separately: source grounding, retrieval, tool choice, action scope, approval behavior, answer quality, latency, and cost. Version the test cases. Rerun them after every prompt or model change.

## Documents

Review in four passes: completeness, meaning and source fidelity, consistency, presentation.

- Build a requirement-to-section table and a claim-to-evidence table.
- Open the exported PDF, Word file, or spreadsheet. Look for clipped text, blank pages, broken links, bad tables, page breaks, broken cross-references, footnotes, placeholders, and missing appendices.
- Reconcile the summary with the body. Never let a summary answer a question that the body leaves open.
- Walk a realistic case: who acts, with what information, by when, under what condition, and what happens when the normal path fails.
- Answer the common what-if events: a missed step, a closed office, a missing owner.

## Review prompts

Give each reviewer one narrow job. Examples:

- "Review only for missing requirements. Quote each requirement and mark it satisfied, partly satisfied, missing, or unverifiable, with locations."
- "Audit the important factual claims. Distinguish *the source supports this* from *the source discusses the same topic*."
- "Find contradictions among the requirements, implementation, tests, documentation, and final report."
- "Design cases that make this fail: invalid inputs, boundaries, unauthorized actions, interrupted workflows, and misleading sources."
- "Do not fix anything. List each defect with severity, evidence, reproduction steps, and the check that will verify the repair."

A second model or a fresh session adds another review pass. It does not prove anything.

## Verification record

| ID | Requirement or claim | Method | Evidence | Status |
|---|---|---|---|---|
| APP-01 | A saved record survives a restart | End-to-end test | Test output and the retrieved record | pass, fail, or unresolved |
| DOC-01 | All requested sections appear | Requirement-to-section comparison | Section locations | pass, fail, or unresolved |
| RES-01 | A key statistic is accurate and applies here | Source inspection and recalculation | Source passage and calculation | verified or unresolved |

## Release gate

1. List every open defect by severity.
2. Confirm that no blocking defect remains.
3. Confirm that Flags states every unresolved or not-checked status plainly.
4. Confirm that the owner has accepted, in writing and with scope, any remaining Critical or High risk.
5. State the readiness decision and the limits of the review.
