"""Rules files and test impact.

Rules: find agent instruction files, lint them, print a rewrite template for
negative rules, and compile the rules that name a blockable command into
`permissions.deny` entries plus an exec-form hook fragment.

Test impact: map changed files (from git) to the tests that cover them.

A written rule is context for the model, not enforcement; the compiled output
is the enforcement. Text matching has limits: a deny rule covers the spelling
the model usually produces and is not a security boundary around a program.
"""

import fnmatch
import os
import re
import subprocess
import sys

import ad_core

DEFAULT_MAX_LINES = 200
MAX_WALK_DEPTH = 4
GIT_TIMEOUT_SECONDS = 30
TEST_READ_BYTES = 256 * 1024
MIN_STEM_CHARS = 3
PREVIEW_CHARS = 160
MIN_DUPLICATE_WORDS = 3

# The bootstrap makes a hook whose script is missing exit 0 instead of blocking every call.
HOOK_BOOTSTRAP = ("import os,runpy,sys; p=sys.argv[1]; sys.argv=sys.argv[1:]; "
                  "os.path.isfile(p) and runpy.run_path(p, run_name='__main__')")
HOOK_TIMEOUT_SECONDS = 10

RULE_FILE_NAMES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "GEMINI.md", ".cursorrules", ".windsurfrules")
SKIPPED_DIRS = ("node_modules", ".git", ".venv", "venv", "env", "site-packages", "dist", "build",
                "__pycache__", "vendor", "third_party", "target", ".next", "worktrees")

KIND_SIZE = "size"
KIND_NEGATIVE = "negative-only"
KIND_VAGUE = "vague"
KIND_DUPLICATE = "duplicate"
KIND_BLOCKABLE = "blockable"
KIND_UNREADABLE = "unreadable"

_NEGATION = (r"(?:never|don't|dont|do not|must not|mustn't|cannot|can't|can not|shouldn't|should not"
             r"|avoid|prohibited|forbidden|under no circumstances)")
_NEGATION_RE = re.compile(r"\b%s\b" % _NEGATION, re.I)
_GOVERNING_NEGATION_RE = re.compile(
    r"^(?:(?:you|we|claude|agents?|the agent|please|always)\s+)?%s\b" % _NEGATION, re.I)
_PASSIVE_PROHIBITION_RE = re.compile(r"\b(?:is|are)\s+(?:prohibited|forbidden|not allowed|not permitted)\b", re.I)
_ALTERNATIVE_RE = re.compile(r"\b(?:instead|use|prefer|rather than|only)\b", re.I)
_VAGUE_RE = re.compile(
    r"\b(?:be careful|use (?:your )?best judge?ment|as appropriate|when needed|as needed|try to|if possible"
    r"|where applicable|where possible|if necessary)\b", re.I)
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_EMPHASIS_RE = re.compile(r"[*_]{1,3}")
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
_COMMAND_WORD_RE = re.compile(r"^[a-z][a-z0-9_+-]*$")
_PATH_SPAN_RE = re.compile(r"^[\w.\-/*]+$")

# Where a command may start inside a Bash command line: at the start, or after a separator.
_COMMAND_START = r"(?:^|[;&|(]\s*)(?:sudo\s+)?"
_WORD_END = r"(?=\s|$|[;&|)])"

