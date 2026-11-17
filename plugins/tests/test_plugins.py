"""Tests for the Claude Code plugins under plugins/.

Structure: every plugin has a manifest that the marketplace lists; every skill has valid
frontmatter and can be loaded by the model; every file that a skill names exists; every
command that runs a bundled script uses ${CLAUDE_SKILL_DIR}.
Build: the upload zips match their folders, and the generated plugins match what the build
script produces from the pinned source, when that source checkout is present.

Run from any directory:
    python3 -B -m unittest discover -s plugins/tests
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.dont_write_bytecode = True
PLUGINS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(PLUGINS)
EXPECTED = {
    "coding": ["clean-minimal-code", "coding-ecosystem-primer", "deliverable-first", "real-time-testing",
               "stable-architecture", "ui-engineering", "ux-engineering"],
    "plain-language": ["one-way-optimal-language", "unambiguous-language"],
    "red-team": ["red-team-lead"],
}
MAX_DESCRIPTION_CHARS = 1024
MAX_SKILL_LINES = 500
RESOURCE_PATH = re.compile(r"\b((?:scripts|references|templates|data|assets)/[A-Za-z0-9_.\-/]+\.[A-Za-z0-9]+)")
BARE_SCRIPT_COMMAND = re.compile(r"python3?(?:\s+-\S+)*\s+(?![\"']?\$\{CLAUDE_SKILL_DIR\})[\"']?[\w./-]*\w+\.py\b")


def load_build():
    spec = importlib.util.spec_from_file_location("build_plugins", os.path.join(PLUGINS, "tools", "build_plugins.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def skill_dir(plugin, skill):
    return os.path.join(PLUGINS, plugin, "skills", skill)


def frontmatter(text):
    """Return (dict of top-level keys -> raw value text, body). Fails on a file with no frontmatter."""
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.S)
    if not match:
        raise AssertionError("no frontmatter")
    keys = {}
    current = None
    for line in match.group(1).split("\n"):
        top = re.match(r"^([A-Za-z_-]+):(.*)$", line)
        if top:
            current = top.group(1)
            keys[current] = top.group(2).strip()
        elif current is not None:
            keys[current] += "\n" + line
    return keys, match.group(2)


def scalar(raw):
    """Return the text of a single-line YAML scalar, with or without double quotes."""
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return json.loads(raw)
    return raw


def all_skills():
    return [(plugin, skill) for plugin, skills in sorted(EXPECTED.items()) for skill in skills]


class StructureTests(unittest.TestCase):
    def test_each_plugin_holds_exactly_the_expected_skills(self):
        for plugin, skills in EXPECTED.items():
            with self.subTest(plugin=plugin):
                self.assertEqual(sorted(os.listdir(os.path.join(PLUGINS, plugin, "skills"))), skills)

    def test_each_manifest_names_its_folder_and_has_a_version_and_a_description(self):
        for plugin in EXPECTED:
            with self.subTest(plugin=plugin):
                manifest = json.loads(read(os.path.join(PLUGINS, plugin, ".claude-plugin", "plugin.json")))
                self.assertEqual(manifest["name"], plugin)
                self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
                self.assertTrue(manifest["description"].strip())
                self.assertTrue(os.path.isfile(os.path.join(PLUGINS, plugin, "README.md")))

    def test_the_root_marketplace_lists_each_plugin(self):
        marketplace = json.loads(read(os.path.join(REPO, ".claude-plugin", "marketplace.json")))
        sources = {entry["name"]: entry["source"] for entry in marketplace["plugins"]}
        for plugin in EXPECTED:
            self.assertEqual(sources.get(plugin), "./plugins/" + plugin)

    def test_frontmatter_lets_claude_code_load_and_invoke_each_skill(self):
        for plugin, skill in all_skills():
            with self.subTest(skill=skill):
                keys, _body = frontmatter(read(os.path.join(skill_dir(plugin, skill), "SKILL.md")))
                self.assertEqual(scalar(keys["name"]), skill)
                description = scalar(keys["description"])
                self.assertTrue(description)
                self.assertNotIn("\n", description)
                self.assertLessEqual(len(description), MAX_DESCRIPTION_CHARS)
                self.assertNotIn("disable-model-invocation", keys)
                self.assertEqual(sorted(set(keys) - {"name", "description", "metadata"}), [])

    def test_no_skill_file_is_too_long_or_uses_crlf(self):
        for plugin, skill in all_skills():
            with self.subTest(skill=skill):
                with open(os.path.join(skill_dir(plugin, skill), "SKILL.md"), "rb") as handle:
                    raw = handle.read()  # bytes: text mode would turn a CRLF into a LF before the check
                self.assertNotIn(b"\r", raw)
                self.assertLessEqual(len(raw.decode("utf-8").rstrip("\n").split("\n")), MAX_SKILL_LINES)

    def test_every_bundled_file_that_a_skill_names_exists(self):
        for plugin, skill in all_skills():
            folder = skill_dir(plugin, skill)
            for relative in sorted(set(RESOURCE_PATH.findall(read(os.path.join(folder, "SKILL.md"))))):
                with self.subTest(skill=skill, path=relative):
                    if relative.startswith("skills/"):
                        continue
                    self.assertTrue(os.path.isfile(os.path.join(folder, *relative.split("/"))), relative)

    def test_every_command_that_runs_a_bundled_script_uses_the_skill_folder(self):
        for plugin, skill in all_skills():
            folder = skill_dir(plugin, skill)
            scripts = os.path.join(folder, "scripts")
            if not os.path.isdir(scripts):
                continue
            text = read(os.path.join(folder, "SKILL.md"))
            for name in sorted(os.listdir(scripts)):
                if not name.endswith(".py"):
                    continue
                with self.subTest(skill=skill, script=name):
                    self.assertIn('"${CLAUDE_SKILL_DIR}/scripts/%s"' % name, text)
                    for line in text.split("\n"):
                        if name in line and BARE_SCRIPT_COMMAND.search(line):
                            self.fail("a command runs %s without ${CLAUDE_SKILL_DIR}: %s" % (name, line[:160]))

    def test_every_bundled_python_script_compiles(self):
        for plugin, skill in all_skills():
            for current, _dirs, files in os.walk(skill_dir(plugin, skill)):
                for name in files:
                    if name.endswith(".py"):
                        with self.subTest(script=name):
                            compile(read(os.path.join(current, name)), name, "exec")

    def test_no_skill_ships_evals_caches_or_cursor_files(self):
        for plugin in EXPECTED:
            for current, dirs, files in os.walk(os.path.join(PLUGINS, plugin)):
                for name in dirs + files:
                    self.assertNotIn(name, ("evals", "__pycache__", ".cursor", ".cursor-plugin", ".DS_Store"),
                                     os.path.join(current, name))


class ActiveVoiceCheckerTests(unittest.TestCase):
    """The plain-language plugin must ship a checker that runs: its absence was the defect."""

    def run_checker(self, text):
        script = os.path.join(skill_dir("plain-language", "one-way-optimal-language"), "scripts",
                              "active_voice_check.py")
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "sample.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            return subprocess.run([sys.executable, "-B", script, "--strict", "--no-spacy", path],
                                  capture_output=True, text=True, timeout=120)

    def test_an_active_text_passes(self):
        result = self.run_checker("Take one tablet every morning.  Your doctor will adjust the dose.\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_passive_text_fails(self):
        result = self.run_checker("The dose was changed by the doctor.  The form must be signed.\n")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("PASSIVE", result.stdout)


class SourceStateTests(unittest.TestCase):
    """The build stamps each skill with the source commit, so the source must hold exactly that commit."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="plugins-source-")
        self.addCleanup(__import__("shutil").rmtree, self.folder, True)
        for pack in ("coding", "legal"):
            os.makedirs(os.path.join(self.folder, "skills", pack, "a-skill"))
            with open(os.path.join(self.folder, "skills", pack, "a-skill", "SKILL.md"), "w") as handle:
                handle.write("x\n")
        for args in (["init", "-q", "."], ["add", "-A"],
                     ["-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "init"]):
            subprocess.run(["git"] + args, cwd=self.folder, check=True, capture_output=True)

    def test_a_clean_checkout_reports_its_commit_and_no_changes(self):
        commit, changed = load_build().source_state(self.folder)
        self.assertRegex(commit, r"^[0-9a-f]{40}$")
        self.assertEqual(changed, [])

    def test_an_edited_file_and_an_untracked_file_are_reported(self):
        with open(os.path.join(self.folder, "skills", "legal", "a-skill", "SKILL.md"), "w") as handle:
            handle.write("changed\n")
        with open(os.path.join(self.folder, "skills", "coding", "a-skill", "extra.md"), "w") as handle:
            handle.write("new\n")
        _commit, changed = load_build().source_state(self.folder)
        self.assertEqual(sorted(changed), ["skills/coding/a-skill/extra.md", "skills/legal/a-skill/SKILL.md"])

    def test_a_folder_that_git_cannot_read_reports_no_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(load_build().source_state(folder), (None, []))


class ConsistencyTests(unittest.TestCase):
    """Facts that live in more than 1 file must agree."""

    def test_the_version_agrees_in_the_manifest_the_readme_and_each_generated_skill(self):
        build = load_build()
        for plugin, skills in EXPECTED.items():
            with self.subTest(plugin=plugin):
                version = json.loads(read(os.path.join(PLUGINS, plugin, ".claude-plugin", "plugin.json")))["version"]
                self.assertIn("Version %s." % version, read(os.path.join(PLUGINS, plugin, "README.md")))
                self.assertIn("| `%s` | %s |" % (plugin, version), read(os.path.join(PLUGINS, "README.md")))
                if plugin in build.GENERATED:
                    self.assertEqual(build.GENERATED[plugin]["version"], version)
                    for skill in skills:
                        keys, _body = frontmatter(read(os.path.join(skill_dir(plugin, skill), "SKILL.md")))
                        self.assertIn('version: "%s"' % version, keys["metadata"], skill)

    def test_the_files_table_of_the_one_way_skill_lists_exactly_its_bundled_files(self):
        folder = skill_dir("plain-language", "one-way-optimal-language")
        text = read(os.path.join(folder, "SKILL.md"))
        table = text[text.index("## Files in this skill"):]
        listed = sorted(re.findall(r"^\| `((?:scripts|references)/[^`]+)` \|", table, re.M))
        actual = sorted(os.path.relpath(os.path.join(current, name), folder).replace(os.sep, "/")
                        for sub in ("scripts", "references")
                        for current, _dirs, files in os.walk(os.path.join(folder, sub)) for name in files)
        self.assertEqual(listed, actual)

    def test_plugin_folders_hold_no_links_and_no_backup_files(self):
        for plugin in EXPECTED:
            for current, dirs, files in os.walk(os.path.join(PLUGINS, plugin)):
                for name in dirs + files:
                    path = os.path.join(current, name)
                    self.assertFalse(os.path.islink(path), path)
                    self.assertFalse(name.endswith(("~", ".orig", ".bak", ".swp", ".tmp", ".rej")), path)

    def test_the_router_says_where_the_verified_build_loop_lives(self):
        text = read(os.path.join(skill_dir("coding", "coding-ecosystem-primer"), "SKILL.md"))
        self.assertIn("`verified-build-loop:verified-build-loop`", text)


class BuildTests(unittest.TestCase):
    def test_each_upload_zip_matches_its_plugin_folder(self):
        self.assertEqual(load_build().check_zips(), [])

    def test_each_zip_has_one_top_folder_with_the_manifest(self):
        for plugin in EXPECTED:
            with self.subTest(plugin=plugin):
                with zipfile.ZipFile(os.path.join(PLUGINS, "dist", plugin + "-plugin.zip")) as archive:
                    names = archive.namelist()
                self.assertEqual({name.split("/")[0] for name in names}, {plugin})
                self.assertIn(plugin + "/.claude-plugin/plugin.json", names)
                for skill in EXPECTED[plugin]:
                    self.assertIn("%s/skills/%s/SKILL.md" % (plugin, skill), names)

    def test_every_generated_skill_records_its_source(self):
        build = load_build()
        for plugin, skill in all_skills():
            if plugin == "red-team":
                continue
            with self.subTest(skill=skill):
                text = read(os.path.join(skill_dir(plugin, skill), "SKILL.md"))
                self.assertIn(build.SOURCE_COMMIT[:7], frontmatter(text)[0]["metadata"])

    def test_the_committed_plugins_equal_a_fresh_build_from_the_pinned_source(self):
        build = load_build()
        source = os.environ.get("CURSOR_SKILLS_DIR", build.DEFAULT_SOURCE)
        if not os.path.isdir(os.path.join(source, "skills", "coding")):
            self.skipTest("no Cursor_Skills checkout at %s; set CURSOR_SKILLS_DIR to run this test" % source)
        commit, changed = build.source_state(source)
        self.assertIsNotNone(commit, "git cannot read the checkout at %s" % source)
        if commit != build.SOURCE_COMMIT:
            self.skipTest("the checkout at %s is not at the pinned commit %s" % (source, build.SOURCE_COMMIT[:7]))
        self.assertEqual(changed, [], "the checkout holds changes that the pinned commit does not")
        with tempfile.TemporaryDirectory() as folder:
            build.generate(source, folder)
            for plugin, skill in all_skills():
                if plugin == "red-team":
                    continue
                fresh = os.path.join(folder, plugin, "skills", skill)
                committed = skill_dir(plugin, skill)
                listing = lambda root: sorted(  # noqa: E731
                    os.path.relpath(os.path.join(current, name), root)
                    for current, _dirs, files in os.walk(root) for name in files)
                self.assertEqual(listing(committed), listing(fresh), skill)
                for relative in listing(fresh):
                    with open(os.path.join(fresh, relative), "rb") as a, open(os.path.join(committed, relative), "rb") as b:
                        self.assertEqual(a.read(), b.read(), "%s/%s" % (skill, relative))


if __name__ == "__main__":
    unittest.main()
