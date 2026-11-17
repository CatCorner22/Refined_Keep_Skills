#!/usr/bin/env python3
"""Build tool for the agent-discipline skills repository.

Sub-commands:

  sync      copy every lib/*.py into scripts/ of each scripted skill
  check     list every packaging defect (drift, frontmatter, references, stale zips)
  validate  run the upload validator's checks on every skill folder
  zip       write dist/<name>.zip for every skill, deterministically
  all       sync, check, validate, zip, then confirm the zips

Why this file exists: lib/ is the only hand-edited copy of the CLI library.
Each scripted skill carries a generated copy so that the skill folder is
self-contained on every surface. This tool makes the copies, proves that they
match, and builds the upload packages for claude.ai.

Standard library only. PyYAML is optional: when it imports, the frontmatter is
parsed a second time with it as a cross-check. Runs on Python 3.8 or later.
"""

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

VERSION_DEFAULT = "2.1.0"

SCRIPTED_SKILLS = (
    "autonomy-ledger",
    "backward-review-gate",
    "claim-evidence-pairing",
    "completion-evidence-gate",
    "context-budget-governor",
    "inventory-before-fetch",
    "model-sanity-regression",
    "negative-constraint-compiler",
    "read-manifest",
    "rules-hygiene",
    "scope-and-blast-radius-check",
    "test-impact-selector",
)

SCRIPT_FREE_SKILLS = (
    "ask-or-assume",
    "narrow-read-discipline",
    "premise-check",
    "retrieval-verification-gate",
    "tool-call-validator",
)

# Skills that ship scripts of their own (not a copy of lib/).
OWN_SCRIPT_SKILLS = ("living-reference",)

ALL_SKILLS = tuple(sorted(SCRIPTED_SKILLS + SCRIPT_FREE_SKILLS + OWN_SCRIPT_SKILLS))

LIB_FILES = (
    "ad.py",
    "ad_core.py",
    "ad_gates.py",
    "ad_guards.py",
    "ad_regress.py",
    "ad_rules.py",
    "ad_shell.py",
    "ad_state.py",
)

# The CLI surface of lib/ad.py: each sub-command and its second-level names.
# An empty tuple means the sub-command takes arguments, not a second-level name.
# tests/test_packaging.py compares this table with the real ad.py.
AD_SUBCOMMANDS = {
    "version": (),
    "manifest": ("record", "check", "show"),
    "ledger": ("add", "check", "show", "clear"),
    "checkpoint": ("write", "show"),
    "reinject": (),
    "scope": ("set", "add", "show"),
    "approve": (),
    "approvals": ("show", "clear"),
    "fence-check": (),
    "fetch-check": (),
    "gate": (),
    "review": (),
    "trim": (),
    "provenance": ("add", "show", "audit"),
    "rules": ("lint", "rewrite", "compile"),
    "test-impact": (),
    "regress": ("init", "show", "record", "report"),
    "deny-regex": (),
    "hook": (
        "session-start",
        "pre-bash",
        "pre-write",
        "pre-fetch",
        "read-cache",
        "record-read",
        "log",
        "log-failure",
        "completion-gate",
        "review-gate",
        "stop",
        "pre-plan",
        "review-reminder",
        "reinject",
        "fetch-guard",
        "scope-fence",
        "validate-call",
        "log-trim",
    ),
}

# Sub-commands that change what the scope fence allows. They must prompt the
# user, so no skill may pre-approve them. The two read-only forms are exempt.
NEVER_PREAPPROVED_SUBCOMMANDS = ("approve", "approvals", "scope")
PREAPPROVED_READ_ONLY_FORMS = ("approvals show", "scope show")

# Frontmatter keys this repository uses (SKILL.md style guide).
REPO_FRONTMATTER_KEYS = ("name", "description", "compatibility", "metadata", "allowed-tools")

# Frontmatter keys the claude.ai upload validator accepts.
UPLOAD_FRONTMATTER_KEYS = REPO_FRONTMATTER_KEYS + ("license",)

MAX_DESCRIPTION_CHARS = 400
MAX_SKILL_MD_LINES = 500
UPLOAD_MAX_NAME_CHARS = 64
UPLOAD_MAX_DESCRIPTION_CHARS = 1024
UPLOAD_MAX_COMPATIBILITY_CHARS = 500

SKILL_DIR_PLACEHOLDER = "${CLAUDE_SKILL_DIR}"

# Zip packaging.
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
ZIP_MODE_FILE = 0o644
ZIP_MODE_SCRIPT = 0o755
ZIP_COMPRESS_LEVEL = 9
ZIP_UNIX_SYSTEM = 3
ZIP_REGULAR_FILE_FLAG = 0o100000
ZIP_EXCLUDED_DIRS = ("__pycache__", "tests", ".agent")
ZIP_EXCLUDED_FILES = (".DS_Store",)
ZIP_EXCLUDED_SUFFIXES = (".pyc", ".pyo")