# Families of blockable rules. `trigger` is matched against the rule text (code spans
# included); `when` pre-fills the rewrite template; `deny` lists permission rules; `regex`
# lists hook patterns.
_FAMILIES = (
    {
        "label": "force push",
        "when": "about to force-push",
        "trigger": r"force[- ]?push|push\s+(?:--force|-f)\b|git\s+push\s+\S*\s*--force",
        "deny": ("Bash(git push --force *)", "Bash(git push * --force)", "Bash(git push * --force *)",
                 "Bash(git push -f *)", "Bash(git push * -f)", "Bash(git push * -f *)"),
        "regex": (_COMMAND_START + r"git\s+(?:\S+\s+)*?push\b[^;&|]*\s(?:--force|-[a-zA-Z]*f[a-zA-Z]*|\+\S+)"
                  + _WORD_END,),
    },
    {
        "label": "recursive delete",
        "when": "about to delete recursively",
        "trigger": r"\brm\s+-(?:rf|fr|r|R)\b|recursive(?:ly)?[- ]delet",
        "deny": ("Bash(rm -rf *)", "Bash(rm -fr *)", "Bash(rm -r *)", "Bash(rm -R *)", "Bash(rm -Rf *)",
                 "Bash(rm --recursive *)"),
        "regex": (_COMMAND_START + r"(?:\S*/)?rm\s+(?:\S+\s+)*?(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)" + _WORD_END,),
    },
    {
        "label": "push to protected branch",
        "when": "about to push to main or master",
        "trigger": r"push(?:es|ing)?\s+(?:directly\s+|straight\s+)?(?:to|on|onto|into)\s+(?:the\s+)?`?(?:main|master)\b",
        "deny": ("Bash(git push * main)", "Bash(git push * main *)", "Bash(git push *:main)",
                 "Bash(git push * master)", "Bash(git push * master *)", "Bash(git push *:master)"),
        "regex": (_COMMAND_START + r"git\s+(?:\S+\s+)*?push\b[^;&|]*[\s:/+](?:main|master)" + _WORD_END,),
    },
    {
        "label": "package publish",
        "when": "about to publish a package",
        "trigger": r"\b(?:npm|pnpm|yarn)\s+publish|publish(?:es|ing)?\s+(?:to\s+)?(?:npm|the\s+registry)\b",
        "deny": ("Bash(npm publish *)", "Bash(pnpm publish *)", "Bash(yarn publish *)"),
        "regex": (_COMMAND_START + r"(?:npm|pnpm|yarn)\s+publish" + _WORD_END + r"(?![^;&|]*--dry-run)",),
    },
    {
        "label": "hard reset",
        "when": "about to hard-reset the worktree",
        "trigger": r"reset\s+--hard|hard[- ]reset",
        "deny": ("Bash(git reset --hard *)", "Bash(git reset * --hard)", "Bash(git reset * --hard *)"),
        "regex": (_COMMAND_START + r"git\s+(?:\S+\s+)*?reset\b[^;&|]*\s--hard" + _WORD_END,),
    },
    {
        "label": "destructive SQL",
        "when": "about to run destructive SQL",
        "trigger": r"\bdrop\s+(?:table|database|schema)s?\b|\btruncate\s+table",
        "deny": (),
        "regex": (r"(?i)" + _COMMAND_START + r"(?:psql|mysql|mariadb|sqlite3|sqlcmd|duckdb)\b[^;&|]*"
                  r"\b(?:drop\s+(?:table|database|schema)|truncate)\b",),
    },
    {
        "label": "production deploy",
        "when": "about to deploy to production",
        "trigger": r"\bvercel\s+(?:deploy\s+)?--prod|deploy(?:s|ing)?\s+(?:directly\s+)?to\s+prod(?:uction)?\b",
        "deny": ("Bash(vercel --prod *)", "Bash(vercel * --prod)", "Bash(vercel * --prod *)",
                 "Bash(netlify deploy --prod *)", "Bash(netlify deploy * --prod)", "Bash(netlify deploy * --prod *)"),
        "regex": (_COMMAND_START + r"(?:npx\s+)?(?:vercel|netlify)\b[^;&|]*\s--prod" + _WORD_END,),
    },
)
_FAMILY_TRIGGERS = tuple((family, re.compile(family["trigger"], re.I)) for family in _FAMILIES)

# ---------------------------------------------------------------- finding rule files


def _is_rule_file(directory_parts, name):
    """Return True when a file at `directory_parts/name` is an agent instruction file."""
    if name in RULE_FILE_NAMES:
        return True
    if name.endswith(".md") and ".claude" in directory_parts and "rules" in directory_parts:
        return directory_parts.index("rules") > directory_parts.index(".claude")
    if name.endswith(".mdc") and directory_parts[-2:] == [".cursor", "rules"]:
        return True
    return name == "copilot-instructions.md" and directory_parts[-1:] == [".github"]


