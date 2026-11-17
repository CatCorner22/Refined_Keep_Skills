#!/usr/bin/env python3
"""Stop hook for verified-build-loop.

Runs each time Claude tries to end its turn. In order:
  1. Integrity: confirms that no protected file, check, or feature changed against the rules.
  2. Skip: if no project file changed since the last passing run, lets Claude stop. In a git
     repository the project files are the files that git does not ignore. Elsewhere they are
     every file outside the dependency and cache folders in EXCLUDED_DIRS.
  3. Fast checks: runs every command in verify.json "fast_checks".
  4. Full checks: also runs "full_checks" when a feature changed to "passes": true.
On any failure, exits with code 2 so Claude Code sends the report back to Claude.
"""

import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vbl_common as vbl  # noqa: E402

EXCLUDED_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", "dist", "build", ".next", "target", ".idea", ".vscode",
}
REPEAT_LIMIT = 3  # identical failures in a row, while already continuing, before the hook lets Claude stop
GIT_TIMEOUT_SECONDS = 30
DURATION = re.compile(r"\b\d+(?:\.\d+)?\s*(?:ms|s|sec|secs|seconds)\b")


def walked_files(root, extra_excludes=()):
    """Return relative paths of the files under root, skipping dependency and cache folders."""
    excluded = EXCLUDED_DIRS | set(extra_excludes)
    found = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in excluded)
        for name in sorted(files):
            relative = vbl.rel_path(root, os.path.join(current, name))
            if relative:
                found.append(relative)
    return found


def git_files(root):
    """Return relative paths of the files that git tracks or does not ignore, or None when
    root is not the top folder of a git work tree or git cannot answer."""
    def git(*args):
        result = subprocess.run(
            ("git", "-c", "core.quotepath=off") + args, cwd=root, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=GIT_TIMEOUT_SECONDS,
        )
        return result.stdout if result.returncode == 0 else None
    try:
        # A project folder inside a larger repository could be ignored as a whole; use the walk there.
        if git("rev-parse", "--show-prefix") != b"\n":
            return None
        listed = git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    except (OSError, subprocess.SubprocessError):
        return None
    if listed is None:
        return None
    names = {name.decode("utf-8", "surrogateescape") for name in listed.split(b"\0") if name}
    return sorted(names)


def project_files(root, extra_excludes):
    """Return the files whose change makes the Stop hook run the checks again."""
    listed = git_files(root)
    if listed is None:
        return walked_files(root, extra_excludes)
    excluded = set(extra_excludes) | {".git"}
    return [relative for relative in listed if not excluded.intersection(relative.split("/")[:-1])]


def fingerprint(root, extra_excludes):
    digest = hashlib.sha256()
    for relative in project_files(root, extra_excludes):
        if relative == vbl.LOCK_REL or relative.endswith(".tmp"):
            continue
        try:
            info = os.lstat(os.path.join(root, relative))
            entry = "{}|{}|{}\n".format(relative, info.st_size, info.st_mtime_ns)
        except OSError:
            entry = "{}|missing\n".format(relative)  # tracked by git and deleted from the folder
        digest.update(entry.encode("utf-8", "surrogateescape"))
    return digest.hexdigest()


def check_protected_hashes(root, config, lock):
    """Compare protected files with the lock. Record files protected for the first time."""
    problems = []
    hashes = lock.setdefault("hashes", {})
    patterns = vbl.protected_patterns(config)
    # A path that no pattern covers any more was unlocked by the user. (A pattern that Claude
    # removed is reported by config_violations, and then nothing here is saved.)
    for relative in [path for path in hashes if not vbl.matches_any(path, patterns)]:
        del hashes[relative]
    seen = set()
    # Protection does not follow "fingerprint_exclude" or .gitignore: walk the folder itself.
    for relative in walked_files(root):
        if relative == vbl.LOCK_REL or not vbl.matches_any(relative, patterns):
            continue
        seen.add(relative)
        current = vbl.sha256_file(os.path.join(root, relative))
        recorded = hashes.get(relative)
        if recorded is None:
            hashes[relative] = current
        elif recorded != current:
            problems.append("protected file '{}' changed".format(relative))
    for relative in sorted(set(hashes) - seen):
        problems.append("protected file '{}' is missing".format(relative))
    return problems


