#!/usr/bin/env python3
"""Validate the chicken-little-overwatch plugin.

Checks the manifest, every front matter block, the skill's upload limits, the
agents' tool lists, the links between files, the byte-for-byte reference
files, the rules that the agents repeat, and the 2 scanners.

Usage:  python3 tools/validate_package.py
Exit:   0 when every check passes, otherwise 1.

Standard library only. PyYAML is optional: when it imports, each front matter
block must also parse with it. Runs on Python 3.8 or later.
"""
import hashlib
import json
import os
import re
import sys

NAME = "chicken-little-overwatch"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", NAME)

SKILL_KEYS = ("name", "description", "compatibility", "metadata", "allowed-tools", "license")
AGENT_KEYS = ("name", "description", "tools", "model", "effort", "maxTurns", "color")
COMMAND_KEYS = ("description", "argument-hint")
READ_ONLY_TOOLS = ("Read", "Grep", "Glob", "Bash", "WebFetch", "WebSearch")
AGENT_NAMES = ("rt-arbiter", "rt-break-it-tester", "rt-defender", "rt-fact-auditor",
               "rt-future-analyst", "rt-gap-analyst", "rt-proofreader", "rt-style-prosecutor")
VERBATIM = {
    "references/one-way-optimal-language.md": "597633f2b15a0e605abbc7c4148049a09ae2873620c7ce004f281569462f29bf",
    "references/original-plugin.json": "b883be5b6c75dbfea4e93dc4e8a4d183905fd252cb3f009fae4227542895832f",
}
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
MAX_SKILL_LINES = 500
OLD_NAMES = ("llm-qc-suite", "llm-quality-control")
OLD_NAMES_ALLOWED_IN = ("CHANGELOG.md", "README.md")
SHARED_START = "# --- shared reader"
SHARED_END = "# --- end of shared reader ---"


class FrontMatterError(Exception):
    """A front matter block is missing or is not valid."""


def read_text(path):
    with open(path, "rb") as handle:
        return handle.read().decode("utf-8")


def parse_scalar(raw, line_number):
    raw = raw.strip()
    if raw.startswith('"'):
        if len(raw) < 2 or not raw.endswith('"') or '"' in raw[1:-1].replace('\\"', ""):
            raise FrontMatterError("line %d: a double-quoted value must end with one closing quote" % line_number)
        return raw[1:-1].replace('\\"', '"')
    if raw.startswith("'"):
        raise FrontMatterError("line %d: use double quotes" % line_number)
    if not raw:
        raise FrontMatterError("line %d: the value is empty" % line_number)
    if raw[0] in "[{&*!|>%@`#" or ": " in raw or " #" in raw or raw.endswith(":"):
        raise FrontMatterError("line %d: put this value in double quotes; plain YAML reads it another way" % line_number)
    return raw


def parse_front_matter(text):
    """Parse the small YAML subset that this package uses. Return (mapping, body)."""
    if not text.startswith("---\n"):
        raise FrontMatterError("the file does not start with a '---' line")
    end = text.find("\n---\n", 3)
    if end < 0:
        raise FrontMatterError("the front matter has no closing '---' line")
    block, body = text[4:end], text[end + 5:]
    result, parent = {}, None
    for number, line in enumerate(block.split("\n"), 2):
        if not line.strip():
            continue
        match = re.match(r"^( *)([A-Za-z][A-Za-z0-9_-]*):(.*)$", line)
        if not match:
            raise FrontMatterError("line %d: expected 'key: value'" % number)
        indent, key, raw = match.groups()
        if indent:
            if len(indent) != 2 or parent is None:
                raise FrontMatterError("line %d: unexpected indentation" % number)
            result[parent][key] = parse_scalar(raw, number)
            continue
        if key in result:
            raise FrontMatterError("line %d: the key '%s' appears twice" % (number, key))
        if raw.strip():
            result[key], parent = parse_scalar(raw, number), None
        else:
            result[key], parent = {}, key
    try:
        import yaml
    except ImportError:
        return result, body
    try:
        loaded = yaml.safe_load(block)
    except yaml.YAMLError as error:
        raise FrontMatterError("PyYAML rejects the front matter: %s" % " ".join(str(error).split()))
    if loaded != result:
        raise FrontMatterError("PyYAML reads the front matter differently from this validator")
    return result, body


