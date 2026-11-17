# Rules for work in this repository

## Backward review

This rule applies to every plan, reply, deliverable and task, however small.

1. Before you present a plan, send a reply, deliver work or act on a plan, split it into parts and review the parts from the last part to the first part. For each part, check that every fact, name, number, path and command is correct, that an earlier part supplies everything the part needs, and that the user's request needs the part.
2. Correct every error that you find.
3. Re-read the whole corrected text from its first part to its last part, against the user's request.
4. End it with this line, filled in: "Backward review: N parts, last to first; forward re-read done. Corrections: (what you corrected, or none)".
5. Before you act on a plan, and after any interruption, re-read the whole plan.
6. Load the `backward-review-gate` skill and follow its procedure.

## Build

After a change to a skill or to `lib/`, run `python3 tools/build.py all`, then `python3 -m unittest discover -s tests`.

After a change to `verified-build-loop/plugin/skills/verified-build-loop/`, run `python3 verified-build-loop/tools/build.py zip`, then the 2 test commands in `verified-build-loop/README.md`, section 5.

## Verified build loop

This repository uses verified-build-loop (quick setup). Hooks enforce the checks; these lines say how to work.

- Begin with the end: before you write code, write the acceptance checks for the task (each command and what its output must show).
- Run a command to verify each fact that a plan rests on. List what you did not verify under "Assumptions".
- Every plan has an "Acceptance checks" part that names at least 1 command, and an "Assumptions" part. In plan mode a hook denies a plan without them.
- Write the tests first and confirm that they fail for the right reason. Then implement in small steps, and run the covering test after each step.
- Fix what the lint hook reports at once. Run the fast checks yourself before you end a turn; the Stop hook reruns them.
- For any change beyond a few lines, have the `reviewer` subagent review it. Fix correctness gaps; skip style.
- Finish with a commit and an evidence report: each acceptance check, the command you ran, and its output. State what you did not verify.
- Never weaken a check. Never change a protected file or a check in `.claude/verify.json`. If one is wrong, stop and ask the user.
- Protected tests: none. New tests stay editable until the user asks to protect them.
- The fast checks are the 5 commands in `.claude/verify.json`. The lint check parses each edited `.py` file.
- The files under `.claude/hooks/` are copies of the scripts in `verified-build-loop/plugin/skills/verified-build-loop/scripts/`. Only the user can replace them; `verified-build-loop/README.md`, section 5, gives the 2 commands.
