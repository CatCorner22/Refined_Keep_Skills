#!/usr/bin/env python3
"""PostToolUse hook for verified-build-loop.

Runs right after Claude writes or edits a file. If verify.json sets "lint_on_edit" and the
file has one of its extensions, runs the lint command on that file. On lint errors, exits
with code 2 so Claude Code shows the errors to Claude. (The edit has already happened;
this hook reports, it does not undo.)
"""

import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vbl_common as vbl  # noqa: E402


def main():
    hook_input = vbl.read_hook_input()
    root = vbl.project_dir(hook_input)
    config, error = vbl.load_usable_config(root)
    if error or not config or not config.get("lint_on_edit"):
        return 0  # not set up, no lint command, or a broken config that the Stop hook reports
    lint = config["lint_on_edit"]
    tool_input = hook_input.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    relative = vbl.rel_path(root, path)
    if not relative or not os.path.isfile(os.path.join(root, relative)):
        return 0
    extensions = lint.get("extensions", [])
    if extensions and os.path.splitext(relative)[1] not in extensions:
        return 0
    command = lint.get("command", "").replace("{file}", shlex.quote(relative))
    passed, report = vbl.run_check(root, {
        "name": "lint " + relative,
        "command": command,
        "timeout_seconds": lint.get("timeout_seconds", 120),
    })
    if not passed:
        vbl.block("verified-build-loop: lint errors in the file you just edited. Fix them now.\n" + report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
