---
name: negative-constraint-compiler
description: "Turn never, do not and must not rules into positive rules with a trigger and a check, and turn the ones that can be blocked into deny rules or a hook, because a written rule is context and not enforcement. Use when you write or edit a rules file, or when a written rule was broken anyway."
compatibility: "Works in claude.ai, Claude Code and the Skills API. The bundled CLI needs Python 3.8 or later (standard library only). Enforcement hooks are optional and exist only in the Claude Code plugin form."
metadata:
  version: "2.1.0"
allowed-tools: 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" rules *)'
---
# Negative constraint compiler

A rule in prose is context, not enforcement. A rule that says only "never do Z" names no moment to act and no way to check. This skill rewrites each negative rule as a positive rule with a trigger and a check, and compiles the rules that can be blocked into a layer that blocks.

## When to use
- You are writing or editing CLAUDE.md, AGENTS.md, .cursorrules, GEMINI.md or a SKILL.md that contains negative rules.
- A rule was broken although the file states it.
- The user asks for a rule to be made "hard".

## When not to use
- You are shortening or reorganizing a rules file. Use rules-hygiene, if installed.
- You are about to run a destructive command now. Use scope-and-blast-radius-check, if installed.

## Procedure
For each negative rule:

1. Rewrite it as a positive rule with a trigger. Use the template under Output. The `rules rewrite` sub-command prints the template for each negative rule. You fill it in.
2. Decide the layer by the cost of a violation. If a violation loses data, costs money or is hard to undo, and the rule has no exceptions, compile it. Otherwise the positive rule in prose is enough.
3. Compile the rules that can be blocked. The `rules compile` sub-command prints 2 things:
   - `permissions.deny` entries for `.claude/settings.json`. These need no script, and they load in cloud sessions too.
   - A PreToolUse hook fragment in exec form, for a rule that needs the precision of a regular expression. The fragment contains an absolute script path, which is specific to 1 machine.
4. Show the user the entries and ask before you add them to a settings file.
5. Keep 1 line of prose that points at the enforcement, so the agent knows why a command is denied.

## Output
The rule template, 1 line, no adjectives:

```
When <trigger>, do <positive action>; check <observable>.
```

Example:

```
Before: Never write tests outside tests/.
After:  When you create a test file, put it under tests/; check that its path starts with tests/.
```

A compiled rule and its pointer line:

```
"permissions": {"deny": ["Bash(git push --force *)", "Bash(git push -f *)"]}
Pointer: Force pushes are denied in .claude/settings.json; ask the user if one is needed.
```

## Rules
- The positive rule must name an observable check. "Be careful with migrations" is not a rule.
- Do not keep the negative rule next to its rewrite. Replace it.
- Do not compile a rule that has exceptions. A deny rule cannot tell the exception from the mistake.
- State the limit when you hand over a deny rule or a hook: it covers the command form Claude usually writes. It is not a security boundary.
- In Claude Code, settings rules are enforced by the client. CLAUDE.md shapes behavior and is not a hard enforcement layer.

## Tooling
Run the bundled CLI from any working directory:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" <sub-command>
```

`${CLAUDE_SKILL_DIR}` is the directory that contains this SKILL.md. Claude Code fills it in. If the placeholder appears unfilled, replace it with that directory's absolute path. State lives in `.agent/` at the repository root (override with `AGENT_STATE_DIR`).

- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" rules lint` prints findings with line numbers for the rules files under the current directory: a file over 200 lines, a negative-only rule, a vague rule, a duplicate line, and a rule that a deny rule can block. Add ROOT to lint another directory. It exits 1 when findings exist.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" rules rewrite FILE` prints each negative rule in FILE with the template to fill in. It does not write the positive rule for you.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" rules compile` prints the `permissions.deny` entries and the hook fragment. Add ROOT to compile another directory. It changes no file.

## Without a shell
Ask the user to paste the rules file. Mark each line that contains "never", "do not", "must not" or "avoid". Rewrite each one with the template. For a rule that names a command, write the matching `permissions.deny` entry by hand, in the form `Bash(<command> *)`, and ask the user to add it.

## Enforcement (optional)
This skill produces enforcement and has no hook of its own. The deny rules it prints take effect once the user adds them to a settings file. Until then, the rules are advisory.

## Related skills
- rules-hygiene: keeps the rules file short and current.
- scope-and-blast-radius-check: the check before a destructive command at run time.
