#!/usr/bin/env python3
"""PreToolUse hook on ExitPlanMode for verified-build-loop: the plan gate.

Runs when Claude presents a plan for approval. Denies (exit code 2) a plan that lacks either of:
  - an "Acceptance checks" part that names at least one command (in backticks or in a code fence):
    the commands that will prove the work, written before any code;
  - an "Assumptions" part: what the plan takes as true without having run anything to verify it
    (the word "none" is a valid answer).
The gate reads the form of the plan. It cannot judge whether the checks are the right ones;
the user does that when the user approves the plan.

The user turns the gate off with "plan_gate": false in .claude/verify.json.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vbl_common as vbl  # noqa: E402

MARKUP = r"[\s>*_#\-\d.)]*"
LABEL = re.compile(r"(?im)^%s(acceptance[ \t]+checks?|assumptions?)\b[*_ \t]*:?[*_ \t]*(.*)$" % MARKUP)
HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+\S")
FENCE = re.compile(r"^ {0,3}(```|~~~)")
INLINE_CODE = re.compile(r"`[^`\n]+`")

TEMPLATE = (
    "## Acceptance checks\n"
    "- `<command>`: <what its output must show>\n"
    "\n"
    "## Assumptions\n"
    "- <a fact that the plan rests on and that no command has verified, or: none>"
)


def parts(plan):
    """Return {"acceptance": text, "assumptions": text} for the labelled parts that the plan holds.

    A part starts at its label and runs to the next label or the next heading."""
    found = {}
    lines = plan.splitlines()
    index = 0
    in_fence = False
    current = None
    while index < len(lines):
        line = lines[index]
        if FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else LABEL.match(line)
        if match:
            current = "acceptance" if match.group(1).lower().startswith("acceptance") else "assumptions"
            found[current] = [match.group(2)]
        elif current and not in_fence and HEADING.match(line):
            current = None
        elif current:
            found[current].append(line)
        index += 1
    return {name: "\n".join(body) for name, body in found.items()}


def names_a_command(text):
    """True when the text holds inline code, or a code fence with a non-empty line."""
    in_fence = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
        elif in_fence and line.strip():
            return True
        elif not in_fence and INLINE_CODE.search(line):
            return True
    return False


def plan_problems(plan):
    found = parts(plan)
    problems = []
    if "acceptance" not in found:
        problems.append("the plan has no \"Acceptance checks\" part")
    elif not names_a_command(found["acceptance"]):
        problems.append("the \"Acceptance checks\" part names no command; put each command in backticks")
    if "assumptions" not in found:
        problems.append("the plan has no \"Assumptions\" part")
    elif not found["assumptions"].strip():
        problems.append("the \"Assumptions\" part is empty; list each assumption, or write: none")
    return problems


def main():
    hook_input = vbl.read_hook_input()
    root = vbl.project_dir(hook_input)
    config, error = vbl.load_usable_config(root)
    if error or config is None or config.get("plan_gate", True) is False:
        return 0  # not set up, switched off by the user, or a broken config that the Stop hook reports
    tool_input = hook_input.get("tool_input")
    plan = tool_input.get("plan") if isinstance(tool_input, dict) else None
    if not isinstance(plan, str) or not plan.strip():
        return 0  # the host did not pass the plan text, so there is nothing to read
    problems = plan_problems(plan)
    if problems:
        vbl.block(
            "verified-build-loop: this plan is not ready to present:\n- " + "\n- ".join(problems) +
            "\nBegin with the end: decide which commands will prove the work before you write any code, "
            "and run a command to verify each fact that the plan rests on. "
            "Add these 2 parts to the plan file, then call ExitPlanMode again:\n" + TEMPLATE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
