#!/usr/bin/env python3
"""PreToolUse hook for verified-build-loop.

Runs before Claude writes, edits, or runs a Bash command. Blocks (exit code 2):
  - any write to a protected path (verify.json "protected" plus the hook files, settings, and lock),
    under any name for that path (letter case, a symbolic link);
  - a change to the feature list other than flipping "passes" or adding a new failing feature;
  - a change to verify.json other than a new check or a new protected path;
  - a Bash command that names a protected path and also writes, moves, or deletes files
    (one exception: a lone "git checkout HEAD -- PATH" or
    "git restore --source=HEAD --staged --worktree -- PATH", which puts a file back to the
    content of the last commit, so that Claude can undo its own accidental change);
  - a Bash command that runs the user-only unlock or relock commands.
The hook files, the settings and the lock stay protected when verify.json is missing or malformed.
The Bash rule is a heuristic. The Stop hook's integrity check is the backstop.
"""

import json
import os
import re
import shlex
import sys

sys.dont_write_bytecode = True  # keep a __pycache__ folder out of .claude/hooks/
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
SHELL_SYNTAX = re.compile(r"[;&|<>`$(){}\n\\]")
PATH_TOKEN = re.compile(r"[^\s;&|<>()'\"`=]+")
RESTORE_FORMS = (
    ["git", "checkout", "HEAD", "--"],
    ["git", "restore", "--source=HEAD", "--staged", "--worktree", "--"],
)


def new_content_after(tool_name, tool_input, old_text):
    """Return the file text the tool would produce, or None if it cannot be worked out."""
    if tool_name == "Write":
        content = tool_input.get("content", "")
        return content if isinstance(content, str) else None
    if tool_name == "Edit":
        edits = [tool_input]
    elif tool_name == "MultiEdit":
        edits = tool_input.get("edits")
        if not isinstance(edits, list):
            return None
    else:
        return None
    text = old_text or ""
    for edit in edits:
        if not isinstance(edit, dict):
            return None
        old_string = edit.get("old_string", "")
        new_string = edit.get("new_string", "")
        if not isinstance(old_string, str) or not isinstance(new_string, str) or not old_string:
            return None
        if old_string not in text:
            return None
        text = text.replace(old_string, new_string) if edit.get("replace_all") else text.replace(old_string, new_string, 1)
    return text


def json_rule_problems(relative, config, tool_name, tool_input, root):
    """Apply the feature-list and verify.json rules to a proposed file change."""
    is_feature_list = relative.lower() == vbl.feature_list_rel(config).lower()
    is_config = relative.lower() == vbl.CONFIG_REL
    if not (is_feature_list or is_config):
        return []
    try:
        old_text = vbl.read_text(os.path.join(root, relative))
    except (OSError, ValueError):
        return []  # the file cannot be read as text; the Stop hook reports that
    if old_text is None:
        return []  # creating the file is allowed
    try:
        old_data = json.loads(old_text)
    except (ValueError, RecursionError):
        return []  # the old file was already broken; let Claude repair it
    new_text = new_content_after(tool_name, tool_input, old_text)
    if new_text is None:
        # If the hook cannot work out the result, it cannot apply the rules, so it does not guess.
        return ["the hook cannot work out the result of this change to {}; "
                "use the Write tool with the full new content".format(relative)]
    try:
        new_data = json.loads(new_text)
    except RecursionError:
        return ["the new {} would not be valid JSON: it is nested too deeply".format(relative)]
    except ValueError as exc:
        return ["the new {} would not be valid JSON: {}".format(relative, exc)]
    if is_feature_list:
        return vbl.feature_list_violations(old_data, new_data)
    return vbl.config_violations(old_data, new_data)


def check_file_tool(root, config, tool_name, tool_input):
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    forms = vbl.rel_paths(root, path)
    patterns = vbl.protected_patterns(config)
    for relative in forms:
        if vbl.matches_any(relative, patterns):
            return ["'{}' is protected. Only the user can change it.".format(relative)]
    for relative in forms:
        problems = json_rule_problems(relative, config, tool_name, tool_input, root)
        if problems:
            return problems
    return []


def is_plain_restore(command):
    """True for one git command, with no other shell syntax, that only puts files back to the
    content of the last commit: `git checkout HEAD -- PATH...` or
    `git restore --source=HEAD --staged --worktree -- PATH...`.

    Other forms are not accepted. For example, `git restore PATH` takes the content from the
    index, which can hold a staged change."""
    if SHELL_SYNTAX.search(command):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    for form in RESTORE_FORMS:
        if words[:len(form)] == form:
            paths = words[len(form):]
            return bool(paths) and not any(word.startswith("-") for word in paths)
    return False


def is_guarded(root, config, token):
    """Return the relative form of token that a guarded pattern covers, or None."""
    guarded = vbl.protected_patterns(config) + [vbl.CONFIG_REL, vbl.feature_list_rel(config)]
    for relative in vbl.rel_paths(root, token):
        if not relative or relative == ".":
            continue
        if vbl.matches_any(relative, guarded):
            return relative
        # a folder that holds a protected file, such as "rm -r tests" when "tests/*" is protected
        prefix = relative.rstrip("/").lower() + "/"
        for pattern in guarded:
            if pattern.lower().startswith(prefix):
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
    if not vbl.is_set_up(root):
        return 0  # this project does not use the loop
    config, error = vbl.load_usable_config(root)
    if error:
        config = None  # missing or malformed: the always-protected paths still apply; the Stop hook reports it
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
                  "If a Bash command was blocked by mistake, split it so the protected path and the write are "
                  "separate commands. To put a protected file back to its committed content, run only: "
                  "git checkout HEAD -- <path>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
