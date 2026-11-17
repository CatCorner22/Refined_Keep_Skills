---
name: rules-hygiene
description: "Keep agent instruction files such as CLAUDE.md, AGENTS.md and .cursorrules short, specific and current, with the most-used facts first and hard constraints moved to settings or hooks. Use when you create or edit a rules file, when a rules file has grown long, or when the agent keeps ignoring a written rule."
compatibility: "Works in claude.ai, Claude Code and the Skills API. The bundled CLI needs Python 3.8 or later (standard library only). Enforcement hooks are optional and exist only in the Claude Code plugin form."
metadata:
  version: "2.1.0"
allowed-tools: 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" rules lint *)'
---
# Rules hygiene

A rules file is loaded at the start of every session and stays in the context for all of it. Every line costs context in every task, and a long file makes each rule easier to miss. This skill keeps the file short, puts the most-used facts first, and moves hard constraints to a layer that can block.

## When to use
- You are creating or editing CLAUDE.md, AGENTS.md, GEMINI.md, .cursorrules or a similar rules file.
- A rules file has grown past the default length of 200 lines.
- The agent ignored a rule that the file states.

## When not to use
- You are rewriting a negative rule or turning it into a deny rule. Use negative-constraint-compiler, if installed.
- The material is a procedure for 1 kind of task. Put it in a skill or in the project docs.

## Procedure
1. Lint the rules files (see Tooling). Read each finding with its line number.
2. Check the file against this checklist:
   - The file is short (default: at most 200 lines).
   - The first lines carry what the agent needs most often: the build and test commands, and the facts the agent cannot find in the code.
   - Each rule is phrased positively and names its trigger: "When you edit X, run Y."
   - Task-specific material, such as a deploy runbook or a migration guide, lives in a skill or in the docs. The rules file references it.
   - Each hard constraint is enforced mechanically, by a permission rule or a hook. The rules file keeps 1 pointer line.
   - The file does not repeat what a linter or CI enforces. It says "run `make lint`", not the style guide.
   - The file has a dated `Last reviewed:` line.
3. Fix the findings, starting with the ones that remove lines.
4. Lint again, and update the `Last reviewed:` date.

## Output
A short report, then the edited file:

```
CLAUDE.md: 264 lines, now 131.
Moved: deploy runbook to docs/deploy.md (referenced on line 12).
Rewritten: 6 negative rules as positive rules with triggers.
Mechanical: 2 hard constraints moved to permissions.deny; 1 pointer line kept.
Last reviewed: 2026-11-10
```

## Rules
- Treat these as smells and remove them: narrative history, a rule with "always" or "never" and no trigger, a copy of the README, instructions meant for humans, and a long code-style section that a formatter already enforces.
- Delete a rule that you cannot connect to a real mistake or a real need.
- Do not split a long file into imports to make it look short. In Claude Code, an import helps organization and does not reduce context.
- Tell the user before you delete a rule that the user wrote. Show the line.
- Exceed 200 lines only when each line is used often, and say why in the report.

Host notes for Claude Code, from its documentation:
- CLAUDE.md files are loaded at the start of every session. Claude treats them as context, not as enforced configuration.
- "Files over 200 lines consume more context and may reduce adherence."
- Settings rules are enforced by the client. To block an action whatever Claude decides, use a permission rule or a PreToolUse hook.

## Tooling
Run the bundled CLI from any working directory:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" <sub-command>
```

`${CLAUDE_SKILL_DIR}` is the directory that contains this SKILL.md. Claude Code fills it in. If the placeholder appears unfilled, replace it with that directory's absolute path. State lives in `.agent/` at the repository root (override with `AGENT_STATE_DIR`).

- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" rules lint` finds the rules files under the current directory and prints findings with line numbers. It exits 1 when findings exist, and 0 otherwise.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" rules lint ROOT` does the same under ROOT.

The lint flags a file over 200 lines, a negative-only rule, a vague rule with no testable trigger, a duplicate rule line, and a rule that names a command a deny rule can block.

## Without a shell
Ask the user to paste the rules file. Count the lines, then apply the checklist by hand. Return the edited file and the report.

## Enforcement (optional)
No hook backs this skill. It is advisory on every host.

## Related skills
- negative-constraint-compiler: rewrites negative rules and prints deny rules for the hard constraints.
