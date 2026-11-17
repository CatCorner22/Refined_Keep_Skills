#!/usr/bin/env python3
"""Build and check the claude.ai upload package of the verified-build-loop skill. Standard library only.

The skill folder is plugin/skills/verified-build-loop/. The zip holds that folder under the name
verified-build-loop/.

    python3 verified-build-loop/tools/build.py zip     write the 2 zips under dist/
    python3 verified-build-loop/tools/build.py check   exit 1 when a zip differs from its folder

The 2 zips:
    dist/verified-build-loop.zip          the skill alone: 1 top folder with SKILL.md in it
    dist/verified-build-loop-plugin.zip   the plugin: 1 top folder with .claude-plugin/plugin.json in it

The zip is deterministic: sorted members, the fixed timestamp 1980-01-01, mode 0644 (0755 for
.py and .sh files), and no __pycache__, *.pyc or .DS_Store content.
"""
import hashlib
import os
import sys
import zipfile

sys.dont_write_bytecode = True
PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "verified-build-loop"
SKILLS = os.path.join(PACKAGE, "plugin", "skills")
SKILL = os.path.join(SKILLS, NAME)
PLUGIN = os.path.join(PACKAGE, "plugin")
ZIP_PATH = os.path.join(PACKAGE, "dist", NAME + ".zip")
PLUGIN_ZIP_PATH = os.path.join(PACKAGE, "dist", NAME + "-plugin.zip")
SKIP_DIRS = {"__pycache__"}
SKIP_FILES = {".DS_Store"}


def members(plugin=False):
    """Return [(name in the zip, absolute path, mode)] for every file of the skill folder, sorted.

    With ``plugin`` set, return every file of the plugin folder, under the top folder ``verified-build-loop/``."""
    found = []
    for current, dirs, files in os.walk(PLUGIN if plugin else SKILL):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name in SKIP_FILES or name.endswith(".pyc"):
                continue
            path = os.path.join(current, name)
            if plugin:
                relative = NAME + "/" + os.path.relpath(path, PLUGIN).replace(os.sep, "/")
            else:
                relative = os.path.relpath(path, SKILLS).replace(os.sep, "/")
            mode = 0o755 if name.endswith((".py", ".sh")) else 0o644
            found.append((relative, path, mode))
    return sorted(found)


def write_zip():
    os.makedirs(os.path.dirname(ZIP_PATH), exist_ok=True)
    for target, plugin in ((ZIP_PATH, False), (PLUGIN_ZIP_PATH, True)):
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for relative, path, mode in members(plugin):
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100000 | mode) << 16
                with open(path, "rb") as handle:
                    archive.writestr(info, handle.read())
        print("wrote %s (%d files)" % (os.path.relpath(target, PACKAGE), len(members(plugin))))
    return 0


def check():
    """Return the list of differences between each zip and its folder."""
    findings = []
    for target, plugin in ((ZIP_PATH, False), (PLUGIN_ZIP_PATH, True)):
        label = "dist/" + os.path.basename(target)
        if not os.path.isfile(target):
            findings.append("%s is missing; run: build.py zip" % label)
            continue
        expected = {}
        for relative, path, mode in members(plugin):
            with open(path, "rb") as handle:
                expected[relative] = (hashlib.sha256(handle.read()).hexdigest(), mode)
        actual = {}
        with zipfile.ZipFile(target) as archive:
            for info in archive.infolist():
                actual[info.filename] = (hashlib.sha256(archive.read(info)).hexdigest(),
                                         (info.external_attr >> 16) & 0o777)
        for name in sorted(set(expected) | set(actual)):
            if name not in actual:
                findings.append("%s lacks %s" % (label, name))
            elif name not in expected:
                findings.append("%s holds %s, which the folder lacks" % (label, name))
            elif expected[name] != actual[name]:
                findings.append("%s holds a different %s" % (label, name))
    return findings


def main(argv):
    if argv[1:] == ["zip"]:
        return write_zip()
    if argv[1:] == ["check"]:
        findings = check()
        for finding in findings:
            print(finding)
        print("check: %d findings" % len(findings))
        return 1 if findings else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
