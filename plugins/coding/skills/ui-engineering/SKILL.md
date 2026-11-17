---
name: ui-engineering
description: "Modern UI implementation: component composition, design tokens, Tailwind/shadcn/Radix stacks, responsive layout, and accessible markup foundations. Use when building or refactoring UI components, pages, design systems, or styling. Scope boundary: React/Next render performance → `react-best-practices`; shadcn CLI install and registries → `shadcn`; App Router data fetching and RSC → `nextjs`; UX flows and copy → `ux-engineering`."
metadata:
  version: "2.0.0"
  source: "CatCorner22/Cursor_Skills@5cf5106 skills/coding/ui-engineering"
---
# UI engineering

Build UIs that are **composable, token-driven, and boring to maintain** — not one-off styled divs.

## Stack defaults (modern web)

| Concern | Preferred | When to diverge |
|---|---|---|
| Components | React function components + TypeScript | Existing Vue/Svelte repo — match repo |
| Primitives | Radix UI / native semantic HTML | No React — use platform primitives |
| Styling | Tailwind CSS + CSS variables for tokens | Existing CSS Modules — extend, don't rewrite |
| Component kit | shadcn/ui (copy-in, you own code) | MUI/Chakra legacy — migrate incrementally via `shadcn` |
| Icons | lucide-react (direct imports, not barrel) | Match repo icon set |
| Forms | react-hook-form + Zod resolver | Server Actions + progressive enhancement in Next |

Follow repo conventions when they differ; do not rip working UI for stack purity.

## Design tokens (do this before pixel-pushing)

Define once, reference everywhere:

```css
/* semantic tokens — not raw hex in components */
--background, --foreground, --primary, --muted, --border, --radius
```

- **Spacing scale:** 4px base (Tailwind default)
- **Type scale:** 2–3 body sizes + 1–2 display; limit font families to 1–2
- **Radius/shadow:** 2 levels max for cohesion

Components consume tokens (`bg-background`, `text-muted-foreground`), not `#1a1a1a`.

## Component structure

```
components/
  ui/           ← shadcn primitives (Button, Input) — thin, unmodified when possible
  features/     ← domain-specific (InvoiceTable, UserMenu)
  layouts/      ← shells (AppShell, SettingsLayout)
```

**Rules:**
- **ui/** has no business logic and no data fetching.
- **features/** compose ui/ + hooks; one primary user task per folder.
- Props are **explicit** — prefer `{ invoice: Invoice }` over spreading unknown bags.

## Composition patterns

| Pattern | Use |
|---|---|
| **Compound components** | Tabs, accordion — shared context, flexible children |
| **Slot / `asChild`** | Radix — style triggers without wrapper div soup |
| **Variants** | `cva` or `tailwind-variants` for Button size/intent — not 12 boolean props |
| **Controlled vs uncontrolled** | Document which; default uncontrolled for simple inputs |

## Responsive & layout

- Mobile-first Tailwind breakpoints (`sm:`, `md:`).
- Prefer **CSS Grid/Flex** over absolute positioning for page layout.
- Touch targets ≥ 44×44px; do not rely on hover-only affordances.

## Deliverable-first UI

Before JSX, list from `deliverable-first`:

1. States: loading, empty, error, success
2. Primary + secondary actions
3. Data shape props require

Implement **empty and error states first** — they expose missing API contracts early.

## Quality bar

- [ ] Semantic HTML (`button` not `div onClick`, `nav`, `main`, headings in order)
- [ ] Focus visible on interactive elements
- [ ] No inline styles except dynamic values
- [ ] Story or test for non-trivial component states
- [ ] `real-time-testing`: component test or typecheck after edits

## Handoffs

| Need | Skill |
|---|---|
| User flows, heuristics, a11y audit depth | `ux-engineering` |
| shadcn add/update CLI | `shadcn` |
| Next.js Server Components | `nextjs` |
| Perf waterfalls / bundle | `react-best-practices` |

## In Claude Code

This skill is part of the `coding` plugin. Load a skill that this text names with the Skill tool: `coding:<name>` for a skill of this plugin, or the name that the session lists for a skill of another pack. If the session does not list a named skill, continue without it.