def find_rule_files(root="."):
    """Return the agent instruction files under `root`, sorted, each real file once.

    Looks for CLAUDE.md, CLAUDE.local.md, .claude/CLAUDE.md, .claude/rules/*.md, AGENTS.md,
    GEMINI.md, .cursorrules, .cursor/rules/*.mdc, .windsurfrules and
    .github/copilot-instructions.md. Skips dependency and build directories, descends at
    most 4 levels and does not follow symlinked directories. A file given as `root` is
    returned as is, whatever its name.
    """
    if os.path.isfile(root):
        return [root]
    found = []
    seen = set()
    for directory, subdirectories, names in os.walk(root, followlinks=False):
        relative = os.path.relpath(directory, root)
        parts = [] if relative == "." else relative.split(os.sep)
        subdirectories[:] = sorted(name for name in subdirectories if name not in SKIPPED_DIRS)
        if len(parts) >= MAX_WALK_DEPTH:
            subdirectories[:] = []
        for name in sorted(names, key=lambda item: (os.path.islink(os.path.join(directory, item)), item)):
            if not _is_rule_file(parts, name):
                continue
            path = os.path.join(directory, name)
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            found.append(path)
    return sorted(found)


# ---------------------------------------------------------------- lint


def _rule_text(line):
    """Return a rules line without its bullet, emphasis markers and surrounding whitespace."""
    text = line.replace("\u2019", "'")
    text = _BULLET_RE.sub("", text)
    text = _EMPHASIS_RE.sub("", text)
    return " ".join(text.split())


def _prose(text):
    """Return rule text with code spans removed, so only the prose is judged."""
    return " ".join(_CODE_SPAN_RE.sub(" ", text).split())


def _is_prohibition(text):
    """Return True when the negation governs the rule: it starts the rule or a clause of it."""
    prose = _prose(text)
    if _GOVERNING_NEGATION_RE.match(prose) or _PASSIVE_PROHIBITION_RE.search(prose):
        return True
    return any(_GOVERNING_NEGATION_RE.match(clause.strip()) for clause in re.split(r"[;:.]\s+", prose)[1:])


def _rule_lines(lines):
    """Yield (line number, rule text) for the lines that are rules: not front matter, code or headings."""
    in_fence = False
    in_front_matter = bool(lines) and lines[0].strip() == "---"
    for number, line in enumerate(lines, 1):
        if in_front_matter:
            if number > 1 and line.strip() == "---":
                in_front_matter = False
            continue
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or _HEADING_RE.match(line) or line.startswith(("    ", "\t")):
            continue
        text = _rule_text(line)
        if text:
            yield number, text


def _command_regex(command):
    """Return a hook pattern that matches `command` at the start of a simple command."""
    words = [re.escape(word) for word in command.split()]
    return _COMMAND_START + r"\s+".join(words) + _WORD_END


def _looks_like_command(span):
    """Return True when a code span reads as a shell command (`terraform destroy`), not a path or a file name."""
    words = span.split()
    if not words or not _COMMAND_WORD_RE.match(words[0]):
        return False
    if len(words) == 1:
        return False
    return not any(char in span for char in "<>{}$")


def _first_alternative(text, start):
    """Return the index of the first word after `start` that introduces an alternative (`instead`, `use`), or -1."""
    match = _ALTERNATIVE_RE.search(_CODE_SPAN_RE.sub(lambda span: " " * len(span.group(0)), text), start)
    return match.start() if match else -1


def _blocked_spans(text):
    """Return the code spans the rule prohibits: those after the first negation, within its clause.

    The clause ends at a semicolon or at a word that introduces the alternative, so in
    "Do not hand-edit `dist/`; run `npm run build` instead" the build command is not blocked.
    """
    negation = _NEGATION_RE.search(text)
    if not negation:
        return []
    end = len(text)
    for boundary in (text.find(";", negation.end()), _first_alternative(text, negation.end())):
        if 0 <= boundary < end:
            end = boundary
    return [match.group(1).strip() for match in _CODE_SPAN_RE.finditer(text)
            if negation.start() < match.start() < end]


