# red-team

Version 1.0.0. A Claude Code plugin with 1 skill.

| Skill | Use it when |
|---|---|
| `red-team-lead` | You want an adversarial campaign against something that you own or are authorized to test: a plan, a prompt, an agent, a codebase, a policy or a brief |

The skill writes a charter, runs independent attacker lanes as sub-agents, hands the stripped attempts to a separate judge, and writes the findings and the report under `redteam/` in the working directory. It attacks authorized targets only.

`skills/red-team-lead/SKILL.md` is a byte-for-byte copy of the skill that the owner's claude.ai account held on 2026-11-17. This folder is now its home in git.

For a quality-control review with a fixed swarm of 8 read-only reviewers, see the `chicken-little-overwatch` plugin of the same marketplace.
