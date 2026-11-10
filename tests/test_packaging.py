"""Tests for tools/build.py and for the packaging files of this repository.

Two groups:

* Fixture tests build a small complete tree (lib/ plus 17 skills) inside a
  temporary directory and exercise every build.py rule on it.
* Real-tree tests run the same checks on this repository. Each one skips with
  a reason while the part it needs (lib/, the skills, dist/) does not exist yet.

Standard library only. Nothing is written outside temporary directories.
"""

import ast
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout

sys.dont_write_bytecode = True

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_PATH = os.path.join(REPO, "tools", "build.py")

PLUGIN_SCRIPT = "${CLAUDE_PLUGIN_ROOT}/lib/ad.py"
PROJECT_SCRIPT = "${CLAUDE_PROJECT_DIR}/.claude/skills/read-manifest/scripts/ad.py"
EXPECTED_HOOKS = {
    "SessionStart": [(None, "session-start")],
    "PreToolUse": [
        ("Bash|PowerShell", "pre-bash"),
        ("Write|Edit|NotebookEdit", "pre-write"),
        ("WebFetch", "pre-fetch"),
        ("Read", "read-cache"),
    ],
    "PostToolUse": [
        ("Read", "record-read"),
        ("Bash|PowerShell|Write|Edit|NotebookEdit|WebFetch", "log"),
    ],
    "PostToolUseFailure": [("Bash|PowerShell", "log-failure")],
    "Stop": [(None, "completion-gate")],
}
HOOK_TIMEOUT_SECONDS = 10


