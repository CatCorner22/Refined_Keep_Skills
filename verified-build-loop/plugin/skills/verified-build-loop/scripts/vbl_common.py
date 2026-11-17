#!/usr/bin/env python3
"""Shared helpers for the verified-build-loop hooks.

Standard library only. Python 3.8 or later.

The hooks read two files in the project:
  .claude/verify.json       the check configuration (Claude may add a check or a protected path, nothing else)
  .claude/verify-lock.json  the integrity record (only the Stop hook and the user write it)

User-only commands (run these yourself in a terminal; the PreToolUse hook blocks Claude from running them):
  python3 .claude/hooks/vbl_common.py unlock <path>   stop protecting one file
  python3 .claude/hooks/vbl_common.py relock          accept the current state of every protected file
"""

import fnmatch
import hashlib
import json
import os
import signal
import subprocess
import sys
import traceback

CONFIG_REL = ".claude/verify.json"
LOCK_REL = ".claude/verify-lock.json"

# Paths that Claude may never change through a file tool or a Bash command.
ALWAYS_PROTECTED = [
    ".claude/verify-lock.json",
    ".claude/hooks/*",
    ".claude/settings.json",
    ".claude/agents/reviewer.md",
]

OUTPUT_TAIL_LINES = 150
DEFAULT_TIMEOUT_SECONDS = 600
KILL_WAIT_SECONDS = 5
# Settings in verify.json that only the user may change. A missing key counts as its default.
USER_ONLY_SETTINGS = {
    "feature_list": "feature_list.json",
    "fingerprint_exclude": [],
    "plan_gate": True,
}


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def project_dir(hook_input=None):
    """Return the absolute project root."""
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root and hook_input:
        root = hook_input.get("cwd")
    return os.path.abspath(root or os.getcwd())


def rel_path(root, path):
    """Return path relative to root with forward slashes, or None if outside root."""
    if not path:
        return None
    absolute = os.path.abspath(path if os.path.isabs(path) else os.path.join(root, path))
    try:
        relative = os.path.relpath(absolute, root)
    except ValueError:  # different drive on Windows
        return None
    if relative == ".." or relative.startswith(".." + os.sep):
        return None
    return relative.replace(os.sep, "/")


def matches_any(relative, patterns):
    """True if relative matches a pattern. A pattern ending in '/' covers that whole folder.
    In fnmatch, '*' also matches '/', so 'tests/*' covers nested folders."""
    for pattern in patterns:
        pattern = pattern.replace("\\", "/")
        if pattern.startswith("./"):
            pattern = pattern[2:]
        if pattern.endswith("/"):
            if relative.startswith(pattern):
                return True
        elif fnmatch.fnmatchcase(relative, pattern):
            return True
    return False


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except FileNotFoundError:
        return None


def load_json_file(path):
    """Return (data, error). data is None when the file does not exist."""
    text = read_text(path)
    if text is None:
        return None, None
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, "{} is not valid JSON: {}".format(path, exc)


def write_json_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temp_path, path)


def sha256_file(path):
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
    except FileNotFoundError:
        return None
    return digest.hexdigest()


def load_config(root):
    """Return (config, error). config is None when the project has no verify.json."""
    return load_json_file(os.path.join(root, CONFIG_REL))


def _text_list(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def config_shape_problems(config):
    """Return what is malformed in a parsed verify.json. An empty list means that the hooks can use it."""
    if not isinstance(config, dict):
        return ["verify.json must hold a JSON object"]
    problems = []
    for key in ("fast_checks", "full_checks"):
        checks = config.get(key, [])
        if not isinstance(checks, list):
            problems.append("'{}' must be a list of checks".format(key))
            continue
        for index, check in enumerate(checks):
            label = "{} check {}".format(key, index + 1)
            if not isinstance(check, dict):
                problems.append("{} must be an object with 'name' and 'command'".format(label))
                continue
            if not isinstance(check.get("name"), str) or not check.get("name"):
                problems.append("{} needs a 'name'".format(label))
            if not isinstance(check.get("command"), str) or not check.get("command").strip():
                problems.append("{} needs a 'command'".format(label))
            if not _valid_timeout(check.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)):
                problems.append("{}: 'timeout_seconds' must be a number above 0".format(label))
    for key in ("protected", "fingerprint_exclude"):
        if not _text_list(config.get(key, [])):
            problems.append("'{}' must be a list of paths".format(key))
    if not isinstance(config.get("feature_list", "feature_list.json"), str):
        problems.append("'feature_list' must be a path")
    if not isinstance(config.get("plan_gate", True), bool):
        problems.append("'plan_gate' must be true or false")
    lint = config.get("lint_on_edit")
    if lint is not None:
        if not isinstance(lint, dict) or not isinstance(lint.get("command"), str):
            problems.append("'lint_on_edit' must be an object with a 'command'")
        elif not _text_list(lint.get("extensions", [])):
            problems.append("'lint_on_edit' 'extensions' must be a list such as [\".py\"]")
        elif not _valid_timeout(lint.get("timeout_seconds", 120)):
            problems.append("'lint_on_edit': 'timeout_seconds' must be a number above 0")
    return problems