def blockable_rules(text):
    """Return the deny mappings for one rule line as a list of {"label", "deny", "deny_regex"}.

    A rule is blockable only when it is a prohibition and names a command: either a known
    family (force push, recursive delete, push to main, package publish, hard reset,
    destructive SQL, production deploy) or an explicit command in a code span after the
    negation. Prose that merely shares a keyword with a family is not mapped.
    """
    if not _NEGATION_RE.search(_prose(text)) and not _PASSIVE_PROHIBITION_RE.search(text):
        return []
    mappings = []
    covered_spans = []
    for family, trigger in _FAMILY_TRIGGERS:
        match = trigger.search(text)
        if not match:
            continue
        mappings.append({"label": family["label"], "deny": list(family["deny"]), "deny_regex": list(family["regex"])})
        covered_spans.extend(span for span in _blocked_spans(text) if trigger.search(span))
    for span in _blocked_spans(text):
        if span in covered_spans or not _looks_like_command(span):
            continue
        command = " ".join(span.split())
        mappings.append({
            "label": "command `%s`" % command,
            "deny": ["Bash(%s)" % command, "Bash(%s *)" % command],
            "deny_regex": [_command_regex(command)],
        })
    return mappings


def _duplicate_key(text):
    """Return the normalized form used to detect duplicate rule lines, or "" for lines too short to compare."""
    key = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    key = " ".join(key.split())
    if len(key.split()) < MIN_DUPLICATE_WORDS:
        return ""
    return key


def _finding(line, kind, message):
    """Build one lint finding."""
    return {"line": line, "kind": kind, "message": message}


def lint_rules(path, max_lines=DEFAULT_MAX_LINES):
    """Lint one rules file; return {"file", "lines", "findings", "hooks", "rewrites"}.

    Findings carry `line`, `kind` and `message`. Kinds: size (file longer than
    `max_lines`), negative-only (a prohibition with no stated alternative), vague (no
    testable trigger), duplicate (the same rule twice), blockable (the rule names a
    command that a deny rule can block; listed in `hooks` with the rules it compiles to).
    An unreadable file is reported as a finding instead of raising.
    """
    result = {"file": path, "lines": 0, "findings": [], "hooks": [], "rewrites": []}
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError as error:
        result["findings"].append(_finding(0, KIND_UNREADABLE, "cannot read the file (%s)" % error.strerror))
        return result
    result["lines"] = len(lines)
    if len(lines) > max_lines:
        message = ("%d lines. The Claude Code documentation says files over %d lines consume more context "
                   "and may reduce adherence; move task-specific sections into skills or path-scoped rules."
                   % (len(lines), DEFAULT_MAX_LINES))
        result["findings"].append(_finding(0, KIND_SIZE, message))
    first_seen = {}
    for number, text in _rule_lines(lines):
        mappings = blockable_rules(text)
        for mapping in mappings:
            hook = dict(mapping)
            hook["line"] = number
            hook["rule"] = ad_core.clean(text, PREVIEW_CHARS)
            result["hooks"].append(hook)
            targets = ", ".join(mapping["deny"][:2]) or "a hook pattern"
            result["findings"].append(_finding(number, KIND_BLOCKABLE,
                                               "names a blockable command (%s); `rules compile` maps it to %s"
                                               % (mapping["label"], targets)))
        prohibition = _is_prohibition(text)
        if prohibition:
            template = rewrite_template(text)
            if template:
                result["rewrites"].append({"line": number, "template": template})
        if prohibition and not mappings and not _ALTERNATIVE_RE.search(_prose(text)):
            result["findings"].append(_finding(number, KIND_NEGATIVE,
                                               "negative-only rule: it says what not to do and names no "
                                               "alternative; state the trigger, the positive action and a check"))
        if _VAGUE_RE.search(_prose(text)) and not _CODE_SPAN_RE.search(text):
            result["findings"].append(_finding(number, KIND_VAGUE, "vague rule: no testable trigger or condition"))
        key = _duplicate_key(text)
        if key and key in first_seen:
            result["findings"].append(_finding(number, KIND_DUPLICATE, "duplicate of line %d" % first_seen[key]))
        elif key:
            first_seen[key] = number
    return result


def _trigger_for(text):
    """Return the pre-filled trigger of a rewrite template when the rule names a command or a path."""
    for span in _blocked_spans(text) or [match.group(1) for match in _CODE_SPAN_RE.finditer(text)]:
        if _looks_like_command(span) or any(trigger.search(span) for _, trigger in _FAMILY_TRIGGERS):
            return "about to run `%s`" % span
        if _PATH_SPAN_RE.match(span) and ("/" in span or "." in span):
            return "about to change `%s`" % span
    for family, trigger in _FAMILY_TRIGGERS:
        if trigger.search(text):
            return family["when"]
    return "<trigger>"


