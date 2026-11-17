---
name: stable-architecture
description: "Design code that avoids houses of cards: clear module boundaries, dependency direction, fail-fast invariants, and replaceable adapters. Use when structuring a feature, splitting services, reviewing coupling, or when changes in one file break unrelated areas. Scope boundary: line-level clarity → `clean-minimal-code`; defining what done looks like → `deliverable-first`; running tests while editing → `real-time-testing`."
metadata:
  version: "2.0.0"
  source: "CatCorner22/Cursor_Skills@5cf5106 skills/coding/stable-architecture"
---
# Stable architecture

**Goal:** Removing or rewriting one layer does not collapse unrelated features. Dependencies point **toward stability** (domain rules), not toward frameworks.

## Dependency rule (non-negotiable)

```
UI / HTTP / CLI  →  application services  →  domain  ←  adapters (DB, APIs)
```

- **Domain** must not import framework, ORM, or UI.
- **Adapters** implement ports defined by domain/application.
- **Framework** (Next.js routes, FastAPI handlers) is thin glue.

Violating this creates a house of cards: one ORM tweak breaks UI assumptions.

## Layers (minimal)

| Layer | Contains | Must not contain |
|---|---|---|
| **Domain** | Entities, invariants, pure rules | SQL, HTTP, React |
| **Application** | Use-cases, orchestration, transactions | JSX, request objects leaking everywhere |
| **Ports** | Interfaces/types for external systems | Implementations |
| **Adapters** | DB repos, HTTP clients, email senders | Business rules |
| **Delivery** | Routes, components, CLI | Complex branching logic |

Skip layers you do not need — a script may be delivery + one function. Do not add folders "for architecture."

## Houses of cards — detect and fix

| Symptom | Likely cause | Stabilizer |
|---|---|---|
| Changing A breaks B with no obvious link | Hidden shared mutable state | Pass data explicitly; narrow scope |
| Circular imports | Domain ↔ infra coupling | Extract port; move impl to adapter |
| "God" module (>500 lines, many reasons to change) | Missing seams | Split by use-case, not by technical type |
| Feature flags scattered in 20 files | No single policy point | One capability module |
| Tests need full app boot | No ports | Fake adapter behind interface |
| Types duplicated at every layer | Leaky DTO mapping | Map at boundary once |

## Fail fast

- Validate at **system boundaries** (HTTP body, env vars, user input).
- Assert **invariants** inside domain (throw domain errors, not strings).
- Prefer **compile-time** guarantees (TypeScript strict, Rust types) over runtime checks deep in the stack.
- **No silent defaults** for security or money (`|| 'admin'` is a card collapse waiting to happen).

## Replaceability test

Before merging, ask:

1. Can I swap the database adapter in one PR without touching domain?
2. Can I test the use-case with an in-memory fake?
3. If Next.js were removed, is there still a testable core?

If any answer is no for a non-trivial feature, add a seam before adding more features on top.

## Vertical slices over horizontal layers

Prefer:

```
Feature A: route → use-case → adapter (complete)
Feature B: route → use-case → adapter (complete)
```

Over:

```
All routes → all services → all repos (half-wired, untestable middle)
```

## Monolith vs services

Default: **well-bounded monolith** until proven scale/out-of-team needs split.

Split when: independent deploy cadence, different scaling profile, or hard failure isolation requirement — not because "microservices are modern."

## Handoffs

- What to build first → `deliverable-first`
- Proof while building → `real-time-testing`
- UI composition → `ui-engineering`

## In Claude Code

This skill is part of the `coding` plugin. Load a skill that this text names with the Skill tool: `coding:<name>` for a skill of this plugin, or the name that the session lists for a skill of another pack. If the session does not list a named skill, continue without it.