# Folders the upload validator ignores when it counts SKILL.md files.
VALIDATOR_EXCLUDED_DIRS = ("__pycache__", "node_modules")
VALIDATOR_ROOT_EXCLUDED_DIRS = ("evals",)

# Skill names that existed in drafts of version 1 and must not be named any more.
REMOVED_SKILLS = ("tool-output-trimmer",)

RELATED_BULLET = re.compile(r"^\s*[-*]\s+[`*_]*([A-Za-z0-9\-]+)[`*_]*\s*(?::|\(|\u2014|-|,|$)")
USE_SIBLING = re.compile(
    r"\buse (?:the )?[`*_]*(?<![A-Za-z0-9\-])([a-z0-9]+(?:-[a-z0-9]+)+)[`*_]*"
    r"(?=[.,;)]|$| if installed| instead| skill| \()"
)
KEBAB_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
SCRIPT_REFERENCE = re.compile(r"scripts/[A-Za-z0-9_\-]+\.py")
AD_EXAMPLE = re.compile(r'python3 "\$\{CLAUDE_SKILL_DIR\}/scripts/ad\.py"([^`\n]*)')
PLAIN_WORD = re.compile(r"^[a-z][a-z0-9\-]*$")
ALLOWED_TOOLS_AD_RULE = re.compile(
    r'Bash\(python3 "\$\{CLAUDE_SKILL_DIR\}/scripts/ad\.py" ([^)]*)\)'
)
BARE_PYTHON_RULE = re.compile(r"Bash\(python3?(?::\*| \*)?\)")
READ_TOOL_RULE = re.compile(r"(?<![A-Za-z])(Read|Grep|Glob)(?![A-Za-z])")


class BuildError(Exception):
    """A problem that stops the build tool itself (missing lib/, bad arguments)."""


class FrontmatterError(Exception):
    """The SKILL.md frontmatter cannot be parsed."""


# ---------------------------------------------------------------- paths