def rewrite_template(line):
    """Return the rewrite template for a negative rule, or None when the line is not one.

    The result shows the original rule and the template `When <trigger>, do <positive
    action>; check <observable>.` with the trigger pre-filled when the rule names a command
    or a path. It does not rewrite the rule: the positive action and the check are for the
    author to fill in.
    """
    if not isinstance(line, str):
        return None
    if _FENCE_RE.match(line) or _HEADING_RE.match(line):
        return None
    text = _rule_text(line)
    if not text or not _is_prohibition(text):
        return None
    return "original: %s | template: When %s, do <positive action>; check <observable>." % (
        ad_core.clean(text, PREVIEW_CHARS), _trigger_for(text))


# ---------------------------------------------------------------- compile


def default_script_path():
    """Return the absolute path of the `ad.py` next to this module."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "ad.py")


def _valid_patterns(patterns):
    """Return the patterns that compile as Python regexes, in first-seen order without duplicates."""
    kept = []
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error:
            continue
        if pattern not in kept:
            kept.append(pattern)
    return kept


def compile_rules(results, script_path=None):
    """Compile lint results into enforcement configuration.

    Returns a dict with:
    - `permissions.deny`: permission rules for a Claude Code settings file; they need no script;
    - `hooks`: an exec-form PreToolUse hook (matcher Bash) that runs `ad.py deny-regex PATTERN...`
      through a bootstrap that exits 0 when the script is missing; empty when no rule compiled;
    - `sources`: one line per compiled rule (file, line, label), for review;
    - `note`: where the output goes and its limits.
    Exec form passes each argument verbatim, so the patterns are ordinary Python regexes
    with single backslashes and no shell quoting.
    """
    deny = []
    patterns = []
    sources = []
    for result in results:
        for hook in result.get("hooks") or []:
            deny.extend(rule for rule in hook.get("deny") or [] if rule not in deny)
            patterns.extend(hook.get("deny_regex") or [])
            sources.append("%s:%s %s: %s" % (result.get("file"), hook.get("line"), hook.get("label"),
                                             hook.get("rule")))
    patterns = _valid_patterns(patterns)
    script = script_path or default_script_path()
    hooks = {}
    if patterns:
        handler = {
            "type": "command",
            "command": "python3",
            "args": ["-c", HOOK_BOOTSTRAP, script, "deny-regex"] + patterns,
            "timeout": HOOK_TIMEOUT_SECONDS,
        }
        hooks = {"PreToolUse": [{"matcher": "Bash", "hooks": [handler]}]}
    note = ("Merge `permissions.deny` and `hooks` into a Claude Code settings file such as "
            ".claude/settings.json. The deny rules need no script. The hook runs the script at %s; "
            "an absolute path is machine-specific, so pass --script-path with a path that exists "
            "wherever the settings file loads. Deny rules and patterns match the command text and "
            "are not a security boundary around a program. claude.ai has no hooks." % script)
    return {"permissions": {"deny": deny}, "hooks": hooks, "sources": sources, "note": note}


def deny_regex_hook(patterns):
    """PreToolUse hook body: deny the Bash command when any pattern matches it.

    Reads only `tool_input.command`. Invalid patterns are skipped with a note on stderr.
    Fail-open: any other problem lets the call proceed.
    """
    inp = ad_core.read_hook_input()
    tool_input = inp.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        ad_core.allow()
        return
    for pattern in patterns:
        try:
            matched = re.search(pattern, command)
        except re.error as error:
            sys.stderr.write("deny-regex: skipping invalid pattern %r (%s)\n" % (pattern, error))
            continue
        if matched:
            ad_core.deny("compiled rule: blocked, the command matches a deny pattern compiled from the project's "
                         "rules file: `%s`. Matched text: `%s`. Next step: use the alternative the rules file "
                         "names, or ask the user." % (ad_core.clean(ad_core.redact(command), PREVIEW_CHARS),
                                                      ad_core.clean(matched.group(0).strip(), 80)))
            return
    ad_core.allow()


# ---------------------------------------------------------------- test impact: changed files


def _git(root, args):
    """Run a read-only git command in `root`; return (exit code, stdout). Raises ValueError when git cannot run."""
    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        completed = subprocess.run(["git", "-C", root] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=GIT_TIMEOUT_SECONDS, env=environment)
    except FileNotFoundError:
        raise ValueError("git is not installed; cannot determine the changed files")
    except subprocess.TimeoutExpired:
        raise ValueError("git did not answer within %d seconds" % GIT_TIMEOUT_SECONDS)
    return completed.returncode, completed.stdout.decode("utf-8", "replace")


def _name_status(output):
    """Parse `git diff --name-status -z --no-renames` output into (changed, deleted) path lists."""
    fields = [field for field in output.split("\0")]
    changed = []
    deleted = []
    index = 0
    while index + 1 < len(fields):
        status = fields[index]
        path = fields[index + 1]
        index += 2
        if not status or not path:
            continue
        if status.startswith("D"):
            deleted.append(path)
        else:
            changed.append(path)
    return changed, deleted


def _resolve_base(top, base):
    """Return the commit id of `base`; raises ValueError for an option-like or unknown ref."""
    if not isinstance(base, str) or not base.strip():
        raise ValueError("empty --base")
    if base.startswith("-"):
        raise ValueError("invalid --base %r: a ref cannot start with '-'" % base)
    code, output = _git(top, ["rev-parse", "--verify", "--quiet", base + "^{commit}"])
    if code != 0 or not output.strip():
        raise ValueError("unknown --base ref %r" % base)
    return output.strip()


def changed_files(base=None, root="."):
    """Return (changed, deleted): the files that differ from HEAD, plus those changed since `base`.

    The union of staged and unstaged changes against HEAD, untracked files, and, when
    `base` is given, the commits on HEAD since the merge base with `base`. Paths are
    relative to `root`, use `/`, and are read NUL-separated, so names with spaces survive.
    Deleted files are listed separately. Raises ValueError outside a git repository, for
    a `base` that starts with `-`, and for an unknown ref.
    """
    if not os.path.isdir(root):
        raise ValueError("no such directory: %s" % root)
    code, output = _git(root, ["rev-parse", "--show-toplevel"])
    if code != 0 or not output.strip():
        raise ValueError("not a git repository: %s" % os.path.abspath(root))
    top = output.strip()
    diff = ["diff", "--name-status", "-z", "--no-renames"]
    changed = []
    deleted = []
    has_head = _git(top, ["rev-parse", "--verify", "--quiet", "HEAD^{commit}"])[0] == 0
    comparisons = [diff + ["HEAD", "--"]] if has_head else [diff + ["--cached", "--"], diff + ["--"]]
    if base is not None:
        commit = _resolve_base(top, base)
        comparisons.append(diff + [commit + "...HEAD", "--"])
    for arguments in comparisons:
        code, output = _git(top, arguments)
        if code != 0:
            raise ValueError("git %s failed" % " ".join(arguments[:1]))
        found_changed, found_deleted = _name_status(output)
        changed.extend(found_changed)
        deleted.extend(found_deleted)
    code, output = _git(top, ["ls-files", "-z", "--others", "--exclude-standard"])
    if code == 0:
        changed.extend(name for name in output.split("\0") if name)
    real_root = os.path.realpath(root)

    def relative(name):
        return os.path.relpath(os.path.join(os.path.realpath(top), name), real_root).replace(os.sep, "/")

    existing = sorted(set(relative(name) for name in changed if os.path.lexists(os.path.join(top, name))))
    gone = sorted(set(relative(name) for name in changed + deleted
                      if not os.path.lexists(os.path.join(top, name))))
    return existing, gone


# ---------------------------------------------------------------- test impact: discovery and mapping

_JS_EXTENSIONS = ("js", "jsx", "ts", "tsx", "mjs", "cjs", "mts", "cts")
_TEST_NAME_PATTERNS = (
    "test_*.py", "*_test.py",
    "*_test.go",
    "*Test.java", "*Tests.java", "*Test.kt", "*Tests.kt",
    "*_spec.rb", "*_test.rb",
    "*Tests.cs", "*Test.php", "*Tests.swift",
    "*_test.exs", "*_test.cc", "*_test.cpp",
)
_JS_TEST_RE = re.compile(r"\.(?:test|spec)\.(?:%s)$" % "|".join(_JS_EXTENSIONS))
_JS_FILE_RE = re.compile(r"\.(?:%s)$" % "|".join(_JS_EXTENSIONS))
_TEST_AFFIX_RE = re.compile(r"^(?:test_|tests_)|(?:_test|_tests|_spec|\.test|\.spec|Tests?|Spec)$")
_SOURCE_EXTENSIONS = ("py", "go", "rs", "java", "kt", "rb", "cs", "php", "swift", "c", "cc", "cpp", "h", "hpp",
                      "ex", "exs", "scala", "sh") + _JS_EXTENSIONS
_GENERIC_STEMS = ("index", "main", "utils", "util", "init", "__init__", "types", "test", "tests", "app", "helpers",
                  "config", "constants", "base", "common", "mod", "lib")
_SHARED_NAMES = (
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "pyproject.toml",
    "poetry.lock", "uv.lock", "setup.py", "setup.cfg", "Pipfile", "Pipfile.lock", "Cargo.toml", "Cargo.lock",
    "go.mod", "go.sum", "pytest.ini", "tox.ini", "conftest.py", "Makefile", "Dockerfile", "pom.xml",
    "build.gradle", "build.gradle.kts", "settings.gradle", "Gemfile", "Gemfile.lock", "composer.json",
    "composer.lock", "Package.swift", "mix.exs", "CMakeLists.txt", ".babelrc",
)
_SHARED_PATTERNS = ("requirements*.txt", "tsconfig*.json", "jest.config.*", "vitest.config.*", "vite.config.*",
                    "webpack.config.*", "babel.config.*", "jest.setup.*", "*.csproj", "*.sln")
_TEST_SUPPORT_DIRS = ("fixtures", "helpers", "testdata", "__fixtures__", "__mocks__", "support")
_TEST_DIRS = ("tests", "test", "__tests__", "spec")


def _is_test_path(path):
    """Return True when a `/`-separated relative path is a test file by its language's convention."""
    name = path.rsplit("/", 1)[-1]
    directories = path.split("/")[:-1]
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in _TEST_NAME_PATTERNS):
        return True
    if _JS_TEST_RE.search(name):
        return True
    if "__tests__" in directories and _JS_FILE_RE.search(name):
        return True
    return name.endswith(".rs") and "tests" in directories


