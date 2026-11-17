---
name: deliverable-first
description: "Plan and implement features by defining the final deliverable first, then reverse-engineering the smallest code path to it. Use when starting a feature, API, UI screen, or refactor; when the user says begin with the end in mind, work backwards, or what should this look like when done. Produces acceptance criteria, contracts, and UI state maps before bulk coding. Scope boundary: after the deliverable is defined, continuous test execution belongs to `real-time-testing`; structural boundaries belong to `stable-architecture`."
metadata:
  version: "2.0.0"
  source: "CatCorner22/Cursor_Skills@5cf5106 skills/coding/deliverable-first"
---
# Deliverable-first engineering

**Rule:** Do not write production code until you can describe the **finished artifact** a user, API client, or reviewer would see. Then derive the implementation backward from that artifact.

## Step 1 — Name the deliverable (one sentence)

Examples:
- "User can reset password via email link and land on a signed-in dashboard."
- "`POST /v1/invoices` returns 201 with `{ id, status: 'draft' }` and persists to Postgres."
- "Settings page shows current theme, toggles light/dark, persists across reload."

If you cannot name it in one sentence, the scope is not ready.

## Step 2 — Specify the artifact (pick all that apply)

### API / backend
- Request/response JSON (happy path + error shapes)
- Status codes and idempotency behavior
- Auth requirement per endpoint
- One example curl or typed client call that **must pass** when done

### UI
- **States:** loading, empty, error, success (see `ux-engineering`)
- **Wireframe in words:** primary action, secondary actions, what is read-only
- **Responsive breakpoint** that matters (usually mobile + desktop)

### CLI / script
- Exact invocation, stdout/stderr examples, exit codes

### Data
- Entities touched, invariants ("balance never negative"), migration yes/no

Write these into a short **Acceptance checklist** (3–7 checkboxes). That checklist becomes the test plan for `real-time-testing`.

## Step 3 — Reverse-engineer the path (outside-in)

List layers from the deliverable **inward**, not from files **outward**:

```
UI event / HTTP request
  → application use-case (orchestration)
    → domain rule (pure where possible)
      → port (interface)
        → adapter (DB, HTTP client, filesystem)
```

For each layer, ask: *What is the smallest thing I can build and verify that moves the checklist one checkbox forward?*

Implement **vertical slices** (one checkbox end-to-end) before horizontal layers (all routes, then all UI).

## Step 4 — Contract before code

Lock interfaces before bodies:

| Layer | Contract artifact |
|---|---|
| HTTP | Route signature + Zod/OpenAPI/schema + example fixtures |
| UI | Props/types + state enum + Storybook story or static mock |
| Module | Function signature + doc comment with pre/post conditions |

Changing a contract after two adapters depend on it is a architecture smell — get contracts stable early (`stable-architecture`).

## Step 5 — Slice implementation loop

For each acceptance checkbox:

1. Write or extend the **narrowest failing check** (test, type error, or lint) — see `real-time-testing`.
2. Implement the minimum code to pass.
3. Refine with `clean-minimal-code` (delete, rename, inline).
4. Mark checkbox done only with command output as evidence.

## Anti-patterns

| Smell | Fix |
|---|---|
| "I'll add tests later" | Checkbox is not done; run `real-time-testing` |
| Scaffold 20 files upfront | One vertical slice first |
| UI built before API contract | Define JSON + errors, then UI states |
| Abstractions before second use case | YAGNI until duplication hurts |
| Deliverable is "clean up the codebase" | Name measurable outcomes (coverage, deleted modules, perf metric) |

## Handoffs

- Boundaries between modules/services → `stable-architecture`
- Watch mode / test commands → `real-time-testing`
- Component structure / tokens → `ui-engineering`
- Loading/error/copy/a11y → `ux-engineering`

## In Claude Code

This skill is part of the `coding` plugin. Load a skill that this text names with the Skill tool: `coding:<name>` for a skill of this plugin, or the name that the session lists for a skill of another pack. If the session does not list a named skill, continue without it.
