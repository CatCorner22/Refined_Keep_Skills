#!/usr/bin/env python3
"""PreToolUse hook on ExitPlanMode for verified-build-loop: the plan gate.

Runs when Claude presents a plan for approval. Denies (exit code 2) a plan that lacks either of:
  - an "Acceptance checks" part that names at least one command (in backticks or in a code fence):
    the commands that will prove the work, written before any code;
  - an "Assumptions" part: what the plan takes as true without having run anything to verify it
    (the word "none" is a valid answer).
The gate reads the form of the plan. It cannot judge whether the checks are the right ones;
the user does that when the user approves the plan.

How the gate reads a plan:
  - A part starts at its label. A label is a heading that starts with the label words
    ("## Acceptance checks"), or a line that holds only the label words, with or without a list
    marker, bold markers and a colon, and with or without text after the colon
    ("**Assumptions:** none"). A sentence that merely starts with those words is not a label.
  - A part ends at the next label, heading, horizontal rule, or line that holds only bold text.
  - The first label of each kind counts. Text inside a code fence is never a label.

The user turns the gate off with "plan_gate": false in .claude/verify.json.
"""

import os
import re
import sys

sys.dont_write_bytecode = True  # keep a __pycache__ folder out of .claude/hooks/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vbl_common as vbl  # noqa: E402

LABEL_WORDS = r"(acceptance[ \t]+checks?|assumptions?)"
LIST_MARKER = r"(?:[-*+][ \t]+|\d+[.)][ \t]+)?"
HEADING_LABEL = re.compile(r"(?i)^ {0,3}#{1,6}[ \t]+[*_]*%s(?![A-Za-z])(.*)$" % LABEL_WORDS)
PLAIN_LABEL = re.compile(r"(?i)^[ \t]*%s[*_]*%s[*_]*[ \t]*(?::[*_]*[ \t]*(.*))?$" % (LIST_MARKER, LABEL_WORDS))
HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+\S")
RULE = re.compile(r"^ {0,3}(?:-{3,}|\*{3,}|_{3,})[ \t]*$")
BOLD_ONLY = re.compile(r"^[ \t]*%s(\*\*|__)(?![ \t]).+?\1:?[ \t]*$" % LIST_MARKER)
FENCE = re.compile(r"^[ \t]*(```|~~~)")
ONE_LINE_FENCE = re.compile(r"^[ \t]*(```|~~~).*\S.*\1[ \t]*$")
INLINE_CODE = re.compile(r"`[^`\n]+`")

TEMPLATE = (
    "## Acceptance checks\n"
    "- `<command>`: <what its output must show>\n"
    "\n"
    "## Assumptions\n"
    "- <a fact that the plan rests on and that no command has verified, or: none>"
)


def label_of(line):
    """Return (kind, text after the label) for a label line, or (None, None)."""
    match = HEADING_LABEL.match(line)
    if match:
        tail = match.group(2).strip()
        # The rest of a heading belongs to the heading ("Assumptions and risks"), unless a colon sets it off.
        text = tail[1:].strip(" \t*_") if tail.startswith(":") else ""
    else:
        match = PLAIN_LABEL.match(line)
        if not match:
            return None, None
        text = (match.group(2) or "").strip()
    kind = "acceptance" if match.group(1).lower().startswith("acceptance") else "assumptions"
    return kind, text


def is_fence(line):
    """True for a line that opens or closes a code fence. A fence that opens and closes on 1 line is inline code."""
    return bool(FENCE.match(line)) and not ONE_LINE_FENCE.match(line)


def parts(plan):
    """Return {"acceptance": text, "assumptions": text} for the labelled parts that the plan holds."""
    found = {}
    current = None
    in_fence = False
    for line in plan.splitlines():
        if is_fence(line):
            in_fence = not in_fence
        elif not in_fence:
            kind, text = label_of(line)
            if kind:
                if kind in found:
                    current = None  # the first label of each kind counts
                else:
                    found[kind] = [text]
                    current = kind
                continue
            if HEADING.match(line) or RULE.match(line) or BOLD_ONLY.match(line):
                current = None
                continue
        if current:
            found[current].append(line)
    return {kind: "\n".join(body) for kind, body in found.items()}


def names_a_command(text):
    """True when the text holds inline code, or a code fence with a non-empty line."""
    in_fence = False
    for line in text.splitlines():
        if is_fence(line):
            in_fence = not in_fence
        elif in_fence:
            if line.strip():
                return True
        elif ONE_LINE_FENCE.match(line) or INLINE_CODE.search(line):
            return True
    return False


def has_text(text):
    """True when the text holds more than fence lines, list markers and white space."""
    return any(line.strip(" \t-*+") and not is_fence(line) for line in text.splitlines())


def plan_problems(plan):
    found = parts(plan)
    problems = []
    if "acceptance" not in found:
        problems.append("the plan has no \"Acceptance checks\" part")
    elif not names_a_command(found["acceptance"]):
        problems.append("the \"Acceptance checks\" part names no command; put each command in backticks")
    if "assumptions" not in found:
        problems.append("the plan has no \"Assumptions\" part")
    elif not has_text(found["assumptions"]):
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