def discover_tests(root="."):
    """Return the test files under `root` (relative, `/`-separated, sorted), found by naming convention.

    Python `test_*.py`, `*_test.py`; JS/TS `*.test.*`, `*.spec.*`, files under `__tests__/`;
    Go `*_test.go`; Rust files under `tests/`; Java/Kotlin `*Test`, `*Tests`; Ruby
    `*_spec.rb`, `*_test.rb`; C# `*Tests.cs`; PHP `*Test.php`; Swift `*Tests.swift`.
    """
    found = []
    for directory, subdirectories, names in os.walk(root, followlinks=False):
        subdirectories[:] = [name for name in subdirectories if name not in SKIPPED_DIRS]
        relative = os.path.relpath(directory, root)
        for name in names:
            path = name if relative == "." else os.path.join(relative, name).replace(os.sep, "/")
            if _is_test_path(path):
                found.append(path)
    return sorted(found)


def _extension(path):
    """Return the lower-case file extension without the dot, or ""."""
    name = path.rsplit("/", 1)[-1]
    if "." not in name.lstrip("."):
        return ""
    return name.rsplit(".", 1)[1].lower()


def _stem(path):
    """Return the file name without its extension."""
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name.lstrip(".") else name


def _shared_reason(path):
    """Return why a changed file calls for the full suite, or "" when it does not."""
    name = path.rsplit("/", 1)[-1]
    directories = path.split("/")[:-1]
    if name in _SHARED_NAMES or any(fnmatch.fnmatchcase(name, pattern) for pattern in _SHARED_PATTERNS):
        return "shared or configuration file changed: %s" % path
    if directories[:2] == [".github", "workflows"]:
        return "CI configuration changed: %s" % path
    in_test_tree = any(part in _TEST_DIRS for part in directories)
    if in_test_tree and any(part in _TEST_SUPPORT_DIRS for part in directories):
        return "shared test support file changed: %s" % path
    return ""


