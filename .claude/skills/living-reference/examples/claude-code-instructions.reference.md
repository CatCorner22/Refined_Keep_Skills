# [00] Claude Code instructions and enforcement: living reference

Version 1.0. Owner: (owner name). Scope: how Claude Code treats written instructions, and which mechanisms enforce a rule. Does not cover model behaviour, pricing or other products.

Stale-after: 120

The living-reference skill generates the text between each `start` marker and its `end` marker. Regenerate after every edit. Do not edit generated text by hand.

## [01] Attack sheet

- A CLAUDE.md file is context. It is not enforced configuration. §10.01
- Keep each CLAUDE.md file under 200 lines. Imports do not reduce context. §10.02
- To block a tool call whatever Claude decides, use a PreToolUse hook or a deny rule. §20.01, §20.02
- A Bash deny rule matches the command text. It is not a security boundary around the program. §20.02
- A skill's allowed-tools grant lasts for 1 turn and restricts nothing. §30.01

## [02] Contents

<!-- toc:start -->
- [01 Attack sheet](#01-attack-sheet)
- [03 How to read this file](#03-how-to-read-this-file)
- [10 Written instructions](#10-written-instructions)
  - [10.01 Claude treats a CLAUDE.md file as context, not as enforced configuration](#1001-claude-treats-a-claudemd-file-as-context-not-as-enforced-configuration)
  - [10.02 A CLAUDE.md file over 200 lines costs context, and imports do not reduce it](#1002-a-claudemd-file-over-200-lines-costs-context-and-imports-do-not-reduce-it)
- [20 Enforcement](#20-enforcement)
  - [20.01 A PreToolUse hook can block a tool call](#2001-a-pretooluse-hook-can-block-a-tool-call)
  - [20.02 The client enforces permission rules, and a Bash deny rule matches command text only](#2002-the-client-enforces-permission-rules-and-a-bash-deny-rule-matches-command-text-only)
- [30 Skills](#30-skills)
  - [30.01 A skill's allowed-tools grant lasts for the turn that invokes the skill](#3001-a-skills-allowed-tools-grant-lasts-for-the-turn-that-invokes-the-skill)
- [80 Glossary](#80-glossary)
- [85 Changelog](#85-changelog)
- [90 Sources](#90-sources)
- [91 Cite index](#91-cite-index)
- [92 Index](#92-index)
- [99 Health](#99-health)
<!-- toc:end -->

## [03] How to read this file

- Each heading carries a permanent ID in brackets. Refer to a section as `§10.02`, not by position.
- A cite is a short key such as `[S1]` or `[S1 at "Heading"]`. The full citation is in §90.
- Each rule section uses the labels Rule, Elements, Exceptions, Test, Examples, Policy and Open, in that order. A label that has no content is omitted.
- Each rule section ends with `Last verified:` and the date on which someone checked the rule against its source.

## [10] Written instructions

### [10.01] Claude treats a CLAUDE.md file as context, not as enforced configuration

<!-- index: context | CLAUDE.md; written instructions; see also: enforcement -->

- **Rule.** Claude Code loads CLAUDE.md files at the start of every conversation, and Claude treats them "as context, not enforced configuration". [S1 at "CLAUDE.md vs auto memory"]
- **Test.** Ask whether the rule may ever be broken. If it may not, move it to a hook or a deny rule (§20.01, §20.02).
- **Examples.** "Run the linter before each commit" in CLAUDE.md is a request. The same step in a hook runs whatever Claude decides. [S1 at "Claude isn't following my CLAUDE.md"]
- **Policy.** A specific, concise instruction is followed more consistently than a vague one. [S1 at "CLAUDE.md vs auto memory"]
- Last verified: 2026-11-10

### [10.02] A CLAUDE.md file over 200 lines costs context, and imports do not reduce it

<!-- index: file size | 200 lines; imports; see also: context -->

- **Rule.** A file over 200 lines consumes more context and may reduce adherence. Splitting the file into `@path` imports does not reduce context. [S1 at "My CLAUDE.md is too large"]
- **Test.** Count the lines of each CLAUDE.md file. Over 200, trim the file or move part of it into path-scoped rules.
- **Open.** The source gives no measured size of the effect on adherence.
- Last verified: 2026-11-10

## [20] Enforcement

### [20.01] A PreToolUse hook can block a tool call

<!-- index: enforcement | hooks; PreToolUse; blocking; see also: permission rule -->

- **Rule.** A hook on an event that can block enforces a rule whatever Claude decides. For a tool call, that event is PreToolUse. [S2 at "Exit code 2 behavior per event"; S1 at "CLAUDE.md vs auto memory"]
- **Exceptions.** A hook decision does not bypass permission rules. A matching deny rule still blocks the call when the hook returns allow. [S3 at "Precedence among rules, hooks, and mods"]
- **Examples.** A PreToolUse hook that exits with code 2 blocks the tool call. [S2 at "Exit code 2 behavior per event"]
- Last verified: 2026-11-10

### [20.02] The client enforces permission rules, and a Bash deny rule matches command text only

<!-- index: permission rule | deny rule; settings; see also: enforcement -->

- **Rule.** The client enforces settings rules whatever Claude decides. A Bash deny rule matches the command text that Claude writes, so it "isn't a security boundary" around the program. [S1 at "Deploy organization-wide CLAUDE.md"; S3 at "What a Bash rule doesn't match"]
- **Test.** For a program that must never run, do not rely on 1 deny rule. Add a PreToolUse hook (§20.01) or operating-system isolation.
- Last verified: 2026-11-10

## [30] Skills

### [30.01] A skill's allowed-tools grant lasts for the turn that invokes the skill

<!-- index: allowed-tools | skill permissions; pre-approved tools -->

- **Rule.** The `allowed-tools` field lets Claude use the listed tools without a prompt during the turn that invokes the skill. The grant clears with the user's next message, and the field does not restrict which tools are available. [S4 at "Pre-approve tools for a skill"]
- **Test.** Expect a permission prompt for the same command on a later turn, unless a settings rule allows it.
- Last verified: 2026-11-10

## [80] Glossary

- **Context** (UF: written instructions): text that Claude reads and weighs, with no guarantee of compliance. §10.01
- **Enforcement** (UF: hooks, blocking): a mechanism that stops an action whatever Claude decides. §20.01
- **Permission rule** (UF: deny rule): an allow, ask or deny rule in settings that the client applies to a tool call. §20.02

## [85] Changelog

- 2026-11-10 v1.0: created from the 4 documentation pages in §90.

## [90] Sources

- [S1] Anthropic, *How Claude remembers your project*, Claude Code docs. https://code.claude.com/docs/en/memory. Accessed 2026-11-10. Grade: A.
- [S2] Anthropic, *Hooks reference*, Claude Code docs. https://code.claude.com/docs/en/hooks. Accessed 2026-11-10. Grade: A.
- [S3] Anthropic, *Configure permissions*, Claude Code docs. https://code.claude.com/docs/en/permissions. Accessed 2026-11-10. Grade: A.
- [S4] Anthropic, *Extend Claude with skills*, Claude Code docs. https://code.claude.com/docs/en/skills. Accessed 2026-11-10. Grade: A.

## [91] Cite index

<!-- authorities:start -->
- [S1] Anthropic, *How Claude remembers your project*, Claude Code docs — §10.01, §10.02, §20.01, §20.02
- [S2] Anthropic, *Hooks reference*, Claude Code docs — §20.01
- [S3] Anthropic, *Configure permissions*, Claude Code docs — §20.01, §20.02
- [S4] Anthropic, *Extend Claude with skills*, Claude Code docs — §30.01
<!-- authorities:end -->

## [92] Index

<!-- index:start -->
**Symbols**

- 200 lines — *see* file size

**A**

- **allowed-tools** — §30.01

**B**

- blocking — *see* enforcement

**C**

- CLAUDE.md — *see* context
- **context** — §10.01; *see also* enforcement

**D**

- deny rule — *see* permission rule

**E**

- **enforcement** — §20.01; *see also* permission rule

**F**

- **file size** — §10.02; *see also* context

**H**

- hooks — *see* enforcement

**I**

- imports — *see* file size

**P**

- **permission rule** — §20.02; *see also* enforcement
- pre-approved tools — *see* allowed-tools
- PreToolUse — *see* enforcement

**S**

- settings — *see* permission rule
- skill permissions — *see* allowed-tools

**W**

- written instructions — *see* context
<!-- index:end -->

## [99] Health

<!-- health:start -->
_18 sections, 4 sources, 5 index terms. Cadence: 120 days. Generated content last changed 2026-11-10._

- No findings.
<!-- health:end -->
