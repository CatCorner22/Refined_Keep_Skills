#!/usr/bin/env python3
"""PreToolUse hook for verified-build-loop.

Runs before Claude writes, edits, or runs a Bash command. Blocks (exit code 2):
  - any write to a protected path (verify.json "protected" plus the hook files, settings, and lock);
  - a change to the feature list other than flipping "passes" or adding a new failing feature;
  - a change to verify.json that removes or alters a check, a protected path, or a setting;
  - a Bash command that names a protected path and also writes, moves, or deletes files
    (one exception: a lone "git restore PATH" or "git checkout [HEAD] -- PATH", which puts a
    file back to its committed content, so that Claude can undo its own accidental change);
  - a Bash command that runs the user-only unlock or relock commands.
The Bash rule is a heuristic. The Stop hook's integrity check is the backstop.
"""

import json
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vbl_common as vbl  # noqa: E402

FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
WRITE_COMMAND = re.compile(
    r"(^|[\s;&|(`])("
    r"rm|mv|cp|tee|truncate|dd|ln|install|rsync|chmod|unlink|shred|"
    r"sed\s+(?:-[^\s]*\s+)*-i|perl\s+(?:-[^\s]*\s+)*-[^\s]*i|"
    r"git\s+(?:checkout|restore|rm|mv|reset|stash|apply|clean)|"
    r"python3?\s+-c|node\s+-e|ruby\s+-e"
    r")\b"
)
REDIRECT_TARGET = re.compile(r"(?:^|[^<>&\d])\d*>>?\s*([^\s;&|<>()]+)")
SAFE_TARGETS = {"/dev/null", "/dev/stderr", "/dev/stdout"}


def new_content_after(tool_name, tool_input, old_text):
    """Return the file text the tool would produce, or None if it cannot be worked out."""
    if tool_name == "Write":
        return tool_input.get("content", "")
    edits = []
    if tool_name == "Edit":
        edits = [tool_input]
    elif tool_name == "MultiEdit":
        edits = tool_input.get("edits", [])
    else:
        return None
    text = old_text or ""
    for edit in edits:
        old_string = edit.get("old_string", "")
        new_string = edit.get("new_string", "")
        if old_string not in text:
            return None  # the tool call itself will fail
        text = text.replace(old_string, new_string) if edit.get("replace_all") else text.replace(old_string, new_string, 1)
    return text


def json_rule_problems(relative, config, tool_name, tool_input, root):
    """Apply the feature-list and verify.json rules to a proposed file change."""
    is_feature_list = relative == vbl.feature_list_rel(config)
    is_config = relative == vbl.CONFIG_REL
    if not (is_feature_list or is_config):
        return []
    old_text = vbl.read_text(os.path.join(root, relative))
    if old_text is None:
        return []  # creating the file is allowed
    new_text = new_content_after(tool_name, tool_input, old_text)
    if new_text is None:
        if tool_name == "NotebookEdit":
            return ["edit {} with Edit or Write, not NotebookEdit".format(relative)]
        return []
    try:
        old_data = json.loads(old_text)
    except json.JSONDecodeError:
        return []  # the old file was already broken; let Claude repair it
    try:
        new_data = json.loads(new_text)
    except json.JSONDecodeError as exc:
        return ["the new {} would not be valid JSON: {}".format(relative, exc)]
    if is_feature_list:
        return vbl.feature_list_violations(old_data, new_data)
    return vbl.config_violations(old_data, new_data)


def check_file_tool(root, config, tool_name, tool_input):
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    relative = vbl.rel_path(root, path)
    if relative is None:
        return []
    if vbl.matches_any(relative, vbl.protected_patterns(config)):
        return ["'{}' is protected. Only the user can change it.".format(relative)]
    return json_rule_problems(relative, config, tool_name, tool_input, root)


SHELL_SYNTAX = re.compile(r"[;&|<>`$()\n\\]")


def is_plain_restore(command):
    """True for one git command, with no other shell syntax, that only puts files back to their
    committed content: `git restore [--worktree] [--] PATH...` or `git checkout [HEAD] -- PATH...`."""
    if SHELL_SYNTAX.search(command):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if len(words) < 3 or words[0] != "git":
        return False
    if words[1] == "restore":
        rest = [word for word in words[2:] if word not in ("--worktree", "-W")]
    elif words[1] == "checkout":
        rest = words[3:] if words[2] == "HEAD" else words[2:]
        if not rest or rest[0] != "--":
            return False
    else:
        return False
    if rest and rest[0] == "--":
        rest = rest[1:]
    return bool(rest) and not any(word.startswith("-") for word in rest)


PATH_TOKEN = re.compile(r"[^\s;&|<>()'\"`=]+")


def is_guarded(root, config, token):
    relative = vbl.rel_path(root, token)
    if not relative or relative == ".":
        return None
    guarded = vbl.protected_patterns(config) + [vbl.CONFIG_REL, vbl.feature_list_rel(config)]
    if vbl.matches_any(relative, guarded):
        return relative
    # a folder that holds a protected file, such as "rm -r tests" when "tests/*" is protected
    for pattern in guarded:
        if pattern.startswith(relative.rstrip("/") + "/"):
            return relative
    return None


def check_bash(root, config, command):
    if "vbl_common.py" in command and re.search(r"\b(unlock|relock)\b", command):
        return ["unlock and relock are user-only commands. Ask the user to run them."]
    problems = []
    for target in REDIRECT_TARGET.findall(command):
        if target in SAFE_TARGETS:
            continue
        relative = is_guarded(root, config, target)
        if relative:
            problems.append("the command writes to '{}' with a redirect".format(relative))
    if WRITE_COMMAND.search(command) and not is_plain_restore(command):
        named = []
        for token in PATH_TOKEN.findall(command):
            relative = is_guarded(root, config, token)
            if relative and relative not in named:
                named.append(relative)
        for relative in named:
            problems.append("the command names '{}' and also writes, moves, or deletes files".format(relative))
    return problems


def main():
    hook_input = vbl.read_hook_input()
    root = vbl.project_dir(hook_input)
    config, error = vbl.load_usable_config(root)
    if error or config is None:
        return 0  # not set up, or a broken config that the Stop hook reports
    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    if tool_name in FILE_TOOLS:
        problems = check_file_tool(root, config, tool_name, tool_input)
    elif tool_name == "Bash":
        command = tool_input.get("command")
        problems = check_bash(root, config, command if isinstance(command, str) else "")
    else:
        problems = []
    if problems:
        vbl.block("verified-build-loop blocked this action:\n- " + "\n- ".join(problems) +
                  "\nIf the change is necessary, stop and ask the user. "
                  "If a Bash command was blocked by mistake, split it so the protected path and the write are separate commands.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