def _name_matches(stem, test_path):
    """Return True when the test file name contains the source stem as a whole word."""
    bare = _TEST_AFFIX_RE.sub("", _stem(test_path))
    if bare.lower() == stem.lower():
        return True
    return re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(stem), bare, re.I) is not None


class _TestContents(object):
    """Read each test file at most once (the first 256 KB), on demand."""

    def __init__(self, root):
        self.root = root
        self.cache = {}

    def get(self, test_path):
        """Return the cached text of a test file, or "" when it cannot be read."""
        if test_path not in self.cache:
            try:
                with open(os.path.join(self.root, test_path), "rb") as handle:
                    self.cache[test_path] = handle.read(TEST_READ_BYTES).decode("utf-8", "replace")
            except OSError:
                self.cache[test_path] = ""
        return self.cache[test_path]


def _tests_for(stem, tests, contents):
    """Return {test path: basis} for the tests that match a source stem by name or by content."""
    matched = {}
    reference = re.compile(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(stem))
    for test_path in tests:
        if _name_matches(stem, test_path):
            matched[test_path] = "name"
        elif reference.search(contents.get(test_path)):
            matched[test_path] = "content"
    return matched


def _advice(changed, deleted, run, reason, unmapped, source_count):
    """Return the one-line advice for a test-impact result."""
    if not changed and not deleted:
        return "no changes detected"
    if reason:
        return "run the full suite: %s" % reason
    if unmapped:
        return ("no test maps to %s; run the full suite or the tests of that package, because name matching "
                "found nothing" % ", ".join(unmapped))
    if run:
        return "run the %d mapped test file(s) first; run the full suite before merging" % len(run)
    if source_count == 0:
        return "no source or test file changed; no tests selected"
    return "no mapped tests; run the full suite"