def load_build():
    """Import tools/build.py as a fresh module, without writing bytecode."""
    spec = importlib.util.spec_from_file_location("build_under_test", BUILD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def read(path):
    with io.open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def skill_text(name, scripted, body_extra=""):
    """Return a minimal SKILL.md that passes every check."""
    lines = [
        "---",
        "name: " + name,
        'description: "Keeps one thing checkable. Use when a test needs a valid skill."',
        'compatibility: "Instruction-only skill."',
        "metadata:",
        '  version: "2.0.0"',
    ]
    if scripted:
        lines.append("allowed-tools: 'Bash(python3 \"${CLAUDE_SKILL_DIR}/scripts/ad.py\" manifest *)'")
    lines.extend(["---", "# " + name, "", "Body text.", ""])
    if scripted:
        lines.extend(
            [
                "## Tooling",
                "```",
                'python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" <sub-command>',
                'python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" manifest check notes.txt',
                "```",
                "",
            ]
        )
    lines.append(body_extra)
    return "\n".join(lines) + "\n"


class FixtureTree(unittest.TestCase):
    """Base class: a complete, clean tree in a temporary directory."""

    def setUp(self):
        self.build = load_build()
        self.root = tempfile.mkdtemp(prefix="packaging-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        for file_name in self.build.LIB_FILES:
            content = "# %s\n" % file_name
            if file_name == "ad_core.py":
                content += 'VERSION = "2.0.0"\n'
            write(os.path.join(self.root, "lib", file_name), content)
        for name in self.build.ALL_SKILLS:
            scripted = name in self.build.SCRIPTED_SKILLS
            write(self.skill_md(name), skill_text(name, scripted))
        write(
            os.path.join(self.root, ".claude", "skills", "living-reference", "scripts", "refresh_reference.py"),
            "print('refresh')\n",
        )
        write(
            os.path.join(self.root, ".claude-plugin", "plugin.json"),
            json.dumps({"name": "agent-discipline", "version": "2.0.0"}),
        )

    def skill_md(self, name):
        return os.path.join(self.root, ".claude", "skills", name, "SKILL.md")

    def scripts(self, name):
        return os.path.join(self.root, ".claude", "skills", name, "scripts")

    def make_clean(self):
        self.build.sync(self.root)
        self.build.write_zips(self.root)

    def append_body(self, name, text):
        with io.open(self.skill_md(name), "a", encoding="utf-8", newline="") as handle:
            handle.write(text)

    def replace_in_skill(self, name, old, new):
        text = read(self.skill_md(name))
        self.assertIn(old, text)
        write(self.skill_md(name), text.replace(old, new))

    def findings(self, include_dist=False):
        return self.build.check(self.root, include_dist=include_dist)

    def assert_finding(self, needle, include_dist=False):
        findings = self.findings(include_dist)
        matching = [finding for finding in findings if needle in finding]
        self.assertTrue(matching, "no finding contains %r; findings: %r" % (needle, findings))
        return matching

    def run_main(self, *arguments):
        """Run build.main with --root set to the fixture. Return (code, stdout, stderr)."""
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = self.build.main(["--root", self.root] + list(arguments))
            except SystemExit as exit_error:
                code = exit_error.code
        return code, out.getvalue(), err.getvalue()


class SyncAndDriftTests(FixtureTree):
    def test_clean_tree_has_no_findings(self):
        self.make_clean()
        self.assertEqual(self.findings(include_dist=True), [])

    def test_sync_copies_every_lib_file_into_each_scripted_skill(self):
        self.build.sync(self.root)
        for name in self.build.SCRIPTED_SKILLS:
            self.assertEqual(sorted(os.listdir(self.scripts(name))), sorted(self.build.LIB_FILES))
        for name in self.build.SCRIPT_FREE_SKILLS:
            self.assertFalse(os.path.exists(self.scripts(name)))

    def test_sync_leaves_own_script_skill_alone(self):
        self.build.sync(self.root)
        self.assertEqual(os.listdir(self.scripts("living-reference")), ["refresh_reference.py"])

    def test_missing_copies_are_reported_before_sync(self):
        self.assert_finding("read-manifest/scripts: missing")

    def test_edited_copy_is_reported_and_sync_repairs_it(self):
        self.make_clean()
        write(os.path.join(self.scripts("read-manifest"), "ad_state.py"), "# hotfix applied only here\n")
        self.assert_finding("read-manifest/scripts/ad_state.py: differs from lib/ad_state.py")
        self.build.sync(self.root)
        self.assertEqual(self.findings(), [])

    def test_lib_change_marks_every_copy_stale(self):
        self.make_clean()
        write(os.path.join(self.root, "lib", "ad_rules.py"), "# changed in lib only\n")
        matching = self.assert_finding("differs from lib/ad_rules.py")
        self.assertEqual(len(matching), len(self.build.SCRIPTED_SKILLS))

    def test_stray_entries_are_reported_and_removed_by_sync(self):
        self.make_clean()
        write(os.path.join(self.scripts("rules-hygiene"), "extra.py"), "x = 1\n")
        write(os.path.join(self.scripts("rules-hygiene"), "__pycache__", "ad.cpython-313.pyc"), "x")
        self.assert_finding("rules-hygiene/scripts/extra.py: stray entry")
        self.assert_finding("rules-hygiene/scripts/__pycache__: stray entry")
        self.build.sync(self.root)
        self.assertEqual(sorted(os.listdir(self.scripts("rules-hygiene"))), sorted(self.build.LIB_FILES))

    def test_missing_lib_file_is_reported(self):
        os.remove(os.path.join(self.root, "lib", "ad_shell.py"))
        self.assert_finding("lib/ad_shell.py: missing from the library")

    def test_script_free_skill_with_scripts_directory_is_reported(self):
        write(os.path.join(self.scripts("premise-check"), "ad.py"), "x = 1\n")
        self.assert_finding("a script-free skill must not have a scripts/ directory")

    def test_sync_skips_a_skill_without_skill_md(self):
        os.remove(self.skill_md("autonomy-ledger"))
        report = self.build.sync(self.root)
        self.assertIn("skipped autonomy-ledger: no SKILL.md yet", report)
        self.assertFalse(os.path.exists(self.scripts("autonomy-ledger")))

    def test_sync_without_lib_raises_build_error(self):
        shutil.rmtree(os.path.join(self.root, "lib"))
        with self.assertRaises(self.build.BuildError):
            self.build.sync(self.root)

    def test_missing_and_unexpected_skill_folders_are_reported(self):
        shutil.rmtree(os.path.dirname(self.skill_md("premise-check")))
        write(self.skill_md("surprise-skill"), skill_text("surprise-skill", False))
        self.assert_finding(".claude/skills/premise-check: skill folder missing")
        self.assert_finding(".claude/skills/surprise-skill: unexpected folder")


class SkillTextTests(FixtureTree):
    def setUp(self):
        FixtureTree.setUp(self)
        self.build.sync(self.root)

    def test_name_that_differs_from_folder_is_reported(self):
        self.replace_in_skill("premise-check", "name: premise-check", "name: other-name")
        self.assert_finding("frontmatter name 'other-name' differs from the folder name 'premise-check'")

    def test_frontmatter_key_outside_the_allowed_five_is_reported(self):
        self.replace_in_skill("premise-check", "metadata:", "hooks: none\nmetadata:")
        self.assert_finding("frontmatter key 'hooks' is not allowed")

    def test_license_key_is_reported_by_check_but_accepted_by_validate(self):
        self.replace_in_skill("premise-check", "metadata:", "license: MIT\nmetadata:")
        self.assert_finding("frontmatter key 'license' is not allowed")
        ok, _message = self.build.validate_skill(os.path.dirname(self.skill_md("premise-check")))
        self.assertTrue(ok)

    def test_description_over_400_characters_is_reported(self):
        long_text = "word " * 81
        self.replace_in_skill("premise-check", "Keeps one thing checkable.", long_text)
        self.assert_finding("the limit is 400")

    def test_description_of_exactly_400_characters_passes(self):
        text = read(self.skill_md("premise-check"))
        description = "d" * self.build.MAX_DESCRIPTION_CHARS
        text = re.sub(r'description: "[^"]*"', 'description: "%s"' % description, text)
        write(self.skill_md("premise-check"), text)
        self.assertEqual(self.findings(), [])

    def test_angle_bracket_in_description_is_reported(self):
        self.replace_in_skill("premise-check", "Keeps one thing checkable.", "Keeps <one> thing checkable.")
        self.assert_finding("description contains an angle bracket")

    def test_skill_md_over_500_lines_is_reported(self):
        self.append_body("premise-check", "line\n" * 500)
        self.assert_finding("the limit is 500")

    def test_unparseable_frontmatter_is_reported(self):
        self.replace_in_skill("premise-check", '"Instruction-only skill."', "Works here: and there")
        self.assert_finding("premise-check/SKILL.md: frontmatter:")

    def test_command_without_placeholder_in_fenced_block_is_reported(self):
        self.append_body("read-manifest", "\n```\npython3 scripts/ad.py manifest show\n```\n")
        self.assert_finding("command runs a script without the ${CLAUDE_SKILL_DIR} prefix")

    def test_command_without_placeholder_in_inline_code_is_reported(self):
        self.append_body("read-manifest", "\nRun `python3 scripts/ad.py manifest show` now.\n")
        self.assert_finding("command runs a script without the ${CLAUDE_SKILL_DIR} prefix")

    def test_own_script_without_placeholder_is_reported(self):
        self.append_body("living-reference", "\n```\npython3 scripts/refresh_reference.py ref.md\n```\n")
        self.assert_finding("living-reference/SKILL.md")

    def test_prose_mention_of_a_script_file_is_not_a_command(self):
        self.append_body("read-manifest", "\nThe CLI lives in `scripts/ad.py` next to this file.\n")
        self.assertEqual(self.findings(), [])

    def test_unknown_sub_command_is_reported(self):
        self.append_body("read-manifest", '\n`python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" manifests show`\n')
        self.assert_finding("`ad.py manifests` is not a sub-command")

    def test_unknown_second_level_name_is_reported(self):
        self.append_body("read-manifest", '\n```\npython3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger remove x\n```\n')
        self.assert_finding("`ad.py ledger remove` is not a sub-command")

    def test_prose_after_an_inline_example_is_not_read_as_a_sub_command(self):
        self.append_body("read-manifest", '\nRun `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger` and read it.\n')
        self.assertEqual(self.findings(), [])

    def test_arguments_and_placeholders_after_a_sub_command_pass(self):
        examples = [
            'python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" approve -- \'git push --force\'',
            'python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" ledger add GRANT "push to main"',
            'python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" manifest record PATH --range 1-40',
            'python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" hook completion-gate',
            'python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" test-impact --base main',
            'python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" trim build.log',
        ]
        self.append_body("read-manifest", "\n```\n" + "\n".join(examples) + "\n```\n")
        self.assertEqual(self.findings(), [])

    def test_unknown_sibling_under_related_skills_is_reported(self):
        self.append_body("premise-check", "\n## Related skills\n- read-manifest: records reads.\n- ghost-skill: gone.\n")
        matching = self.assert_finding("names the sibling skill 'ghost-skill'")
        self.assertEqual(len(matching), 1)

    def test_prose_bullet_under_related_skills_passes(self):
        self.append_body("premise-check", "\n## Related skills\n- the skill that matches each failing item\n")
        self.assertEqual(self.findings(), [])

    def test_unknown_sibling_under_when_not_to_use_is_reported(self):
        self.append_body("premise-check", "\n## When not to use\n- Reading files: use narrow-reading if installed.\n")
        self.assert_finding("names the sibling skill 'narrow-reading'")

    def test_hyphenated_ordinary_word_under_when_not_to_use_passes(self):
        self.append_body("premise-check", "\n## When not to use\n- For reviews, use read-only mode.\n")
        self.assertEqual(self.findings(), [])

    def test_removed_skill_name_is_reported_anywhere(self):
        self.append_body("premise-check", "\nSee also tool-output-trimmer.\n")
        self.assert_finding("names the sibling skill 'tool-output-trimmer'")

    def test_allowed_tools_that_pre_approves_approve_is_reported(self):
        self.replace_in_skill("read-manifest", 'ad.py" manifest *)', 'ad.py" manifest *) Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" approve *)')
        self.assert_finding("allowed-tools pre-approves `ad.py approve *`")

    def test_allowed_tools_that_pre_approves_scope_changes_is_reported(self):
        self.replace_in_skill("read-manifest", 'ad.py" manifest *)', 'ad.py" manifest *) Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" scope *)')
        self.assert_finding("allowed-tools pre-approves `ad.py scope *`")

    def test_allowed_tools_may_pre_approve_the_two_read_only_forms(self):
        extra = ' Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" scope show) Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" approvals show)'
        self.replace_in_skill("read-manifest", 'ad.py" manifest *)', 'ad.py" manifest *)' + extra)
        self.assertEqual(self.findings(), [])

    def test_allowed_tools_with_read_or_bare_python_is_reported(self):
        self.replace_in_skill("read-manifest", 'ad.py" manifest *)', 'ad.py" manifest *) Read Bash(python3 *)')
        self.assert_finding("allowed-tools pre-approves Read")
        self.assert_finding("allowed-tools holds a bare python rule")

    def test_version_mismatch_is_reported(self):
        self.replace_in_skill("premise-check", 'version: "2.0.0"', 'version: "1.0.0"')
        self.assert_finding("versions differ: 1.0.0, 2.0.0")

    def test_top_level_bin_directory_is_reported(self):
        os.makedirs(os.path.join(self.root, "bin"))
        self.assert_finding("bin/: claude.ai rejects a plugin")

    def test_crlf_line_endings_are_reported(self):
        text = read(self.skill_md("premise-check"))
        write(self.skill_md("premise-check"), text.replace("\n", "\r\n"))
        self.assert_finding("CRLF line endings")


class FrontmatterParserTests(unittest.TestCase):
    def setUp(self):
        self.build = load_build()

    def parse(self, text):
        return self.build.parse_frontmatter(text)

    def test_quoted_and_plain_scalars(self):
        parsed = self.parse("name: a-b\ndescription: \"Says \\\"hi\\\": twice\"\ncompatibility: 'It''s fine: yes'")
        self.assertEqual(parsed["name"], "a-b")
        self.assertEqual(parsed["description"], 'Says "hi": twice')
        self.assertEqual(parsed["compatibility"], "It's fine: yes")

    def test_nested_map_and_list(self):
        parsed = self.parse('metadata:\n  version: "2.0.0"\nallowed-tools:\n  - Bash(a *)\n  - Bash(b *)')
        self.assertEqual(parsed["metadata"], {"version": "2.0.0"})
        self.assertEqual(parsed["allowed-tools"], ["Bash(a *)", "Bash(b *)"])

    def test_folded_block_text(self):
        parsed = self.parse("description: >\n  first line\n  second line")
        self.assertEqual(parsed["description"], "first line second line")

    def test_plain_value_with_colon_space_is_rejected(self):
        with self.assertRaises(self.build.FrontmatterError):
            self.parse("description: Use when: always")

    def test_duplicate_key_is_rejected(self):
        with self.assertRaises(self.build.FrontmatterError):
            self.parse("name: a\nname: b")

    def test_split_requires_opening_and_closing_marker(self):
        with self.assertRaises(self.build.FrontmatterError):
            self.build.split_frontmatter("# no frontmatter\n")
        with self.assertRaises(self.build.FrontmatterError):
            self.build.split_frontmatter("---\nname: a\n")
        frontmatter, body = self.build.split_frontmatter("---\nname: a\n---\nBody\n")
        self.assertEqual(frontmatter, "name: a")
        self.assertEqual(body, "Body\n")

    def test_stdlib_parser_agrees_with_pyyaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not installed")
        text = skill_text("read-manifest", True)
        frontmatter, _body = self.build.split_frontmatter(text)
        self.assertEqual(self.parse(frontmatter), yaml.safe_load(frontmatter))
        self.assertEqual(self.build.yaml_cross_check(frontmatter, self.parse(frontmatter)), ([], True))


class ValidateTests(FixtureTree):
    def folder(self, name="premise-check"):
        return os.path.dirname(self.skill_md(name))

    def assert_invalid(self, needle):
        ok, message = self.build.validate_skill(self.folder())
        self.assertFalse(ok)
        self.assertIn(needle, message)

    def test_valid_skill(self):
        self.assertEqual(self.build.validate_skill(self.folder()), (True, "Skill is valid!"))

    def test_missing_skill_md(self):
        os.remove(self.skill_md("premise-check"))
        self.assert_invalid("SKILL.md not found")

    def test_no_frontmatter(self):
        write(self.skill_md("premise-check"), "# Title\n")
        self.assert_invalid("no YAML frontmatter")

    def test_unexpected_key(self):
        self.replace_in_skill("premise-check", "metadata:", "hooks: x\nmetadata:")
        self.assert_invalid("unexpected key(s) in SKILL.md frontmatter: hooks")

    def test_missing_description(self):
        text = read(self.skill_md("premise-check"))
        write(self.skill_md("premise-check"), re.sub(r"description: .*\n", "", text))
        self.assert_invalid("missing 'description'")

    def test_name_rules(self):
        for bad in ("Premise_Check", "-premise", "premise--check", "p" * 65):
            write(self.skill_md("premise-check"), skill_text(bad, False))
            ok, _message = self.build.validate_skill(self.folder())
            self.assertFalse(ok, bad)

    def test_description_rules(self):
        self.replace_in_skill("premise-check", "Keeps one thing checkable.", "x" * 1025)
        self.assert_invalid("the maximum is 1024")

    def test_compatibility_over_500_characters(self):
        self.replace_in_skill("premise-check", "Instruction-only skill.", "c" * 501)
        self.assert_invalid("the maximum is 500")

    def test_nested_skill_md_is_rejected_except_in_excluded_folders(self):
        write(os.path.join(self.folder(), "evals", "case", "SKILL.md"), "x")
        write(os.path.join(self.folder(), "__pycache__", "SKILL.md"), "x")
        self.assertTrue(self.build.validate_skill(self.folder())[0])
        write(os.path.join(self.folder(), "references", "SKILL.md"), "x")
        self.assert_invalid("found 2 SKILL.md files")

    def test_validate_reports_per_skill_findings(self):
        self.replace_in_skill("premise-check", "metadata:", "hooks: x\nmetadata:")
        findings, _notices = self.build.validate(self.root)
        self.assertEqual(len(findings), 1)
        self.assertIn(".claude/skills/premise-check", findings[0])

    def test_missing_external_validator_raises_build_error(self):
        with self.assertRaises(self.build.BuildError):
            self.build.validate(self.root, os.path.join(self.root, "no-such-validator.py"))

    def test_external_validator_result_is_used(self):
        validator = os.path.join(self.root, "fake_validator.py")
        write(validator, "import sys\nprint('Skill is valid!' if 'ask-or-assume' not in sys.argv[1] else 'bad skill')\nsys.exit('ask-or-assume' in sys.argv[1])\n")
        findings, _notices = self.build.validate(self.root, validator)
        self.assertEqual(findings, [".claude/skills/ask-or-assume: external validator: bad skill"])

    def test_external_validator_without_pyyaml_is_skipped_with_a_notice(self):
        validator = os.path.join(self.root, "needs_yaml.py")
        write(validator, "import sys\nsys.stderr.write(\"ModuleNotFoundError: No module named 'yaml'\\n\")\nsys.exit(1)\n")
        findings, notices = self.build.validate(self.root, validator)
        self.assertEqual(findings, [])
        self.assertTrue(any("external validator skipped" in notice for notice in notices))


class ZipTests(FixtureTree):
    def setUp(self):
        FixtureTree.setUp(self)
        self.build.sync(self.root)

    def archive(self, name):
        return zipfile.ZipFile(self.build.zip_path(self.root, name))

    def test_one_zip_per_skill(self):
        self.build.write_zips(self.root)
        expected = sorted(name + ".zip" for name in self.build.ALL_SKILLS)
        self.assertEqual(sorted(os.listdir(self.build.dist_dir(self.root))), expected)

    def test_zip_has_a_single_top_level_folder_and_sorted_file_members(self):
        self.build.write_zips(self.root)
        for name in self.build.ALL_SKILLS:
            with self.archive(name) as archive:
                names = archive.namelist()
            self.assertEqual(names, sorted(names))
            self.assertIn(name + "/SKILL.md", names)
            for member in names:
                self.assertTrue(member.startswith(name + "/"), member)
                self.assertFalse(member.endswith("/"), member)
                self.assertNotIn("..", member.split("/"))

    def test_zip_members_have_fixed_timestamp_and_modes(self):
        self.build.write_zips(self.root)
        with self.archive("read-manifest") as archive:
            modes = {}
            for info in archive.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(info.compress_type, zipfile.ZIP_DEFLATED)
                modes[info.filename] = (info.external_attr >> 16) & 0o777
        self.assertEqual(modes["read-manifest/SKILL.md"], 0o644)
        self.assertEqual(modes["read-manifest/scripts/ad.py"], 0o755)
        self.assertEqual(modes["read-manifest/scripts/ad_core.py"], 0o755)

    def test_zip_content_equals_the_folder(self):
        self.build.write_zips(self.root)
        with self.archive("read-manifest") as archive:
            packed = archive.read("read-manifest/scripts/ad_core.py")
        with open(os.path.join(self.root, "lib", "ad_core.py"), "rb") as handle:
            self.assertEqual(packed, handle.read())

    def test_zip_excludes_caches_tests_state_and_finder_files(self):
        folder = os.path.dirname(self.skill_md("living-reference"))
        write(os.path.join(folder, "scripts", "__pycache__", "x.cpython-313.pyc"), "x")
        write(os.path.join(folder, "scripts", "stale.pyc"), "x")
        write(os.path.join(folder, "tests", "test_refresh.py"), "x")
        write(os.path.join(folder, ".DS_Store"), "x")
        write(os.path.join(folder, ".agent", "ledger.md"), "x")
        write(os.path.join(folder, "references", "design.md"), "kept\n")
        self.build.write_zips(self.root)
        with self.archive("living-reference") as archive:
            names = archive.namelist()
        self.assertEqual(
            names,
            [
                "living-reference/SKILL.md",
                "living-reference/references/design.md",
                "living-reference/scripts/refresh_reference.py",
            ],
        )

    def test_two_builds_give_identical_bytes_whatever_the_file_times(self):
        first = self.build.build_zip_bytes(self.root, "read-manifest")
        for file_name in self.build.LIB_FILES:
            os.utime(os.path.join(self.scripts("read-manifest"), file_name), (86400 * 400, 86400 * 400))
        os.chmod(self.skill_md("read-manifest"), 0o600)
        second = self.build.build_zip_bytes(self.root, "read-manifest")
        self.assertEqual(first, second)

    def test_build_from_a_copied_tree_gives_identical_bytes(self):
        copy_root = tempfile.mkdtemp(prefix="packaging-copy-")
        self.addCleanup(shutil.rmtree, copy_root, True)
        shutil.copytree(os.path.join(self.root, ".claude"), os.path.join(copy_root, ".claude"))
        self.assertEqual(
            self.build.build_zip_bytes(self.root, "autonomy-ledger"),
            self.build.build_zip_bytes(copy_root, "autonomy-ledger"),
        )

    def test_missing_zip_is_reported(self):
        self.assert_finding("dist/premise-check.zip: missing", include_dist=True)

    def test_stale_zip_is_reported_and_rebuilt(self):
        self.build.write_zips(self.root)
        self.append_body("premise-check", "\nOne more line.\n")
        self.assert_finding("dist/premise-check.zip: premise-check/SKILL.md differs from the folder", include_dist=True)
        report = self.build.write_zips(self.root)
        self.assertEqual(len([line for line in report if line.startswith("wrote ")]), 1)
        self.assertEqual(self.findings(include_dist=True), [])

    def test_zip_with_added_or_removed_member_is_reported(self):
        self.build.write_zips(self.root)
        folder = os.path.dirname(self.skill_md("premise-check"))
        write(os.path.join(folder, "references", "extra.md"), "x\n")
        self.assert_finding("dist/premise-check.zip: lacks premise-check/references/extra.md", include_dist=True)
        self.build.write_zips(self.root)
        shutil.rmtree(os.path.join(folder, "references"))
        self.assert_finding("holds premise-check/references/extra.md, which the folder lacks", include_dist=True)

    def test_zip_that_matches_no_skill_is_reported(self):
        self.build.write_zips(self.root)
        shutil.copyfile(self.build.zip_path(self.root, "premise-check"), self.build.zip_path(self.root, "old-skill"))
        self.assert_finding("dist/old-skill.zip: matches no skill folder", include_dist=True)

    def test_hand_made_zip_with_wrong_layout_is_reported(self):
        self.build.write_zips(self.root)
        with zipfile.ZipFile(self.build.zip_path(self.root, "premise-check"), "w") as archive:
            archive.writestr("SKILL.md", read(self.skill_md("premise-check")))
        self.assert_finding("is outside the single top-level folder premise-check/", include_dist=True)

    def test_up_to_date_zip_is_not_rewritten_unless_forced(self):
        self.build.write_zips(self.root)
        path = self.build.zip_path(self.root, "premise-check")
        os.utime(path, (86400 * 400, 86400 * 400))
        stamp = os.stat(path).st_mtime
        self.build.write_zips(self.root)
        self.assertEqual(os.stat(path).st_mtime, stamp)
        self.build.write_zips(self.root, force=True)
        self.assertNotEqual(os.stat(path).st_mtime, stamp)

    def test_symbolic_link_in_a_skill_folder_stops_the_build(self):
        if not hasattr(os, "symlink"):
            self.skipTest("no symbolic links on this platform")
        folder = os.path.dirname(self.skill_md("premise-check"))
        try:
            os.symlink(self.skill_md("ask-or-assume"), os.path.join(folder, "link.md"))
        except OSError:
            self.skipTest("cannot create a symbolic link here")
        with self.assertRaises(self.build.BuildError):
            self.build.build_zip_bytes(self.root, "premise-check")

    def test_zip_unpacks_to_a_folder_that_validates(self):
        self.build.write_zips(self.root)
        target = tempfile.mkdtemp(prefix="packaging-unzip-")
        self.addCleanup(shutil.rmtree, target, True)
        with self.archive("read-manifest") as archive:
            archive.extractall(target)
        self.assertEqual(os.listdir(target), ["read-manifest"])
        self.assertTrue(self.build.validate_skill(os.path.join(target, "read-manifest"))[0])


class CommandLineTests(FixtureTree):
    def test_no_sub_command_is_a_usage_error(self):
        code, _out, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("usage", err)

    def test_unknown_sub_command_is_a_usage_error(self):
        code, _out, _err = self.run_main("publish")
        self.assertEqual(code, 2)

    def test_check_exits_1_and_lists_findings(self):
        code, out, _err = self.run_main("check")
        self.assertEqual(code, 1)
        self.assertIn("read-manifest/scripts: missing", out)

    def test_all_builds_a_clean_tree(self):
        code, out, _err = self.run_main("all")
        self.assertEqual(code, 0, out)
        self.assertIn("check: clean", out)
        self.assertIn("validate: clean", out)
        self.assertIn("dist: clean", out)
        code, out, _err = self.run_main("check")
        self.assertEqual(code, 0, out)

    def test_all_stops_before_zip_when_a_check_fails(self):
        self.replace_in_skill("premise-check", "name: premise-check", "name: wrong-name")
        code, out, _err = self.run_main("all")
        self.assertEqual(code, 1)
        self.assertIn("zip: skipped", out)
        self.assertFalse(os.path.exists(self.build.dist_dir(self.root)))

    def test_sync_without_lib_exits_2_with_a_message(self):
        shutil.rmtree(os.path.join(self.root, "lib"))
        code, _out, err = self.run_main("sync")
        self.assertEqual(code, 2)
        self.assertIn("error: lib/ not found", err)

    def test_validate_exits_1_on_an_invalid_skill(self):
        write(self.skill_md("premise-check"), "# no frontmatter\n")
        code, out, _err = self.run_main("validate")
        self.assertEqual(code, 1)
        self.assertIn("premise-check", out)

    def test_script_runs_from_another_working_directory(self):
        completed = subprocess.run(
            [sys.executable, "-B", BUILD_PATH, "--root", self.root, "all"],
            cwd=tempfile.gettempdir(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


class BuildToolSourceTests(unittest.TestCase):
    def test_skill_lists_cover_17_distinct_skills(self):
        build = load_build()
        self.assertEqual(len(build.SCRIPTED_SKILLS), 11)
        self.assertEqual(len(build.SCRIPT_FREE_SKILLS), 5)
        self.assertEqual(len(build.ALL_SKILLS), 17)
        self.assertEqual(len(set(build.ALL_SKILLS)), 17)
        self.assertEqual(len(build.LIB_FILES), 8)

    def test_build_tool_and_this_test_parse_as_python_3_8(self):
        for path in (BUILD_PATH, os.path.abspath(__file__)):
            ast.parse(read(path), filename=path, feature_version=(3, 8))


# ---------------------------------------------------------------- real tree

def hook_entries(config):
    """Yield (event, matcher, handler) for every handler in a hooks config."""
    for event, groups in config["hooks"].items():
        for group in groups:
            for handler in group["hooks"]:
                yield event, group.get("matcher"), handler


def argparse_choices(help_text):
    """Return the names inside the first `{a,b,c}` group of an argparse help text."""
    match = re.search(r"\{([^{}]+)\}", " ".join(help_text.split()))
    if not match:
        return None
    return sorted(name.strip() for name in match.group(1).split(",") if name.strip())


class RealManifestTests(unittest.TestCase):
    """The plugin manifest and the marketplace file, checked against the docs' rules."""

    def load(self, *parts):
        path = os.path.join(REPO, *parts)
        if not os.path.isfile(path):
            self.skipTest("%s does not exist yet" % "/".join(parts))
        return json.loads(read(path))

    def test_plugin_manifest_fields(self):
        manifest = self.load(".claude-plugin", "plugin.json")
        self.assertEqual(manifest["name"], "agent-discipline")
        self.assertEqual(manifest["version"], "2.0.0")
        self.assertEqual(manifest["author"]["name"], "CatCorner22")
        self.assertTrue(manifest["description"].strip())
        self.assertEqual(manifest["skills"], ["./.claude/skills/"])
        documented = {
            "$schema", "name", "displayName", "version", "description", "author", "homepage", "repository",
            "license", "keywords", "metadata", "skills", "hooks",
        }
        self.assertEqual(sorted(set(manifest) - documented), [])

    def test_plugin_component_paths_start_with_dot_slash_and_stay_inside(self):
        manifest = self.load(".claude-plugin", "plugin.json")
        for path in manifest["skills"]:
            self.assertTrue(path.startswith("./"), path)
            self.assertNotIn("..", path.split("/"))

    def test_plugin_skills_path_exists(self):
        manifest = self.load(".claude-plugin", "plugin.json")
        if not os.path.isdir(os.path.join(REPO, ".claude", "skills")):
            self.skipTest(".claude/skills/ does not exist yet")
        for path in manifest["skills"]:
            self.assertTrue(os.path.isdir(os.path.join(REPO, path)), path)

    def test_plugin_description_states_the_real_skill_count(self):
        manifest = self.load(".claude-plugin", "plugin.json")
        self.assertIn("%d skills" % len(load_build().ALL_SKILLS), manifest["description"])

    def test_marketplace_has_required_fields_and_one_matching_entry(self):
        manifest = self.load(".claude-plugin", "plugin.json")
        marketplace = self.load(".claude-plugin", "marketplace.json")
        self.assertTrue(re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", marketplace["name"]))
        self.assertTrue(marketplace["owner"]["name"].strip())
        self.assertEqual(len(marketplace["plugins"]), 1)
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], manifest["name"])
        self.assertEqual(entry["source"], "./")
        self.assertNotIn("version", entry)
        self.assertEqual(sorted(set(marketplace) - {"name", "description", "owner", "plugins"}), [])
        self.assertEqual(sorted(set(entry) - {"name", "source", "description"}), [])

    def test_repository_has_no_top_level_bin_directory(self):
        self.assertFalse(os.path.exists(os.path.join(REPO, "bin")))


class RealHooksTests(unittest.TestCase):
    """hooks/hooks.json and the project-settings example."""

    def load(self, *parts):
        path = os.path.join(REPO, *parts)
        if not os.path.isfile(path):
            self.skipTest("%s does not exist yet" % "/".join(parts))
        return json.loads(read(path))

    def assert_hook_shape(self, config, script):
        self.assertEqual(list(config), ["hooks"])
        self.assertEqual(sorted(config["hooks"]), sorted(EXPECTED_HOOKS))
        self.assertNotIn("PostCompact", config["hooks"])
        for event, expected in EXPECTED_HOOKS.items():
            actual = []
            for group in config["hooks"][event]:
                self.assertEqual(len(group["hooks"]), 1)
                actual.append((group.get("matcher"), group["hooks"][0]["args"][-1]))
            self.assertEqual(actual, expected, event)
        for _event, matcher, handler in hook_entries(config):
            self.assertEqual(handler["type"], "command")
            self.assertEqual(handler["command"], "python3")
            self.assertEqual(handler["timeout"], HOOK_TIMEOUT_SECONDS)
            arguments = handler["args"]
            self.assertEqual(arguments[0], "-c")
            self.assertIn("os.path.isfile(p)", arguments[1])
            self.assertEqual(arguments[2:4], [script, "hook"])
            self.assertEqual(len(arguments), 5)
            if matcher:
                self.assertNotIn("MultiEdit", matcher)

    def test_plugin_hooks_follow_the_specified_shape(self):
        self.assert_hook_shape(self.load("hooks", "hooks.json"), PLUGIN_SCRIPT)

    def test_settings_example_follows_the_specified_shape(self):
        self.assert_hook_shape(self.load("docs", "hooks-settings-example.json"), PROJECT_SCRIPT)

    def test_settings_example_equals_plugin_hooks_except_for_the_script_path(self):
        plugin_text = json.dumps(self.load("hooks", "hooks.json"), sort_keys=True)
        example_text = json.dumps(self.load("docs", "hooks-settings-example.json"), sort_keys=True)
        self.assertEqual(plugin_text.replace(PLUGIN_SCRIPT, PROJECT_SCRIPT), example_text)

    def test_every_hook_name_is_a_known_hook_sub_command(self):
        known = load_build().AD_SUBCOMMANDS["hook"]
        for _event, _matcher, handler in hook_entries(self.load("hooks", "hooks.json")):
            self.assertIn(handler["args"][-1], known)

    def test_settings_example_script_belongs_to_a_scripted_skill(self):
        self.assertIn("read-manifest", load_build().SCRIPTED_SKILLS)

    def test_bootstrap_exits_0_when_the_script_is_missing(self):
        handler = self.load("hooks", "hooks.json")["hooks"]["PreToolUse"][0]["hooks"][0]
        missing = os.path.join(tempfile.gettempdir(), "no-such-plugin-root", "lib", "ad.py")
        completed = subprocess.run(
            [sys.executable, "-c", handler["args"][1], missing, "hook", "pre-bash"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, b"")

    def test_bootstrap_runs_the_script_with_its_arguments(self):
        handler = self.load("hooks", "hooks.json")["hooks"]["PreToolUse"][0]["hooks"][0]
        folder = tempfile.mkdtemp(prefix="packaging-hook-")
        self.addCleanup(shutil.rmtree, folder, True)
        script = os.path.join(folder, "ad.py")
        write(script, "import sys\nprint(__name__, sys.argv[1:])\n")
        completed = subprocess.run(
            [sys.executable, "-B", "-c", handler["args"][1], script, "hook", "pre-bash"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "__main__ ['hook', 'pre-bash']")


class RealLibraryTests(unittest.TestCase):
    """AD_SUBCOMMANDS in build.py must equal the CLI surface of lib/ad.py."""

    def setUp(self):
        self.ad = os.path.join(REPO, "lib", "ad.py")
        if not os.path.isfile(self.ad):
            self.skipTest("lib/ad.py does not exist yet")
        self.work = tempfile.mkdtemp(prefix="packaging-ad-")
        self.addCleanup(shutil.rmtree, self.work, True)

    def help_text(self, *arguments):
        environment = dict(os.environ)
        environment["AGENT_STATE_DIR"] = os.path.join(self.work, "state")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-B", self.ad] + list(arguments) + ["--help"],
            cwd=self.work,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        return completed.returncode, completed.stdout

    def test_top_level_sub_commands_match(self):
        code, text = self.help_text()
        self.assertEqual(code, 0)
        choices = argparse_choices(text)
        expected = sorted(load_build().AD_SUBCOMMANDS)
        if choices is None:
            for name in expected:
                self.assertEqual(self.help_text(name)[0], 0, "ad.py %s --help failed" % name)
            return
        self.assertEqual(choices, expected)

    def test_second_level_names_match(self):
        for name, second_level in sorted(load_build().AD_SUBCOMMANDS.items()):
            if not second_level:
                continue
            code, text = self.help_text(name)
            self.assertEqual(code, 0, "ad.py %s --help failed" % name)
            choices = argparse_choices(text)
            if choices is None:
                continue
            self.assertEqual(choices, sorted(second_level), "ad.py %s" % name)

    def test_help_calls_leave_no_state_directory(self):
        self.help_text()
        self.assertFalse(os.path.exists(os.path.join(self.work, "state")))
        self.assertFalse(os.path.exists(os.path.join(self.work, ".agent")))


class RealTreeTests(unittest.TestCase):
    """build.py check and validate on this repository, so drift fails the suite."""

    def setUp(self):
        self.build = load_build()
        if not os.path.isdir(os.path.join(REPO, "lib")):
            self.skipTest("lib/ does not exist yet")
        missing = [name for name in self.build.ALL_SKILLS if not os.path.isfile(os.path.join(REPO, ".claude", "skills", name, "SKILL.md"))]
        if missing:
            self.skipTest("%d of 17 skills do not exist yet (first: %s)" % (len(missing), missing[0]))

    def test_check_is_clean_apart_from_dist(self):
        self.assertEqual(self.build.check(REPO, include_dist=False), [])

    def test_validate_is_clean(self):
        findings, _notices = self.build.validate(REPO)
        self.assertEqual(findings, [])

    def test_dist_zips_match_the_skill_folders(self):
        if not os.path.isdir(os.path.join(REPO, "dist")):
            self.skipTest("dist/ does not exist yet; run tools/build.py all")
        self.assertEqual(self.build.check_dist(REPO), [])

    def test_every_scripted_skill_reports_the_library_version(self):
        environment = dict(os.environ)
        work = tempfile.mkdtemp(prefix="packaging-version-")
        self.addCleanup(shutil.rmtree, work, True)
        environment["AGENT_STATE_DIR"] = os.path.join(work, "state")
        outputs = set()
        for name in self.build.SCRIPTED_SKILLS:
            script = os.path.join(REPO, ".claude", "skills", name, "scripts", "ad.py")
            if not os.path.isfile(script):
                self.skipTest("generated copies do not exist yet; run tools/build.py sync")
            completed = subprocess.run(
                [sys.executable, "-B", script, "version"],
                cwd=work,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            outputs.add(completed.stdout.strip())
        self.assertEqual(outputs, {"agent-discipline 2.0.0"})
        for name in self.build.SCRIPTED_SKILLS:
            cache = os.path.join(REPO, ".claude", "skills", name, "scripts", "__pycache__")
            self.assertFalse(os.path.exists(cache), cache)


class RealRepositoryFilesTests(unittest.TestCase):
    def read_or_skip(self, name):
        path = os.path.join(REPO, name)
        if not os.path.isfile(path):
            self.skipTest("%s does not exist yet" % name)
        return read(path)

    def test_gitignore_lists_the_four_patterns(self):
        lines = self.read_or_skip(".gitignore").split("\n")
        for pattern in (".agent/", "__pycache__/", "*.pyc", ".DS_Store"):
            self.assertIn(pattern, lines)
        self.assertNotIn("dist/", lines)

    def test_readme_names_every_skill(self):
        text = self.read_or_skip("README.md")
        for name in load_build().ALL_SKILLS:
            self.assertIn("`%s`" % name, text)

    def test_readme_documents_every_cli_sub_command(self):
        text = self.read_or_skip("README.md")
        for name in load_build().AD_SUBCOMMANDS:
            self.assertIn("`%s" % name, text)

    def test_changelog_has_an_entry_for_the_manifest_version(self):
        text = self.read_or_skip("CHANGELOG.md")
        manifest = json.loads(self.read_or_skip(os.path.join(".claude-plugin", "plugin.json")))
        self.assertIn("## [%s]" % manifest["version"], text)

    def test_tests_leave_no_state_directory_in_the_repository(self):
        self.assertFalse(os.path.exists(os.path.join(REPO, ".agent")))


if __name__ == "__main__":
    unittest.main()
