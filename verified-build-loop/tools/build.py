#!/usr/bin/env python3
"""Build and check the claude.ai upload package of the verified-build-loop skill. Standard library only.

The skill folder is plugin/skills/verified-build-loop/. The zip holds that folder under the name
verified-build-loop/.

    python3 verified-build-loop/tools/build.py zip     write dist/verified-build-loop.zip
    python3 verified-build-loop/tools/build.py check   exit 1 when the zip differs from the skill folder

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
ZIP_PATH = os.path.join(PACKAGE, "dist", NAME + ".zip")
SKIP_DIRS = {"__pycache__"}
SKIP_FILES = {".DS_Store"}


def members():
    """Return [(name in the zip, absolute path, mode)] for every file of the skill folder, sorted."""
    found = []
    for current, dirs, files in os.walk(SKILL):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name in SKIP_FILES or name.endswith(".pyc"):
                continue
            path = os.path.join(current, name)
            relative = os.path.relpath(path, SKILLS).replace(os.sep, "/")
            mode = 0o755 if name.endswith((".py", ".sh")) else 0o644
            found.append((relative, path, mode))
    return sorted(found)


def write_zip():
    os.makedirs(os.path.dirname(ZIP_PATH), exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative, path, mode in members():
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100000 | mode) << 16
            with open(path, "rb") as handle:
                archive.writestr(info, handle.read())
    print("wrote %s (%d files)" % (os.path.relpath(ZIP_PATH, PACKAGE), len(members())))
    return 0


def check():
    """Return the list of differences between the zip and the skill folder."""
    if not os.path.isfile(ZIP_PATH):
        return ["dist/%s.zip is missing; run: build.py zip" % NAME]
    expected = {}
    for relative, path, mode in members():
        with open(path, "rb") as handle:
            expected[relative] = (hashlib.sha256(handle.read()).hexdigest(), mode)
    actual = {}
    with zipfile.ZipFile(ZIP_PATH) as archive:
        for info in archive.infolist():
            actual[info.filename] = (hashlib.sha256(archive.read(info)).hexdigest(),
                                     (info.external_attr >> 16) & 0o777)
    findings = []
    for name in sorted(set(expected) | set(actual)):
        if name not in actual:
            findings.append("the zip lacks %s" % name)
        elif name not in expected:
            findings.append("the zip holds %s, which the skill folder lacks" % name)
        elif expected[name] != actual[name]:
            findings.append("the zip holds a different %s" % name)
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
