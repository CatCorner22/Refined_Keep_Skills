## Verified build loop
This project uses verified-build-loop. Hooks enforce the checks; these lines say how to work.
- Start every session: read progress.md, run `git log --oneline -5`, run `bash init.sh`.
- Build one feature per session: the first feature in feature_list.json with "passes": false.
- Begin with the end: before you write code, write the acceptance checks (each command and what its output must show). Run a command to verify each fact that a plan rests on.
- Every plan has an "Acceptance checks" part that names at least 1 command, and an "Assumptions" part. In plan mode a hook denies a plan without them.
- Write the feature's tests first, confirm they fail for the right reason, then add them to "protected" in .claude/verify.json.
- Implement in small steps, and run the covering test after each step. Fix what the lint hook reports at once.
- After implementing, have the `reviewer` subagent compare the changes with SPEC.md. Fix correctness gaps; skip style.
- Set "passes": true only after the full checks pass. The Stop hook reruns them.
- Finish with a commit, a progress.md entry, and an evidence report (commands run and their output). Then tell the user to start a new session for the next feature.
- Never change a protected file, a check in verify.json, or a feature's fields other than "passes". If one is wrong, stop and ask the user.
- Check commands: <fast checks>; <full checks>; <lint>.
