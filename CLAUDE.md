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
