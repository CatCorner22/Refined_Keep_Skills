# The always-on rule

A skill loads only when Claude judges that its description fits the task. The rule below is short enough to sit in the instructions that a surface loads in every session. Copy it there once. The rule also tells Claude to load the full skill.

## The rule

Copy the text between the 2 lines.

---

Backward review (standing rule; applies to every plan, reply, deliverable and task, however small):

1. Before you present a plan, send a reply, deliver work or act on a plan, split it into parts and review the parts from the last part to the first part. For each part, check that every fact, name, number, path and command is correct, that an earlier part supplies everything the part needs, and that the user's request needs the part.
2. Correct every error that you find.
3. Re-read the whole corrected text from its first part to its last part, against my request.
4. End it with this line, filled in: "Backward review: N parts, last to first; forward re-read done. Corrections: (what you corrected, or none)".
5. Before you act on a plan, and after any interruption, re-read the whole plan.
6. If the backward-review-gate skill is available, load it and follow its procedure.

---

## Where to put the rule

| Surface | Place | Scope |
|---|---|---|
| claude.ai chat, desktop app and mobile app | Settings, then the field for your personal preferences in your profile | every chat of your account |
| claude.ai project | the instructions of the project | every chat in that project |
| Claude Code on your machine | `~/.claude/CLAUDE.md` | every session of your user account on that machine |
| Claude Code in 1 repository, cloud sessions included | `CLAUDE.md` at the root of the repository, committed | every session in that repository |

Notes:

- A cloud session does not read `~/.claude/` from your machine. For a cloud session, commit the rule to `CLAUDE.md` in the repository.
- A plugin cannot deliver the rule: Claude Code does not load a `CLAUDE.md` from a plugin. With the plugin installed, the UserPromptSubmit hook adds the rule to every prompt instead.
- The rule is an instruction. Claude follows it or, now and then, does not. Only the hooks in Claude Code check for the review record, and they check its form.