def _valid_timeout(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def load_usable_config(root):
    """Return (config, error). Like load_config, and a malformed config is an error too."""
    config, error = load_config(root)
    if error or config is None:
        return config, error
    problems = config_shape_problems(config)
    if problems:
        return None, "{} is malformed:\n- {}".format(CONFIG_REL, "\n- ".join(problems))
    return config, None


def protected_patterns(config):
    patterns = list(ALWAYS_PROTECTED)
    if config:
        patterns.extend(config.get("protected", []))
    return patterns


def feature_list_rel(config):
    return (config or {}).get("feature_list", "feature_list.json")


# ---------------------------------------------------------------------------
# Change rules
# ---------------------------------------------------------------------------

def _features_by_id(data):
    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list):
        return None, "feature list must hold a 'features' array"
    by_id = {}
    for feature in features:
        if not isinstance(feature, dict) or not isinstance(feature.get("id"), str) or not feature["id"]:
            return None, "every feature needs an 'id' that is a non-empty string"
        if feature["id"] in by_id:
            return None, "feature id {} appears twice".format(feature["id"])
        by_id[feature["id"]] = feature
    return by_id, None


def feature_list_violations(old_data, new_data):
    """Rules: keep every old feature; change no field except 'passes'; add new features only with passes false."""
    if old_data is None:
        return []
    old, error = _features_by_id(old_data)
    if error:
        return []  # the old file was already malformed; do not block repairs
    new, error = _features_by_id(new_data)
    if error:
        return [error]
    problems = []
    for feature_id, old_feature in old.items():
        new_feature = new.get(feature_id)
        if new_feature is None:
            problems.append("feature {} was removed".format(feature_id))
            continue
        old_rest = {k: v for k, v in old_feature.items() if k != "passes"}
        new_rest = {k: v for k, v in new_feature.items() if k != "passes"}
        if old_rest != new_rest:
            problems.append("feature {} changed a field other than 'passes'".format(feature_id))
    for feature_id, new_feature in new.items():
        if feature_id not in old and new_feature.get("passes") is not False:
            problems.append("new feature {} must start with \"passes\": false".format(feature_id))
    return problems


def _checks_by_name(config, key):
    checks = (config or {}).get(key, [])
    if not isinstance(checks, list):
        return {}
    return {check.get("name"): check for check in checks if isinstance(check, dict)}


def config_violations(old_config, new_config):
    """Rules: keep every old check unchanged; keep every protected path; keep the lint setting once it
    exists; keep the user-only settings (USER_ONLY_SETTINGS), where a missing key counts as its default."""
    if not isinstance(old_config, dict):
        return []  # no earlier config, or one that was already malformed; do not block repairs
    problems = config_shape_problems(new_config)
    if problems:
        return problems
    for key in ("fast_checks", "full_checks"):
        old_checks = _checks_by_name(old_config, key)
        new_checks = _checks_by_name(new_config, key)
        for name, check in old_checks.items():
            if new_checks.get(name) != check:
                problems.append("{} check '{}' was removed or changed".format(key, name))
    old_protected = old_config.get("protected", [])
    removed = set(old_protected if _text_list(old_protected) else []) - set(new_config.get("protected", []))
    for path in sorted(removed):
        problems.append("protected path '{}' was removed".format(path))
    if "lint_on_edit" in old_config and new_config.get("lint_on_edit") != old_config.get("lint_on_edit"):
        problems.append("setting 'lint_on_edit' was changed")
    for key, default in USER_ONLY_SETTINGS.items():
        if new_config.get(key, default) != old_config.get(key, default):
            problems.append("setting '{}' was changed".format(key))
    return problems


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def tail(text, lines=OUTPUT_TAIL_LINES):
    parts = (text or "").rstrip().splitlines()
    if len(parts) <= lines:
        return "\n".join(parts)
    return "[... {} earlier lines cut ...]\n".format(len(parts) - lines) + "\n".join(parts[-lines:])