def default_root():
    """Return the repository root: the parent of the tools/ directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def lib_dir(root):
    return os.path.join(root, "lib")


def skills_dir(root):
    return os.path.join(root, ".claude", "skills")


def skill_dir(root, name):
    return os.path.join(skills_dir(root), name)


def dist_dir(root):
    return os.path.join(root, "dist")


def zip_path(root, name):
    return os.path.join(dist_dir(root), name + ".zip")


def relative(root, path):
    """Return path relative to root with forward slashes, for messages."""
    return os.path.relpath(path, root).replace(os.sep, "/")


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def read_text(path):
    with io.open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
        return handle.read()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def lib_sources(root):
    """Return the sorted names of lib/*.py. Raise BuildError when lib/ is absent."""
    directory = lib_dir(root)
    if not os.path.isdir(directory):
        raise BuildError("lib/ not found under " + root)
    names = [name for name in os.listdir(directory) if name.endswith(".py")]
    return sorted(names)


def present_skills(root):
    """Return the names of the folders under .claude/skills/, sorted."""
    directory = skills_dir(root)
    if not os.path.isdir(directory):
        return []
    names = []
    for name in sorted(os.listdir(directory)):
        if os.path.isdir(os.path.join(directory, name)):
            names.append(name)
    return names


# ---------------------------------------------------------------- frontmatter

def split_frontmatter(text):
    """Split SKILL.md text into (frontmatter text, body text).

    Mirrors the upload validator: the file must start with a `---` line and the
    frontmatter ends at the next `---` line.
    """
    text = text.replace("\r\n", "\n")
    if not text.startswith("---"):
        raise FrontmatterError("no YAML frontmatter found")
    match = re.match(r"^---\n(.*?)\n---[ \t]*(?:\n|$)", text, re.DOTALL)
    if not match:
        raise FrontmatterError("invalid frontmatter format")
    return match.group(1), text[match.end():]


def _unquote_scalar(raw, line_number):
    """Convert one YAML scalar (single-quoted, double-quoted or plain) to a string."""
    value = raw.strip()
    if value.startswith('"'):
        if len(value) < 2 or not value.endswith('"'):
            raise FrontmatterError("line %d: unterminated double-quoted value" % line_number)
        inner = value[1:-1]
        inner = inner.replace("\\\\", "\x00")
        inner = inner.replace('\\"', '"')
        inner = inner.replace("\\n", "\n")
        inner = inner.replace("\\t", "\t")
        return inner.replace("\x00", "\\")
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise FrontmatterError("line %d: unterminated single-quoted value" % line_number)
        return value[1:-1].replace("''", "'")
    if value[:1] in ("[", "{", "*", "&", "!", "%", "@", "`", "|", ">"):
        raise FrontmatterError("line %d: unsupported plain value; quote the value" % line_number)
    if ": " in value or value.endswith(":"):
        raise FrontmatterError(
            "line %d: a plain value contains a colon followed by a space; quote the value" % line_number
        )
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def _parse_block(lines, line_number):
    """Parse the indented lines under a key: a list, a map of scalars, or folded text."""
    stripped = [line.strip() for line in lines if line.strip()]
    if not stripped:
        return ""
    if all(item.startswith("- ") or item == "-" for item in stripped):
        return [_unquote_scalar(item[1:], line_number) for item in stripped]
    result = {}
    for item in stripped:
        match = re.match(r"^([A-Za-z0-9_\-]+):(?:\s+(.*))?$", item)
        if not match:
            raise FrontmatterError("line %d: cannot parse nested line %r" % (line_number, item))
        result[match.group(1)] = _unquote_scalar(match.group(2) or "", line_number)
    return result


def parse_frontmatter(frontmatter_text):
    """Parse the YAML subset that SKILL.md frontmatter uses, with the standard library.

    Supported: top-level `key: scalar`, a nested map of scalars, a list of
    scalars, and `>` or `|` block text. Anything else raises FrontmatterError,
    which is the safe result for a file that must also pass a strict upload
    validator.
    """
    result = {}
    lines = frontmatter_text.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        line_number = index + 1
        index += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            raise FrontmatterError("line %d: unexpected indentation" % line_number)
        match = re.match(r"^([A-Za-z0-9_\-]+):(?:[ \t]+(.*))?$", line)
        if not match:
            raise FrontmatterError("line %d: expected `key: value`" % line_number)
        key = match.group(1)
        raw = (match.group(2) or "").strip()
        if key in result:
            raise FrontmatterError("line %d: duplicate key %r" % (line_number, key))
        block = []
        while index < len(lines) and (not lines[index].strip() or lines[index][0] in " \t"):
            block.append(lines[index])
            index += 1
        if raw in (">", "|", ">-", "|-", ">+", "|+"):
            joiner = " " if raw.startswith(">") else "\n"
            result[key] = joiner.join(item.strip() for item in block if item.strip())
        elif raw == "":
            result[key] = _parse_block(block, line_number)
        else:
            if any(item.strip() for item in block):
                raise FrontmatterError("line %d: value continues on the next line; quote it on one line" % line_number)
            result[key] = _unquote_scalar(raw, line_number)
    return result


def yaml_cross_check(frontmatter_text, parsed):
    """Compare the stdlib parse with PyYAML. Return (findings, yaml_available)."""
    try:
        import yaml
    except ImportError:
        return [], False
    try:
        loaded = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as error:
        return ["PyYAML rejects the frontmatter: %s" % str(error).replace("\n", " ")], True
    if not isinstance(loaded, dict):
        return ["PyYAML: the frontmatter is not a mapping"], True
    findings = []
    if sorted(str(key) for key in loaded) != sorted(parsed):
        findings.append("PyYAML sees different frontmatter keys: %s" % sorted(str(key) for key in loaded))
    for key in ("name", "description", "compatibility", "allowed-tools"):
        if key in loaded and key in parsed and loaded[key] != parsed[key]:
            findings.append("PyYAML reads a different value for %r" % key)
    return findings, True


def load_skill(root, name):
    """Read one skill. Return a dict with text, frontmatter, body and any parse error."""
    path = os.path.join(skill_dir(root, name), "SKILL.md")
    skill = {"name": name, "path": path, "text": None, "frontmatter": None, "frontmatter_text": "", "body": "", "error": None}
    if not os.path.isfile(path):
        skill["error"] = "SKILL.md not found"
        return skill
    skill["text"] = read_text(path)
    try:
        frontmatter_text, body = split_frontmatter(skill["text"])
        skill["frontmatter_text"] = frontmatter_text
        skill["body"] = body
        skill["frontmatter"] = parse_frontmatter(frontmatter_text)
    except FrontmatterError as error:
        skill["error"] = str(error)
    return skill


# ---------------------------------------------------------------- sync

def sync(root):
    """Copy lib/*.py into scripts/ of every scripted skill. Return report lines.

    Stray entries in a generated scripts/ directory are removed, so the copy is
    exactly lib/. A scripted skill whose folder has no SKILL.md yet is skipped.
    """
    sources = lib_sources(root)
    if not sources:
        raise BuildError("lib/ holds no .py files")
    report = []
    for name in SCRIPTED_SKILLS:
        folder = skill_dir(root, name)
        if not os.path.isfile(os.path.join(folder, "SKILL.md")):
            report.append("skipped %s: no SKILL.md yet" % name)
            continue
        target = os.path.join(folder, "scripts")
        os.makedirs(target, exist_ok=True)
        changed = 0
        for entry in sorted(os.listdir(target)):
            if entry in sources:
                continue
            stray = os.path.join(target, entry)
            if os.path.isdir(stray) and not os.path.islink(stray):
                shutil.rmtree(stray)
            else:
                os.remove(stray)
            changed += 1
        for source_name in sources:
            source = os.path.join(lib_dir(root), source_name)
            destination = os.path.join(target, source_name)
            if os.path.islink(destination):
                os.remove(destination)
            if os.path.isfile(destination) and read_bytes(destination) == read_bytes(source):
                shutil.copymode(source, destination)
                continue
            shutil.copyfile(source, destination)
            shutil.copymode(source, destination)
            changed += 1
        report.append("synced %s: %d file(s) changed" % (name, changed))
    return report


# ---------------------------------------------------------------- check

def check_copies(root):
    """Findings for generated scripts/ copies that differ from lib/."""
    findings = []
    try:
        sources = lib_sources(root)
    except BuildError as error:
        return [str(error)]
    for expected in LIB_FILES:
        if expected not in sources:
            findings.append("lib/%s: missing from the library" % expected)
    for name in SCRIPTED_SKILLS:
        folder = skill_dir(root, name)
        if not os.path.isdir(folder):
            continue
        target = os.path.join(folder, "scripts")
        label = relative(root, target)
        if not os.path.isdir(target):
            findings.append("%s: missing; run tools/build.py sync" % label)
            continue
        entries = sorted(os.listdir(target))
        for entry in entries:
            if entry not in sources:
                findings.append("%s/%s: stray entry; run tools/build.py sync" % (label, entry))
        for source_name in sources:
            copy = os.path.join(target, source_name)
            if not os.path.isfile(copy) or os.path.islink(copy):
                findings.append("%s/%s: missing; run tools/build.py sync" % (label, source_name))
                continue
            if read_bytes(copy) != read_bytes(os.path.join(lib_dir(root), source_name)):
                findings.append(
                    "%s/%s: differs from lib/%s; edit lib/ only, then run tools/build.py sync"
                    % (label, source_name, source_name)
                )
    for name in SCRIPT_FREE_SKILLS:
        target = os.path.join(skill_dir(root, name), "scripts")
        if os.path.exists(target):
            findings.append("%s: a script-free skill must not have a scripts/ directory" % relative(root, target))
    return findings


def check_skill_set(root):
    """Findings for missing or unexpected skill folders."""
    findings = []
    present = present_skills(root)
    for name in ALL_SKILLS:
        if name not in present:
            findings.append(".claude/skills/%s: skill folder missing" % name)
    for name in present:
        if name not in ALL_SKILLS:
            findings.append(".claude/skills/%s: unexpected folder (not one of the 18 skills)" % name)
    return findings


def inline_code_spans(line):
    """Return the text of each `inline code` span on one line."""
    return re.findall(r"`([^`]+)`", line)


def unprefixed_script_commands(body):
    """Return (line number, line) for commands that run scripts/*.py without the placeholder.

    A command is a script reference inside a fenced code block, or inside an
    inline code span that also holds an interpreter name or an argument. A bare
    file name in prose (`scripts/ad.py`) is a mention, not a command.
    """
    hits = []
    in_fence = False
    prefix = SKILL_DIR_PLACEHOLDER + "/"
    for number, line in enumerate(body.split("\n"), 1):
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            in_fence = not in_fence
            continue
        regions = [line] if in_fence else inline_code_spans(line)
        for region in regions:
            is_command = in_fence or "python" in region or " " in region.strip()
            if not is_command:
                continue
            for match in SCRIPT_REFERENCE.finditer(region):
                if region[: match.start()].endswith(prefix):
                    continue
                hits.append((number, line.strip()))
                break
    return hits


def ad_example_findings(text):
    """Return messages for ad.py examples that name an unknown sub-command."""
    messages = []
    for number, line in enumerate(text.split("\n"), 1):
        for match in AD_EXAMPLE.finditer(line):
            words = []
            for token in match.group(1).split():
                words.append(token.rstrip(".,;:)'\""))
            if not words:
                continue
            sub = words[0]
            if not PLAIN_WORD.match(sub):
                continue
            if sub not in AD_SUBCOMMANDS:
                messages.append("line %d: `ad.py %s` is not a sub-command of lib/ad.py" % (number, sub))
                continue
            second_level = AD_SUBCOMMANDS[sub]
            if not second_level or len(words) < 2:
                continue
            second = words[1]
            if PLAIN_WORD.match(second) and second not in second_level:
                messages.append(
                    "line %d: `ad.py %s %s` is not a sub-command of lib/ad.py (expected one of: %s)"
                    % (number, sub, second, ", ".join(second_level))
                )
    return messages


def section_lines(body, heading):
    """Return the lines of the `## <heading>` section of a SKILL.md body."""
    lines = []
    inside = False
    for line in body.split("\n"):
        if line.startswith("## "):
            inside = line[3:].strip().lower().startswith(heading.lower())
            continue
        if inside:
            lines.append(line)
    return lines


def sibling_findings(body, own_name):
    """Return messages for sibling skill names that do not exist.

    Looks where the style guide puts sibling names: the lead term of each
    bullet under "Related skills", and "use <name>" at the end of a clause
    under "When not to use". A name from REMOVED_SKILLS is flagged anywhere.
    """
    messages = []
    candidates = []
    for line in section_lines(body, "Related skills"):
        match = RELATED_BULLET.match(line)
        if match:
            candidates.append(match.group(1))
    for line in section_lines(body, "When not to use"):
        for match in USE_SIBLING.finditer(line):
            candidates.append(match.group(1))
    for removed in REMOVED_SKILLS:
        if removed in body:
            candidates.append(removed)
    seen = []
    for candidate in candidates:
        if candidate in seen or candidate == own_name:
            continue
        seen.append(candidate)
        if not KEBAB_NAME.match(candidate):
            continue
        if candidate in ALL_SKILLS:
            continue
        messages.append("names the sibling skill %r, which does not exist" % candidate)
    return messages


def allowed_tools_findings(value):
    """Return messages for `allowed-tools` rules that pre-approve too much."""
    if isinstance(value, list):
        text = " ".join(str(item) for item in value)
    else:
        text = str(value)
    messages = []
    for match in ALLOWED_TOOLS_AD_RULE.finditer(text):
        rule = " ".join(match.group(1).split())
        if rule in PREAPPROVED_READ_ONLY_FORMS:
            continue
        if rule.split(" ")[0] in NEVER_PREAPPROVED_SUBCOMMANDS:
            messages.append("allowed-tools pre-approves `ad.py %s`, which must prompt the user" % rule)
    if BARE_PYTHON_RULE.search(text):
        messages.append("allowed-tools holds a bare python rule")
    outside_bash = re.sub(r"Bash\([^)]*\)", " ", text)
    for match in READ_TOOL_RULE.finditer(outside_bash):
        messages.append("allowed-tools pre-approves %s" % match.group(1))
    return messages


def check_skill_text(root, name):
    """Findings for one SKILL.md: frontmatter, size, command form, sibling names."""
    skill = load_skill(root, name)
    label = relative(root, skill["path"])
    if skill["text"] is None:
        return ["%s: %s" % (label, skill["error"])]
    findings = []
    line_count = len(skill["text"].replace("\r\n", "\n").rstrip("\n").split("\n"))
    if line_count > MAX_SKILL_MD_LINES:
        findings.append("%s: %d lines; the limit is %d" % (label, line_count, MAX_SKILL_MD_LINES))
    if "\r\n" in skill["text"]:
        findings.append("%s: CRLF line endings; use LF" % label)
    if skill["error"]:
        findings.append("%s: frontmatter: %s" % (label, skill["error"]))
        return findings
    frontmatter = skill["frontmatter"]
    for message in yaml_cross_check(skill["frontmatter_text"], frontmatter)[0]:
        findings.append("%s: %s" % (label, message))
    for key in frontmatter:
        if key not in REPO_FRONTMATTER_KEYS:
            findings.append(
                "%s: frontmatter key %r is not allowed (allowed: %s)" % (label, key, ", ".join(REPO_FRONTMATTER_KEYS))
            )
    declared = frontmatter.get("name")
    if declared != name:
        findings.append("%s: frontmatter name %r differs from the folder name %r" % (label, declared, name))
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        findings.append("%s: description missing" % label)
    else:
        if len(description) > MAX_DESCRIPTION_CHARS:
            findings.append(
                "%s: description has %d characters; the limit is %d" % (label, len(description), MAX_DESCRIPTION_CHARS)
            )
        if "<" in description or ">" in description:
            findings.append("%s: description contains an angle bracket" % label)
    if "allowed-tools" in frontmatter:
        for message in allowed_tools_findings(frontmatter["allowed-tools"]):
            findings.append("%s: %s" % (label, message))
    for number, line in unprefixed_script_commands(skill["body"]):
        findings.append(
            "%s:%d: command runs a script without the %s prefix: %s" % (label, number, SKILL_DIR_PLACEHOLDER, line)
        )
    for message in ad_example_findings(skill["text"]):
        findings.append("%s: %s" % (label, message))
    for message in sibling_findings(skill["body"], name):
        findings.append("%s: %s" % (label, message))
    return findings


def check_versions(root):
    """Findings when the plugin manifest, the library and the skills disagree on the version."""
    findings = []
    versions = {}
    manifest_path = os.path.join(root, ".claude-plugin", "plugin.json")
    if os.path.isfile(manifest_path):
        try:
            versions[".claude-plugin/plugin.json"] = json.loads(read_text(manifest_path)).get("version")
        except ValueError as error:
            findings.append(".claude-plugin/plugin.json: invalid JSON: %s" % error)
    core_path = os.path.join(lib_dir(root), "ad_core.py")
    if os.path.isfile(core_path):
        match = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', read_text(core_path), re.MULTILINE)
        if match:
            versions["lib/ad_core.py"] = match.group(1)
        else:
            findings.append("lib/ad_core.py: no VERSION constant found")
    for name in present_skills(root):
        skill = load_skill(root, name)
        if not isinstance(skill["frontmatter"], dict):
            continue
        metadata = skill["frontmatter"].get("metadata")
        if isinstance(metadata, dict) and "version" in metadata:
            versions[relative(root, skill["path"])] = metadata["version"]
    distinct = sorted(set(str(value) for value in versions.values()))
    if len(distinct) > 1:
        for source in sorted(versions):
            findings.append("%s: version %s (versions differ: %s)" % (source, versions[source], ", ".join(distinct)))
    return findings


def check_layout(root):
    """Findings for repository-level layout rules."""
    findings = []
    if os.path.exists(os.path.join(root, "bin")):
        findings.append("bin/: claude.ai rejects a plugin with a top-level bin/ directory")
    return findings


def check(root, include_dist=True):
    """Run every check. Return the list of findings (empty means clean)."""
    findings = []
    findings.extend(check_skill_set(root))
    findings.extend(check_copies(root))
    for name in present_skills(root):
        if name in ALL_SKILLS:
            findings.extend(check_skill_text(root, name))
    findings.extend(check_versions(root))
    findings.extend(check_layout(root))
    if include_dist:
        findings.extend(check_dist(root))
    return findings


# ---------------------------------------------------------------- validate

def counts_as_packaged_skill_md(relative_parts):
    """True when a SKILL.md at this relative path would be packaged (validator rule)."""
    directories = relative_parts[:-1]
    for part in directories:
        if part in VALIDATOR_EXCLUDED_DIRS:
            return False
    if directories and directories[0] in VALIDATOR_ROOT_EXCLUDED_DIRS:
        return False
    return True


def validate_skill(folder):
    """Re-implementation of the upload validator. Return (ok, message)."""
    skill_md = os.path.join(folder, "SKILL.md")
    if not os.path.isfile(skill_md):
        return False, "SKILL.md not found"
    found = []
    for current, _dirs, files in os.walk(folder):
        if "SKILL.md" in files:
            parts = tuple(os.path.relpath(os.path.join(current, "SKILL.md"), folder).split(os.sep))
            if counts_as_packaged_skill_md(parts):
                found.append("/".join(parts))
    if len(found) > 1:
        extras = sorted(item for item in found if item != "SKILL.md")
        return False, "found %d SKILL.md files; a skill must contain exactly one. Extra: %s" % (len(found), ", ".join(extras))
    try:
        frontmatter_text, _body = split_frontmatter(read_text(skill_md))
        frontmatter = parse_frontmatter(frontmatter_text)
    except FrontmatterError as error:
        return False, "frontmatter: %s" % error
    unexpected = sorted(key for key in frontmatter if key not in UPLOAD_FRONTMATTER_KEYS)
    if unexpected:
        return False, "unexpected key(s) in SKILL.md frontmatter: %s" % ", ".join(unexpected)
    if "name" not in frontmatter:
        return False, "missing 'name' in frontmatter"
    if "description" not in frontmatter:
        return False, "missing 'description' in frontmatter"
    name = frontmatter["name"]
    if not isinstance(name, str):
        return False, "name must be a string"
    name = name.strip()
    if name:
        if not re.match(r"^[a-z0-9-]+$", name):
            return False, "name %r must be kebab-case (lowercase letters, digits and hyphens only)" % name
        if name.startswith("-") or name.endswith("-") or "--" in name:
            return False, "name %r cannot start or end with a hyphen or contain consecutive hyphens" % name
        if len(name) > UPLOAD_MAX_NAME_CHARS:
            return False, "name has %d characters; the maximum is %d" % (len(name), UPLOAD_MAX_NAME_CHARS)
    description = frontmatter["description"]
    if not isinstance(description, str):
        return False, "description must be a string"
    description = description.strip()
    if "<" in description or ">" in description:
        return False, "description cannot contain angle brackets"
    if len(description) > UPLOAD_MAX_DESCRIPTION_CHARS:
        return False, "description has %d characters; the maximum is %d" % (len(description), UPLOAD_MAX_DESCRIPTION_CHARS)
    compatibility = frontmatter.get("compatibility", "")
    if compatibility:
        if not isinstance(compatibility, str):
            return False, "compatibility must be a string"
        if len(compatibility) > UPLOAD_MAX_COMPATIBILITY_CHARS:
            return False, "compatibility has %d characters; the maximum is %d" % (
                len(compatibility),
                UPLOAD_MAX_COMPATIBILITY_CHARS,
            )
    return True, "Skill is valid!"


def run_external_validator(validator_path, folder):
    """Run the real validator on one folder. Return (state, message).

    state is "ok", "fail", or "skipped" (the validator needs PyYAML and this
    interpreter does not have it).
    """
    completed = subprocess.run(
        [sys.executable, validator_path, folder],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode == 0:
        return "ok", output
    if "No module named 'yaml'" in output:
        return "skipped", "the validator needs PyYAML, which this interpreter lacks"
    last_line = output.split("\n")[-1] if output else "exit code %d" % completed.returncode
    return "fail", last_line


def validate(root, validator_path=None):
    """Validate every present skill. Return (findings, notices)."""
    findings = []
    notices = []
    try:
        import yaml  # noqa: F401  (availability probe only)
    except ImportError:
        notices.append("notice: PyYAML is not installed; the PyYAML cross-check is skipped")
    if validator_path and not os.path.isfile(validator_path):
        raise BuildError("validator not found: " + validator_path)
    for name in present_skills(root):
        folder = skill_dir(root, name)
        ok, message = validate_skill(folder)
        if not ok:
            findings.append(".claude/skills/%s: %s" % (name, message))
        skill = load_skill(root, name)
        if isinstance(skill["frontmatter"], dict):
            for cross in yaml_cross_check(skill["frontmatter_text"], skill["frontmatter"])[0]:
                findings.append(".claude/skills/%s: %s" % (name, cross))
        if validator_path:
            state, message = run_external_validator(validator_path, folder)
            if state == "fail":
                findings.append(".claude/skills/%s: external validator: %s" % (name, message))
            elif state == "skipped":
                skip_notice = "notice: external validator skipped: " + message
                if skip_notice not in notices:
                    notices.append(skip_notice)
    return findings, notices


# ---------------------------------------------------------------- zip

def is_excluded_from_zip(relative_parts):
    """True when a file at this path inside a skill folder stays out of the zip."""
    for part in relative_parts[:-1]:
        if part in ZIP_EXCLUDED_DIRS:
            return True
    file_name = relative_parts[-1]
    if file_name in ZIP_EXCLUDED_FILES:
        return True
    return file_name.endswith(ZIP_EXCLUDED_SUFFIXES)


def member_mode(arcname):
    """Return the file mode stored in the zip: 0755 for .py scripts, else 0644."""
    if arcname.endswith(".py"):
        return ZIP_MODE_SCRIPT
    return ZIP_MODE_FILE


def package_members(root, name):
    """Return the sorted list of (archive name, source path) for one skill.

    Every archive name starts with `<name>/`, so the zip has one top-level
    folder named after the skill, which is what the claude.ai upload expects.
    """
    folder = skill_dir(root, name)
    members = []
    for current, directories, files in os.walk(folder):
        directories.sort()
        for file_name in files:
            path = os.path.join(current, file_name)
            parts = tuple(os.path.relpath(path, folder).split(os.sep))
            if is_excluded_from_zip(parts):
                continue
            if os.path.islink(path):
                raise BuildError("symbolic link inside a skill folder: " + relative(root, path))
            members.append((name + "/" + "/".join(parts), path))
    members.sort()
    return members


def build_zip_bytes(root, name):
    """Return the bytes of the deterministic zip for one skill.

    Deterministic means: sorted members, the fixed timestamp 1980-01-01, fixed
    modes, no directory entries, one compression level. Two builds from the
    same files with the same zlib give the same bytes.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for arcname, path in package_members(root, name):
            info = zipfile.ZipInfo(arcname, ZIP_TIMESTAMP)
            info.create_system = ZIP_UNIX_SYSTEM
            info.external_attr = (ZIP_REGULAR_FILE_FLAG | member_mode(arcname)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, read_bytes(path), zipfile.ZIP_DEFLATED, ZIP_COMPRESS_LEVEL)
    return buffer.getvalue()


def zip_differences(root, name):
    """Compare dist/<name>.zip with the skill folder. Return a list of differences.

    The comparison uses member names, modes, timestamps and content hashes, not
    the compressed bytes, because deflate output can differ between zlib builds.
    """
    path = zip_path(root, name)
    label = relative(root, path)
    if not os.path.isfile(path):
        return ["%s: missing; run tools/build.py zip" % label]
    expected = {}
    for arcname, source in package_members(root, name):
        expected[arcname] = (sha256_bytes(read_bytes(source)), member_mode(arcname))
    differences = []
    try:
        with zipfile.ZipFile(path) as archive:
            actual = {}
            for info in archive.infolist():
                mode = (info.external_attr >> 16) & 0o777
                actual[info.filename] = (sha256_bytes(archive.read(info.filename)), mode)
                if info.date_time != ZIP_TIMESTAMP:
                    differences.append("%s: member %s has a timestamp that is not 1980-01-01" % (label, info.filename))
                top = info.filename.split("/", 1)[0]
                if top != name or info.filename.endswith("/"):
                    differences.append("%s: member %s is outside the single top-level folder %s/" % (label, info.filename, name))
            if archive.namelist() != sorted(archive.namelist()):
                differences.append("%s: members are not sorted" % label)
    except (zipfile.BadZipFile, OSError) as error:
        return ["%s: unreadable: %s" % (label, error)]
    for arcname in sorted(expected):
        if arcname not in actual:
            differences.append("%s: lacks %s; run tools/build.py zip" % (label, arcname))
        elif actual[arcname][0] != expected[arcname][0]:
            differences.append("%s: %s differs from the folder; run tools/build.py zip" % (label, arcname))
        elif actual[arcname][1] != expected[arcname][1]:
            differences.append("%s: %s has mode %o, expected %o" % (label, arcname, actual[arcname][1], expected[arcname][1]))
    for arcname in sorted(actual):
        if arcname not in expected:
            differences.append("%s: holds %s, which the folder lacks; run tools/build.py zip" % (label, arcname))
    return differences


def check_dist(root):
    """Findings for zips that are missing, stale, or that match no skill."""
    findings = []
    for name in present_skills(root):
        if name in ALL_SKILLS and os.path.isfile(os.path.join(skill_dir(root, name), "SKILL.md")):
            findings.extend(zip_differences(root, name))
    directory = dist_dir(root)
    if os.path.isdir(directory):
        for entry in sorted(os.listdir(directory)):
            stem, extension = os.path.splitext(entry)
            if extension != ".zip" or stem not in present_skills(root):
                findings.append("dist/%s: matches no skill folder" % entry)
    return findings


def write_zips(root, force=False):
    """Write dist/<name>.zip for every present skill. Return report lines.

    A zip whose content already equals the folder is left alone unless `force`
    is set, so a committed zip changes only when its skill changes.
    """
    report = []
    names = [name for name in present_skills(root) if os.path.isfile(os.path.join(skill_dir(root, name), "SKILL.md"))]
    if not names:
        raise BuildError("no skill folders found under .claude/skills/")
    os.makedirs(dist_dir(root), exist_ok=True)
    for name in names:
        if not force and not zip_differences(root, name):
            report.append("up to date dist/%s.zip" % name)
            continue
        data = build_zip_bytes(root, name)
        handle, temporary = tempfile.mkstemp(prefix=name + ".", suffix=".tmp", dir=dist_dir(root))
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.chmod(temporary, ZIP_MODE_FILE)
        os.replace(temporary, zip_path(root, name))
        report.append("wrote dist/%s.zip (%d bytes, sha256 %s)" % (name, len(data), sha256_bytes(data)[:12]))
    return report


# ---------------------------------------------------------------- command line

def print_findings(title, findings):
    """Print findings under a title. Return the exit code: 1 when there are findings."""
    if not findings:
        print("%s: clean" % title)
        return 0
    print("%s: %d problem(s)" % (title, len(findings)))
    for finding in findings:
        print("  " + finding)
    return 1


def command_sync(arguments):
    for line in sync(arguments.root):
        print(line)
    return 0


def command_check(arguments):
    return print_findings("check", check(arguments.root))


def command_validate(arguments):
    findings, notices = validate(arguments.root, arguments.validator)
    for notice in notices:
        print(notice)
    return print_findings("validate", findings)


def command_zip(arguments):
    for line in write_zips(arguments.root, arguments.force):
        print(line)
    return 0


def command_all(arguments):
    """sync, check, validate, zip. Stop before zip when a check fails."""
    for line in sync(arguments.root):
        print(line)
    # Zip freshness is checked after the zip step, which is what makes it fresh.
    status = print_findings("check", check(arguments.root, include_dist=False))
    findings, notices = validate(arguments.root, arguments.validator)
    for notice in notices:
        print(notice)
    status = max(status, print_findings("validate", findings))
    if status:
        print("zip: skipped because a check failed")
        return status
    for line in write_zips(arguments.root, arguments.force):
        print(line)
    return print_findings("dist", check_dist(arguments.root))


def build_parser():
    parser = argparse.ArgumentParser(
        prog="build.py",
        description="Sync lib/ into the scripted skills, check the skills, and build the upload zips.",
    )
    parser.add_argument("--root", default=default_root(), help="repository root (default: the parent of tools/)")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("sync", help="copy lib/*.py into scripts/ of each scripted skill").set_defaults(run=command_sync)
    commands.add_parser("check", help="exit 1 and list every packaging defect").set_defaults(run=command_check)
    validate_parser = commands.add_parser("validate", help="run the upload validator's checks")
    validate_parser.add_argument("--validator", help="path of the real quick_validate.py to run as well")
    validate_parser.set_defaults(run=command_validate)
    zip_parser = commands.add_parser("zip", help="write dist/<name>.zip for every skill")
    zip_parser.add_argument("--force", action="store_true", help="rewrite zips that are already up to date")
    zip_parser.set_defaults(run=command_zip)
    all_parser = commands.add_parser("all", help="sync, check, validate, zip")
    all_parser.add_argument("--validator", help="path of the real quick_validate.py to run as well")
    all_parser.add_argument("--force", action="store_true", help="rewrite zips that are already up to date")
    all_parser.set_defaults(run=command_all)
    return parser


def main(argv=None):
    """Entry point. Exit codes: 0 clean, 1 findings, 2 usage or build error."""
    sys.dont_write_bytecode = True
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if not getattr(arguments, "run", None):
        parser.print_usage(sys.stderr)
        return 2
    arguments.root = os.path.abspath(arguments.root)
    try:
        return arguments.run(arguments)
    except (BuildError, OSError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
