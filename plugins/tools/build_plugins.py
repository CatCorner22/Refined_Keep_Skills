#!/usr/bin/env python3
"""Build the Claude Code plugins under plugins/. Standard library only.

    python3 plugins/tools/build_plugins.py generate [--source DIR]
        Rebuild the skills of the `coding` and `plain-language` plugins from a checkout of
        CatCorner22/Cursor_Skills. The checkout must be at SOURCE_COMMIT, and its skills/coding/
        and skills/legal/ folders must hold no uncommitted change and no untracked file.
    python3 plugins/tools/build_plugins.py zip
        Write plugins/dist/<plugin>-plugin.zip for each plugin.
    python3 plugins/tools/build_plugins.py check
        Exit 1 when a zip differs from its plugin folder.

Why a build: the master copies of these skills are written for Cursor. Each one carries
`disable-model-invocation: true`, which stops Claude Code from loading the skill on its own.
The 7 coding skills also carry routing keys that Claude Code ignores. The build changes only
what this file lists:

  1. Frontmatter: keep `name` and `description` as written; drop every other key; add a
     `metadata` block with the plugin version and the source path and commit.
  2. Body: apply the replacements in PATCHES, and append the text in FOOTERS. Each replaced
     text must occur exactly once in the source, so a changed source stops the build.
  3. Files: copy `scripts/` and `references/`. Nothing else is copied (no `evals/`).

The `red-team` plugin is not generated. Its one skill is a copy of the skill that the owner's
claude.ai account held on 2026-11-17; no repository held it before.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile

sys.dont_write_bytecode = True
PLUGINS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(PLUGINS)
DIST = os.path.join(PLUGINS, "dist")

SOURCE_REPO = "CatCorner22/Cursor_Skills"
SOURCE_COMMIT = "5cf51062d75d7f70e9f29c53cba0e5d41b16d8a4"
_PARENT = os.path.dirname(REPO)
_CANDIDATES = [os.path.join(_PARENT, "Cursor_Skills"), os.path.join(_PARENT, "cursor_skills"),
               os.path.join(_PARENT, "catcorner22", "cursor_skills")]
DEFAULT_SOURCE = next((path for path in _CANDIDATES if os.path.isdir(path)), _CANDIDATES[0])

ALL_PLUGINS = ("coding", "plain-language", "red-team")
GENERATED = {
    "coding": {
        "pack": "coding",
        "version": "2.0.0",
        "skills": ("clean-minimal-code", "coding-ecosystem-primer", "deliverable-first", "real-time-testing",
                   "stable-architecture", "ui-engineering", "ux-engineering"),
    },
    "plain-language": {
        "pack": "legal",
        "version": "1.0.0",
        "skills": ("one-way-optimal-language", "unambiguous-language"),
    },
}
KEPT_KEYS = ("name", "description")
DROPPED_KEYS = ("disable-model-invocation", "metadata")
COPIED_DIRS = ("scripts", "references")
SKIPPED_NAMES = ("__pycache__", ".DS_Store")

CODING_FOOTER = (
    "\n## In Claude Code\n\n"
    "This skill is part of the `coding` plugin. Load a skill that this text names with the Skill tool: "
    "`coding:<name>` for a skill of this plugin, or the name that the session lists for a skill of another "
    "pack. If the session does not list a named skill, continue without it.\n"
)
FOOTERS = {
    "clean-minimal-code": CODING_FOOTER,
    "deliverable-first": CODING_FOOTER,
    "real-time-testing": CODING_FOOTER,
    "stable-architecture": CODING_FOOTER,
    "ui-engineering": CODING_FOOTER,
    "ux-engineering": CODING_FOOTER,
    "one-way-optimal-language": (
        "\n## Files in this skill\n\n"
        "| File | Use |\n|---|---|\n"
        "| `scripts/active_voice_check.py` | The full checker of the Verification section |\n"
        "| `references/one-way-optimal-language-guide.md` | The full style manual on the same subject, "
        "version 1.0 (9 November 2026); read it when a rule here needs more detail |\n"
        "| `references/evidence-one-way-medical-text.md` | A review of the research evidence for this skill's "
        "rules |\n"
        "| `references/patient-facing-comprehension-research-2026.md` | A research synthesis on how readers "
        "comprehend, retain and interpret one-way medical text |\n"
        "| `references/mscd-5th-edition-notes.md` | Notes on MSCD, 5th edition |\n"
    ),
}
# skill -> [(text in the source, replacement)]. Each source text must occur exactly once.
PATCHES = {
    "coding-ecosystem-primer": [(
        "Pick the **smallest set of skills** that covers the task. This pack is **stack-agnostic** — it governs "
        "*how* to code, not which vendor framework to use.",
        "Pick the **smallest set of skills** that covers the task. This pack is **stack-agnostic** — it governs "
        "*how* to code, not which vendor framework to use.\n\n"
        "**In Claude Code.** Load a skill of this plugin with the Skill tool, by its name (for example "
        "`coding:deliverable-first`). The 7 skills of this plugin are `coding-ecosystem-primer`, "
        "`deliverable-first`, `stable-architecture`, `real-time-testing`, `clean-minimal-code`, `ui-engineering` "
        "and `ux-engineering`. Every other skill that the tables below name belongs to another pack. "
        "`verified-build-loop` is its own plugin in the same marketplace "
        "(`verified-build-loop:verified-build-loop`). Load a skill of another pack only if the session lists it; "
        "if the session does not list it, continue without it.",
    )],
    "real-time-testing": [(
        "Keep a watcher running in a **tmux** terminal while editing:",
        "Keep a watcher running while editing. In Claude Code, start the watcher with the Bash tool's "
        "`run_in_background` option; a watch command never exits, so never run one in the foreground. If you "
        "cannot read the output of a background command, run the related test file once after each edit. "
        "In another environment, use a **tmux** terminal:",
    )],
    "unambiguous-language": [(
        "3. Add the same entry to Blake's memory preferences.",
        "3. Add the same entry to Blake's memory preferences, if this session has a memory tool. If it does not, "
        "tell Blake that this step is open.",
    ), (
        "5. Commit the same change to skills/legal/unambiguous-language/SKILL.md in the catcorner22/cursor_skills "
        "repo.",
        "5. Commit the same change to skills/legal/unambiguous-language/SKILL.md in the catcorner22/cursor_skills "
        "repo, which holds the master copy of this skill. If this session cannot write to that repo, tell Blake "
        "that this step is open.",
    )],
    "one-way-optimal-language": [(
        "1. **Full checker.** If `active_voice_check.py` exists (in this skill's `scripts/` folder, the workspace, "
        "or the user's skill repository), run `python3 active_voice_check.py FILE`.",
        "1. **Full checker.** This skill ships the checker. Run "
        "`python3 \"${CLAUDE_SKILL_DIR}/scripts/active_voice_check.py\" FILE`.",
    )],
}


class BuildError(Exception):
    """A problem that stops the build; the message says what to fix."""


def read_text(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


# ---------------------------------------------------------------- generate

def split_frontmatter(text, label):
    """Return (list of (key, [lines]) blocks, body) for a SKILL.md with LF line endings."""
    if "\r" in text:
        raise BuildError("%s: CRLF line endings; expected LF" % label)
    if not text.startswith("---\n"):
        raise BuildError("%s: no frontmatter" % label)
    end = text.find("\n---\n", 4)
    if end < 0:
        raise BuildError("%s: the frontmatter has no closing line" % label)
    blocks = []
    for line in text[4:end].split("\n"):
        if line and not line[0].isspace() and ":" in line:
            blocks.append((line.split(":", 1)[0], [line]))
        elif blocks:
            blocks[-1][1].append(line)
        else:
            raise BuildError("%s: the frontmatter does not start with a key" % label)
    return blocks, text[end + 5:]


def convert_skill(text, skill, plugin, label):
    """Return the Claude Code form of one source SKILL.md."""
    spec = GENERATED[plugin]
    blocks, body = split_frontmatter(text, label)
    kept = []
    for key, lines in blocks:
        if key in KEPT_KEYS:
            if len(lines) != 1:
                raise BuildError("%s: the key %r spans %d lines; the build expects 1" % (label, key, len(lines)))
            kept.append(lines[0])
        elif key not in DROPPED_KEYS:
            raise BuildError("%s: unexpected frontmatter key %r; decide whether the build keeps or drops it"
                             % (label, key))
    if [line.split(":", 1)[0] for line in kept] != list(KEPT_KEYS):
        raise BuildError("%s: the frontmatter must hold name, then description" % label)
    if kept[0].split(":", 1)[1].strip().strip('"') != skill:
        raise BuildError("%s: the name in the frontmatter differs from the folder name" % label)
    for old, new in PATCHES.get(skill, []):
        if body.count(old) != 1:
            raise BuildError("%s: the text to replace occurs %d times, not 1: %r" % (label, body.count(old), old[:70]))
        body = body.replace(old, new)
    if skill in FOOTERS:
        body = body.rstrip("\n") + "\n" + FOOTERS[skill]
    metadata = ('metadata:\n  version: "%s"\n  source: "%s@%s skills/%s/%s"'
                % (spec["version"], SOURCE_REPO, SOURCE_COMMIT[:7], spec["pack"], skill))
    return "---\n" + "\n".join(kept) + "\n" + metadata + "\n---\n" + body


def source_state(source):
    """Return (commit, changed) for a source checkout.

    ``commit`` is the full hash of HEAD, or None when git cannot read the folder. ``changed`` lists
    the paths under the source packs that differ from that commit: edited, deleted or untracked
    files. The build stamps each skill with the commit, so it must read exactly that commit."""
    def git(*args):
        try:
            result = subprocess.run(["git", "-C", source] + list(args), stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, universal_newlines=True)
        except OSError:
            return None
        return result.stdout if result.returncode == 0 else None
    top = git("rev-parse", "--show-toplevel")
    head = git("rev-parse", "HEAD")
    if top is None or head is None or os.path.realpath(top.strip()) != os.path.realpath(source):
        return None, []
    packs = sorted({"skills/" + spec["pack"] for spec in GENERATED.values()})
    status = git("status", "--porcelain", "--untracked-files=all", "--", *packs)
    changed = [line[3:].strip().strip('"') for line in (status or "").splitlines() if line.strip()]
    return head.strip(), changed


def generate(source, out_root):
    """Write <out_root>/<plugin>/skills/<skill>/ for every generated skill. Return report lines."""
    report = []
    for plugin, spec in sorted(GENERATED.items()):
        for skill in spec["skills"]:
            origin = os.path.join(source, "skills", spec["pack"], skill)
            label = "skills/%s/%s/SKILL.md" % (spec["pack"], skill)
            if not os.path.isfile(os.path.join(origin, "SKILL.md")):
                raise BuildError("%s: not found under %s" % (label, source))
            converted = convert_skill(read_text(os.path.join(origin, "SKILL.md")), skill, plugin, label)
            target = os.path.join(out_root, plugin, "skills", skill)
            if os.path.isdir(target):
                shutil.rmtree(target)
            write_text(os.path.join(target, "SKILL.md"), converted)
            copied = 0
            for folder in COPIED_DIRS:
                for current, dirs, files in os.walk(os.path.join(origin, folder)):
                    dirs[:] = sorted(d for d in dirs if d not in SKIPPED_NAMES)
                    for name in sorted(files):
                        if name in SKIPPED_NAMES or name.endswith(".pyc"):
                            continue
                        relative = os.path.relpath(os.path.join(current, name), origin)
                        os.makedirs(os.path.dirname(os.path.join(target, relative)), exist_ok=True)
                        shutil.copyfile(os.path.join(current, name), os.path.join(target, relative))
                        copied += 1
            report.append("generated %s/skills/%s (SKILL.md and %d other files)" % (plugin, skill, copied))
    return report


# ---------------------------------------------------------------- zip

def members(plugin):
    """Return [(name in the zip, absolute path, mode)] for every file of one plugin, sorted."""
    root = os.path.join(PLUGINS, plugin)
    found = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIPPED_NAMES)
        for name in sorted(files):
            if name in SKIPPED_NAMES or name.endswith(".pyc"):
                continue
            path = os.path.join(current, name)
            if os.path.islink(path):
                raise BuildError("%s is a symbolic link; a plugin folder must hold regular files only" % path)
            relative = os.path.relpath(path, PLUGINS).replace(os.sep, "/")
            found.append((relative, path, 0o755 if name.endswith((".py", ".sh")) else 0o644))
    return sorted(found)


def zip_path(plugin):
    return os.path.join(DIST, plugin + "-plugin.zip")


def write_zips():
    os.makedirs(DIST, exist_ok=True)
    report = []
    for plugin in ALL_PLUGINS:
        with zipfile.ZipFile(zip_path(plugin), "w", zipfile.ZIP_DEFLATED) as archive:
            for relative, path, mode in members(plugin):
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100000 | mode) << 16
                with open(path, "rb") as handle:
                    archive.writestr(info, handle.read())
        report.append("wrote dist/%s-plugin.zip (%d files)" % (plugin, len(members(plugin))))
    return report


def check_zips():
    """Return the differences between each zip and its plugin folder."""
    findings = []
    for plugin in ALL_PLUGINS:
        if not os.path.isfile(zip_path(plugin)):
            findings.append("dist/%s-plugin.zip is missing; run: build_plugins.py zip" % plugin)
            continue
        expected = {}
        for relative, path, mode in members(plugin):
            with open(path, "rb") as handle:
                expected[relative] = (hashlib.sha256(handle.read()).hexdigest(), mode)
        actual = {}
        with zipfile.ZipFile(zip_path(plugin)) as archive:
            for info in archive.infolist():
                actual[info.filename] = (hashlib.sha256(archive.read(info)).hexdigest(),
                                         (info.external_attr >> 16) & 0o777)
        for name in sorted(set(expected) | set(actual)):
            if name not in actual:
                findings.append("dist/%s-plugin.zip lacks %s" % (plugin, name))
            elif name not in expected:
                findings.append("dist/%s-plugin.zip holds %s, which the folder lacks" % (plugin, name))
            elif expected[name] != actual[name]:
                findings.append("dist/%s-plugin.zip holds a different %s" % (plugin, name))
    return findings


# ---------------------------------------------------------------- command line

def main(argv):
    args = argv[1:]
    try:
        if args and args[0] == "generate":
            source = DEFAULT_SOURCE
            if len(args) == 3 and args[1] == "--source":
                source = args[2]
            elif len(args) != 1:
                print(__doc__)
                return 2
            commit, changed = source_state(source)
            if commit != SOURCE_COMMIT:
                raise BuildError("the checkout at %s is at commit %s; this build is pinned to %s. Check out that "
                                 "commit, or review the changes in the source and update SOURCE_COMMIT, PATCHES "
                                 "and FOOTERS." % (source, (commit or "unknown")[:7], SOURCE_COMMIT[:7]))
            if changed:
                raise BuildError("the checkout at %s holds changes that commit %s does not: %s. Commit them "
                                 "there and update SOURCE_COMMIT, or remove them."
                                 % (source, SOURCE_COMMIT[:7], ", ".join(changed[:5])))
            for line in generate(source, PLUGINS):
                print(line)
            return 0
        if args == ["zip"]:
            for line in write_zips():
                print(line)
            return 0
        if args == ["check"]:
            findings = check_zips()
            for finding in findings:
                print(finding)
            print("check: %d findings" % len(findings))
            return 1 if findings else 0
    except BuildError as error:
        print("build stopped: %s" % error)
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