def run_check(root, check):
    """Run one check. Return (passed, report_text)."""
    name = check.get("name", "unnamed check")
    command = check.get("command")
    if not command:
        return False, "Check '{}' has no command.".format(name)
    timeout = check.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if not _valid_timeout(timeout):
        return False, "Check '{}' has a 'timeout_seconds' that is not a number above 0.".format(name)
    try:
        # A new session gives the command its own process group, so a timeout can stop every process
        # that the command started. Output is decoded leniently: a stray byte must not crash the hook.
        process = subprocess.Popen(
            command, shell=True, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=(os.name == "posix"),
        )
    except OSError as exc:
        return False, "Check '{}' could not start: {}\n{}".format(name, command, exc)
    try:
        raw, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(process)
        return False, "Check '{}' timed out after {:g} seconds: {}".format(name, timeout, command)
    if process.returncode == 0:
        return True, ""
    output = tail((raw or b"").decode("utf-8", "replace"))
    return False, "Check '{}' failed (exit {}): {}\n{}".format(name, process.returncode, command, output)


def _kill_group(process):
    """Stop a timed-out command and the processes it started, then collect it."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except OSError:
        pass
    try:
        process.communicate(timeout=KILL_WAIT_SECONDS)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Hook input and output
# ---------------------------------------------------------------------------

def read_hook_input():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def block(message):
    """Exit code 2: Claude Code shows stderr to Claude and blocks the action or the stop."""
    sys.stderr.write(message.rstrip() + "\n")
    sys.exit(2)


def run_stop_hook(main, hook_input):
    """Run the Stop hook's main(hook_input) and return its exit code.

    An internal error must not pass in silence, because Claude Code treats a crashed hook as a
    non-blocking error and lets the turn end unchecked. On the first attempt the error blocks, so
    Claude reads it and tells the user. On a continued attempt the turn ends and the user gets a message.
    """
    try:
        return main(hook_input)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - every internal error takes the same route
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        where = traceback.format_exc(limit=-2)
        text = ("verified-build-loop: the Stop hook failed internally, so the checks did not run.\n"
                "{}\nTell the user this, and do not say that the work is verified. "
                "Run the checks by hand, and see Phase 3 (Repair) of the skill.".format(detail))
        if hook_input.get("stop_hook_active"):
            print(json.dumps({"systemMessage": text}))
            return 0
        block(text + "\n" + where)


# ---------------------------------------------------------------------------
# User-only commands
# ---------------------------------------------------------------------------

def _user_unlock(root, target):
    config, error = load_config(root)
    if error or config is None:
        print(error or "No .claude/verify.json in this project.")
        return 1
    if not isinstance(config, dict) or not _text_list(config.get("protected", [])):
        print("{} is malformed; fix its 'protected' list first.".format(CONFIG_REL))
        return 1
    relative = rel_path(root, target) or target
    if relative not in config.get("protected", []):
        print("'{}' is not in the 'protected' list. The list holds: {}".format(
            relative, ", ".join(config.get("protected", [])) or "nothing"))
        return 1
    config["protected"] = [p for p in config.get("protected", []) if p != relative]
    write_json_file(os.path.join(root, CONFIG_REL), config)
    lock, _ = load_json_file(os.path.join(root, LOCK_REL))
    if isinstance(lock, dict) and isinstance(lock.get("hashes"), dict):
        lock["hashes"].pop(relative, None)
        lock["config_snapshot"] = config
        write_json_file(os.path.join(root, LOCK_REL), lock)
    print("Unprotected {}.".format(relative))
    return 0


def _user_relock(root):
    lock_path = os.path.join(root, LOCK_REL)
    if os.path.exists(lock_path):
        os.remove(lock_path)
    print("Removed the lock. The next Stop hook run records the current state of every protected file.")
    return 0


def main(argv):
    root = project_dir()
    if len(argv) == 3 and argv[1] == "unlock":
        return _user_unlock(root, argv[2])
    if len(argv) == 2 and argv[1] == "relock":
        return _user_relock(root)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