def _passes_by_id(data):
    """Return {feature id: passes} for the well-formed features of a parsed feature list."""
    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list):
        return {}
    return {f["id"]: f.get("passes") for f in features if isinstance(f, dict) and isinstance(f.get("id"), str)}


def newly_passed(old_features, new_features):
    old = _passes_by_id(old_features)
    return sorted(feature_id for feature_id, passes in _passes_by_id(new_features).items()
                  if passes is True and old.get(feature_id) is not True)


def main(hook_input):
    root = vbl.project_dir(hook_input)
    config, error = vbl.load_usable_config(root)
    if error:
        vbl.block("verified-build-loop: " + error + "\nFix .claude/verify.json. If the hooks block the fix, "
                  "stop and ask the user to fix it.")
    if config is None:
        return 0  # project not set up for verified-build-loop

    lock_path = os.path.join(root, vbl.LOCK_REL)
    lock, lock_error = vbl.load_json_file(lock_path)
    if lock is not None and not (isinstance(lock, dict) and isinstance(lock.get("hashes", {}), dict)):
        lock_error = "malformed"
    if lock_error:
        vbl.block("verified-build-loop: the lock file .claude/verify-lock.json is not usable. "
                  "Stop and ask the user to run: python3 .claude/hooks/vbl_common.py relock")

    feature_path = os.path.join(root, vbl.feature_list_rel(config))
    features, feature_error = vbl.load_json_file(feature_path)
    if feature_error:
        vbl.block("verified-build-loop: " + feature_error)

    first_run = lock is None
    if first_run:
        lock = {"config_snapshot": config, "feature_snapshot": features, "hashes": {}}

    # 1. Integrity
    problems = []
    problems += vbl.config_violations(lock.get("config_snapshot"), config)
    problems += vbl.feature_list_violations(lock.get("feature_snapshot"), features)
    problems += check_protected_hashes(root, config, lock)
    if problems:
        vbl.block(
            "verified-build-loop integrity check failed:\n- " + "\n- ".join(problems) +
            "\nRestore the original content (for example with git), or stop and ask the user. "
            "Only the user can unprotect a file or accept a change to a protected file."
        )

    # 2. Skip when nothing changed since the last passing run
    excludes = config.get("fingerprint_exclude", [])
    passed_now = newly_passed(lock.get("feature_snapshot"), features)
    lock["config_snapshot"] = config
    if not first_run and not passed_now and lock.get("last_pass_fingerprint") == fingerprint(root, excludes):
        vbl.write_json_file(lock_path, lock)
        return 0

    # 3 and 4. Run checks
    checks = list(config.get("fast_checks", []))
    if passed_now:
        checks += list(config.get("full_checks", []))
    failures = []
    for check in checks:
        passed, report = vbl.run_check(root, check)
        if not passed:
            failures.append(report)

    if failures:
        report = "\n\n".join(failures)
        # Durations such as "in 0.08s" differ on every run; drop them so identical failures match.
        stable = DURATION.sub("", report)
        signature = hashlib.sha256(stable.encode("utf-8")).hexdigest()
        repeats = lock.get("failure_repeats", 0) + 1 if lock.get("last_failure") == signature else 1
        lock["last_failure"] = signature
        lock["failure_repeats"] = repeats
        vbl.write_json_file(lock_path, lock)  # feature_snapshot stays old, so the full checks run again next time
        if hook_input.get("stop_hook_active") and repeats >= REPEAT_LIMIT:
            print(json.dumps({"systemMessage":
                "verified-build-loop: the same checks failed {} times in a row with no change. "
                "Claude stopped without passing them. Failing output:\n{}".format(repeats, vbl.tail(report, 40))}))
            return 0
        header = "verified-build-loop: checks failed. Fix the cause, then finish your turn again."
        if passed_now:
            header += ("\nYou set \"passes\": true on {}. The full checks must pass first; "
                       "if the feature is not done, set it back to false.".format(", ".join(passed_now)))
        vbl.block(header + "\n\n" + report)

    lock["feature_snapshot"] = features
    lock["last_failure"] = None
    lock["failure_repeats"] = 0
    lock["last_pass_fingerprint"] = fingerprint(root, excludes)
    vbl.write_json_file(lock_path, lock)
    return 0


if __name__ == "__main__":
    _input = vbl.read_hook_input()
    sys.exit(vbl.run_stop_hook(main, _input))