def test_impact(files, root=".", deleted=None):
    """Map changed files to the tests to run; return a dict.

    Keys: `changed`, `deleted`, `run` (test files to run), `mapped` (source file to the
    tests chosen for it, with the basis `name` or `content`), `full_suite_reason` (set when
    a shared or configuration file changed), `unmapped` (changed source files with no
    test), `skipped_count`, `total_tests`, `advice`. A changed test file runs itself. A
    source file maps to tests whose name contains its stem as a whole word, or whose
    content references the stem; stems shorter than 3 characters and generic stems such as
    `index` or `utils` map to nothing. Deleted files never appear in `run`.
    """
    changed = sorted(set(path.replace(os.sep, "/") for path in files or []))
    gone = sorted(set(path.replace(os.sep, "/") for path in deleted or []))
    tests = discover_tests(root)
    test_set = set(tests)
    contents = _TestContents(root)
    run = set()
    mapped = {}
    unmapped = []
    reasons = []
    source_count = 0
    for path in changed + gone:
        is_deleted = path in gone and path not in changed
        if path in test_set or _is_test_path(path):
            if not is_deleted and path in test_set:
                run.add(path)
            continue
        reason = _shared_reason(path)
        if reason:
            reasons.append(reason)
            continue
        if _extension(path) not in _SOURCE_EXTENSIONS:
            continue
        source_count += 1
        stem = _stem(path)
        usable = len(stem) >= MIN_STEM_CHARS and stem.lower() not in _GENERIC_STEMS
        matches = _tests_for(stem, tests, contents) if usable else {}
        if matches:
            mapped[path] = [{"test": test_path, "basis": matches[test_path]} for test_path in sorted(matches)]
            run.update(matches)
        elif not is_deleted:
            unmapped.append(path)
    run_list = sorted(run)
    reason_text = "; ".join(reasons) if reasons else None
    return {
        "changed": changed,
        "deleted": gone,
        "run": run_list,
        "mapped": mapped,
        "full_suite_reason": reason_text,
        "unmapped": unmapped,
        "skipped_count": len(tests) - len(run_list),
        "total_tests": len(tests),
        "advice": _advice(changed, gone, run_list, reason_text, unmapped, source_count),
    }


# Keep test runners from collecting `test_impact` as a test function.
test_impact.__test__ = False