def run_checks():
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    def load(relative, allowed_keys):
        path = os.path.join(ROOT, relative)
        try:
            text = read_text(path)
        except (OSError, UnicodeDecodeError) as error:
            errors.append("%s: cannot read as UTF-8: %s" % (relative, error))
            return None, ""
        check("\r" not in text, "%s: CR line endings; use LF" % relative)
        try:
            data, body = parse_front_matter(text)
        except FrontMatterError as error:
            errors.append("%s: front matter: %s" % (relative, error))
            return None, text
        for key in data:
            check(key in allowed_keys, "%s: front matter key '%s' is not allowed" % (relative, key))
        return data, body

    # Layout.
    for relative in (".claude-plugin/plugin.json", "README.md", "CHANGELOG.md", "skills/%s/SKILL.md" % NAME):
        check(os.path.isfile(os.path.join(ROOT, relative)), "%s: missing" % relative)
    check(not os.path.exists(os.path.join(ROOT, "bin")), "bin/: claude.ai does not install a plugin with a top-level bin/")
    check(not os.path.exists(os.path.join(ROOT, "CLAUDE.md")), "CLAUDE.md: Claude Code does not load a CLAUDE.md at a plugin root")
    for current, directories, files in os.walk(ROOT):
        directories[:] = [d for d in directories if d != "__pycache__"]
        for entry in directories + files:
            path = os.path.join(current, entry)
            check(not os.path.islink(path), "%s: symbolic link" % os.path.relpath(path, ROOT))

    # Manifest.
    version = None
    try:
        manifest = json.loads(read_text(os.path.join(ROOT, ".claude-plugin", "plugin.json")))
    except (OSError, ValueError) as error:
        manifest = {}
        errors.append("plugin.json: %s" % error)
    for key in ("name", "version", "description", "author"):
        check(key in manifest, "plugin.json: lacks '%s'" % key)
    check(manifest.get("name") == NAME, "plugin.json: name must be '%s'" % NAME)
    check(isinstance(manifest.get("author", {}), dict) and manifest.get("author", {}).get("name"),
          "plugin.json: author needs a name")
    version = manifest.get("version")
    check(isinstance(version, str) and re.match(r"^\d+\.\d+\.\d+$", version or ""), "plugin.json: version must be N.N.N")
    for key in manifest:
        check(key in ("name", "version", "description", "author", "keywords", "homepage", "repository", "license"),
              "plugin.json: unexpected key '%s'" % key)

    # Skill.
    skill_relative = "skills/%s/SKILL.md" % NAME
    meta, body = load(skill_relative, SKILL_KEYS)
    skill_text = ""
    if meta is not None:
        skill_text = read_text(os.path.join(ROOT, skill_relative))
        name = meta.get("name", "")
        check(name == NAME, "SKILL.md: name must equal the folder name '%s'" % NAME)
        check(bool(re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", str(name))) and len(str(name)) <= MAX_NAME,
              "SKILL.md: name must be kebab-case, at most %d characters" % MAX_NAME)
        description = meta.get("description", "")
        check(isinstance(description, str) and description.strip(), "SKILL.md: description missing")
        check(len(str(description)) <= MAX_DESCRIPTION,
              "SKILL.md: description has %d characters; the limit is %d" % (len(str(description)), MAX_DESCRIPTION))
        check("<" not in str(description) and ">" not in str(description), "SKILL.md: description holds an angle bracket")
        check(len(str(meta.get("compatibility", ""))) <= MAX_COMPATIBILITY,
              "SKILL.md: compatibility exceeds %d characters" % MAX_COMPATIBILITY)
        check(isinstance(meta.get("metadata"), dict) and meta["metadata"].get("version") == version,
              "SKILL.md: metadata.version must equal the plugin.json version %r" % version)
        line_count = len(skill_text.rstrip("\n").split("\n"))
        check(line_count <= MAX_SKILL_LINES, "SKILL.md: %d lines; the limit is %d" % (line_count, MAX_SKILL_LINES))
        for reference in sorted(set(re.findall(r"`((?:references|scripts)/[^`\s]+)`", skill_text))):
            check(os.path.isfile(os.path.join(SKILL, reference)), "SKILL.md: links to missing %s" % reference)
        for line in body.split("\n"):
            if re.match(r"\s*python3? ", line):
                check('python3 "${CLAUDE_SKILL_DIR}/scripts/' in line,
                      "SKILL.md: a command runs a script without the ${CLAUDE_SKILL_DIR} prefix: %s" % line.strip())
    extra = [os.path.relpath(os.path.join(current, f), SKILL) for current, _d, files in os.walk(SKILL)
             for f in files if f == "SKILL.md" and current != SKILL]
    check(not extra, "skill folder holds more than one SKILL.md: %s" % ", ".join(extra))

    # Changelog.
    try:
        changelog = read_text(os.path.join(ROOT, "CHANGELOG.md"))
        first = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M)
        check(first is not None and first.group(1) == version,
              "CHANGELOG.md: the newest entry must be version %r" % version)
    except OSError:
        pass

    # Byte-for-byte reference files.
    for relative, digest in sorted(VERBATIM.items()):
        path = os.path.join(SKILL, relative)
        if not os.path.isfile(path):
            errors.append("%s: missing" % relative)
            continue
        with open(path, "rb") as handle:
            check(hashlib.sha256(handle.read()).hexdigest() == digest,
                  "%s: the content changed; this file must stay byte for byte" % relative)
    try:
        json.loads(read_text(os.path.join(SKILL, "references", "original-plugin.json")))
    except (OSError, ValueError) as error:
        errors.append("references/original-plugin.json: %s" % error)

    # Swarm file.
    swarm_path = os.path.join(SKILL, "references", "red-team-swarm.md")
    swarm = read_text(swarm_path) if os.path.isfile(swarm_path) else ""
    check(bool(swarm), "references/red-team-swarm.md: missing")
    for prefix, count in (("D", 15), ("L", 14), ("RT", 12)):
        for number in range(1, count + 1):
            check(len(re.findall(r"^- \*\*%s%d " % (prefix, number), swarm, re.M)) == 1,
                  "red-team-swarm.md: rule %s%d must appear exactly once" % (prefix, number))
    for agent in sorted(set(re.findall(r"`(rt-[a-z-]+)`", swarm))):
        check(agent in AGENT_NAMES, "red-team-swarm.md: names unknown agent %s" % agent)
    reference = read_text(os.path.join(SKILL, "references", "one-way-optimal-language.md")) \
        if os.path.isfile(os.path.join(SKILL, "references", "one-way-optimal-language.md")) else ""
    for number in range(1, 9):
        check("**H%d " % number in reference, "one-way-optimal-language.md: Hard Rule H%d missing" % number)

    # Agents.
    agents_dir = os.path.join(ROOT, "agents")
    present = sorted(f[:-3] for f in os.listdir(agents_dir) if f.endswith(".md")) if os.path.isdir(agents_dir) else []
    check(tuple(present) == AGENT_NAMES, "agents/: expected exactly %s; found %s" % (", ".join(AGENT_NAMES), ", ".join(present)))
    severity = re.search(r"^## Severity scale\n(.*?)(?=^## )", swarm, re.M | re.S)
    finding = re.search(r"^## Finding format\n(.*?)(?=^## )", swarm, re.M | re.S)
    lens = re.findall(r"^- \*\*L\d+ .*$", swarm, re.M)
    defender = re.findall(r"^- \*\*D\d+ .*$", swarm, re.M)
    for stem in present:
        relative = "agents/%s.md" % stem
        data, agent_body = load(relative, AGENT_KEYS)
        if data is None:
            continue
        check(data.get("name") == stem, "%s: name differs from the file name" % relative)
        check(bool(str(data.get("description", "")).strip()), "%s: description missing" % relative)
        tools = [tool.strip() for tool in str(data.get("tools", "")).split(",") if tool.strip()]
        check(bool(tools), "%s: tools missing; an agent without a tools list inherits every tool" % relative)
        for tool in tools:
            check(tool in READ_ONLY_TOOLS, "%s: tool '%s' is not on the read-only list" % (relative, tool))
        for block, label in ((severity, "severity scale"), (finding, "finding format")):
            check(block is not None and block.group(1).strip("\n") in agent_body,
                  "%s: the %s differs from red-team-swarm.md; run tools/build.py agents" % (relative, label))
        if stem in ("rt-future-analyst", "rt-gap-analyst"):
            check(all(line in agent_body for line in lens), "%s: a lens differs from red-team-swarm.md" % relative)
        if stem in ("rt-defender", "rt-arbiter"):
            check(all(line in agent_body for line in defender), "%s: a Defender rule differs from red-team-swarm.md" % relative)
        for path in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\s`\"]+)", agent_body):
            check(os.path.isfile(os.path.join(ROOT, path)), "%s: points to missing %s" % (relative, path))

    # Commands.
    commands_dir = os.path.join(ROOT, "commands")
    commands = sorted(f for f in os.listdir(commands_dir) if f.endswith(".md")) if os.path.isdir(commands_dir) else []
    check(commands == ["qc-review.md", "red-team.md"], "commands/: expected qc-review.md and red-team.md")
    for file_name in commands:
        relative = "commands/%s" % file_name
        data, command_body = load(relative, COMMAND_KEYS)
        if data is None:
            continue
        check(bool(str(data.get("description", "")).strip()), "%s: description missing" % relative)
        check("$ARGUMENTS" in command_body, "%s: the body never uses $ARGUMENTS" % relative)
        for agent in sorted(set(re.findall(r"%s:(rt-[a-z-]+)" % NAME, command_body))):
            check(agent in AGENT_NAMES, "%s: names unknown agent %s" % (relative, agent))
        for path in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\s`\"]+)", command_body):
            check(os.path.exists(os.path.join(ROOT, path)), "%s: points to missing %s" % (relative, path))

    # Scanners.
    blocks = {}
    for script in ("av_scan.py", "watchlist_scan.py"):
        path = os.path.join(SKILL, "scripts", script)
        if not os.path.isfile(path):
            errors.append("scripts/%s: missing" % script)
            continue
        source = read_text(path)
        try:
            compile(source, path, "exec")
        except SyntaxError as error:
            errors.append("scripts/%s: %s" % (script, error))
        if SHARED_START in source and SHARED_END in source:
            blocks[script] = source[source.index(SHARED_START):source.index(SHARED_END)]
        else:
            errors.append("scripts/%s: the shared reader block is missing" % script)
    check(len(set(blocks.values())) <= 1, "scripts/: the shared reader block differs between the 2 scanners")
    fallback = re.search(r"^P = \(r.*?^\]$", reference, re.M | re.S)
    av_path = os.path.join(SKILL, "scripts", "av_scan.py")
    check(fallback is not None and os.path.isfile(av_path) and fallback.group(0) in read_text(av_path),
          "scripts/av_scan.py: the pattern set differs from the fallback scan in one-way-optimal-language.md")

    # Old names.
    for current, directories, files in os.walk(ROOT):
        directories[:] = [d for d in directories if d != "__pycache__"]
        for file_name in files:
            path = os.path.join(current, file_name)
            relative = os.path.relpath(path, ROOT).replace(os.sep, "/")
            if relative in OLD_NAMES_ALLOWED_IN or relative.endswith(tuple(VERBATIM)) or relative == "tools/validate_package.py":
                continue
            try:
                text = read_text(path)
            except UnicodeDecodeError:
                errors.append("%s: not UTF-8" % relative)
                continue
            for old in OLD_NAMES:
                check(old not in text, "%s: still names '%s'" % (relative, old))
    return errors


def main():
    errors = run_checks()
    if errors:
        print("FAIL")
        for error in errors:
            print(" - " + error)
        return 1
    print("OK: package checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
