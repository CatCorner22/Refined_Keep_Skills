---
name: clean-minimal-code
description: "Write clear, minimal code: fewer lines with the same behavior, established naming, SOLID and YAGNI, no premature abstraction. Use when implementing or reviewing functions, modules, or refactors; when the user wants clean code, less boilerplate, simplify, or remove unnecessary complexity. Scope boundary: system-wide boundaries and coupling → `stable-architecture`; test loop while editing → `real-time-testing`; React-specific perf → `react-best-practices`."
metadata:
  version: "2.0.0"
  source: "CatCorner22/Cursor_Skills@5cf5106 skills/coding/clean-minimal-code"
---
# Clean minimal code

**Goal:** The reader understands intent in one pass. Every line earns its place.

## Core rules

1. **Name for intent, not mechanism** — `calculateInvoiceTotal`, not `doStuff`.
2. **Functions do one thing** — if you need "and" to describe it, split it.
3. **Prefer pure functions** — same inputs → same outputs; push I/O to edges.
4. **YAGNI** — no interfaces, factories, or base classes until the **second** real use case.
5. **Delete > comment** — remove dead code; git remembers.
6. **Early return** — guard clauses beat nested `if` pyramids.
7. **Data over cleverness** — plain objects/structs beat inheritance hierarchies.

## Minimize lines (without golfing)

| Instead of | Prefer |
|---|---|
| Wrapper that only forwards one call | Call through directly |
| Config object with 12 optional fields | Required params + one options bag for rare flags |
| `if (x) { return true } else { return false }` | `return x` |
| Temporary variable used once | Inline when still readable |
| Custom `Result` type for one call site | Throw or return union at boundary |
| Comment explaining *what* | Rename so the code explains *what* |

**Line count is a proxy, not the goal.** A 40-line function with clear steps beats five 8-line functions with opaque names.

## SOLID (practical subset)

| Principle | Application |
|---|---|
| **S** Single responsibility | Module changes for one reason |
| **O** Open/closed | Extend via composition/data, not editing core switches |
| **L** Liskov | Subtypes honor caller expectations (especially errors) |
| **I** Interface segregation | Small function types; don't force unused methods |
| **D** Dependency inversion | Domain depends on interfaces; adapters implement them |

Do not introduce interfaces for single implementations.

## Established patterns (prefer these)

- **Parse, don't validate** at boundaries (Zod/schema in, typed domain inside)
- **Repository / gateway** only when ≥2 storage backends or heavy test doubles needed
- **Command/query split** when reads and writes have different scaling needs
- **Immutability** for shared state; mutate locally in tight loops when profiled
- **Explicit errors** at boundaries; don't leak stringly-typed errors inward

## Refactor pass (after green tests)

Run after `real-time-testing` is green for the slice:

1. Rename until a new reader needs no comments.
2. Inline functions called once if names add no clarity.
3. Extract only when a block has a **reused** nameable concept (≥2 call sites or test isolation).
4. Remove unused imports, params, and branches.
5. Re-run the same test command — still green.

## Review checklist

- [ ] Can any function lose 30%+ lines without losing behavior?
- [ ] Any abstraction with one implementation?
- [ ] Any boolean flag parameter that should be two functions?
- [ ] Any `any` / untyped escape hatch fixable at the boundary?
- [ ] Names consistent with the rest of the repo?

## Boundaries

- Module/package boundaries → `stable-architecture`
- Acceptance criteria before coding → `deliverable-first`

## In Claude Code

This skill is part of the `coding` plugin. Load a skill that this text names with the Skill tool: `coding:<name>` for a skill of this plugin, or the name that the session lists for a skill of another pack. If the session does not list a named skill, continue without it.
