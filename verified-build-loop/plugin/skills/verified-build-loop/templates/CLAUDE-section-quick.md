## Verified build loop
This project uses verified-build-loop (quick setup). Hooks enforce the checks; these lines say how to work.
- Begin with the end: before you write code, write the acceptance checks for the task (each command and what its output must show).
- Run a command to verify each fact that a plan rests on. List what you did not verify under "Assumptions".
- Every plan has an "Acceptance checks" part that names at least 1 command, and an "Assumptions" part. In plan mode a hook denies a plan without them.
- Write the tests first and confirm that they fail for the right reason. Then implement in small steps, and run the covering test after each step.
- Fix what the lint hook reports at once. Run the fast checks yourself before you end a turn; the Stop hook reruns them.
- For any change beyond a few lines, have the `reviewer` subagent review it. Fix correctness gaps; skip style.
- Finish with a commit and an evidence report: each acceptance check, the command you ran, and its output. State what you did not verify.
- Never weaken a check. Never change a protected file or a check in .claude/verify.json. If one is wrong, stop and ask the user.
- Protected tests: <ask the user once: protect new tests, or leave them editable>.
- Check commands: <fast checks>; <lint>.
