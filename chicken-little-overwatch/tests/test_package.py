"""Tests for Chicken Little Overwatch: the scanners, the validator, the agents, and the zips.

Run from the chicken-little-overwatch/ folder:

    python3 -m unittest discover -s tests
"""
import hashlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "chicken-little-overwatch"
PLUGIN = os.path.join(HOME, NAME)
SKILL = os.path.join(PLUGIN, "skills", NAME)
SCRIPTS = os.path.join(SKILL, "scripts")
AV = os.path.join(SCRIPTS, "av_scan.py")
WATCH = os.path.join(SCRIPTS, "watchlist_scan.py")
VALIDATOR = os.path.join(PLUGIN, "tools", "validate_package.py")
BUILD = os.path.join(HOME, "tools", "build.py")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(script, *arguments, stdin=None):
    completed = subprocess.run([sys.executable, "-B", script] + list(arguments), input=stdin,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    return completed.returncode, completed.stdout, completed.stderr


class ScratchCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="clo-test-")
        self.addCleanup(shutil.rmtree, self.folder, True)

    def write(self, text, name="sample.md", raw=None):
        path = os.path.join(self.folder, name)
        with open(path, "wb") as handle:
            handle.write(raw if raw is not None else text.encode("utf-8"))
        return path


class ActiveVoiceScannerTests(ScratchCase):
    def test_active_text_exits_0(self):
        code, out, err = run(AV, self.write("The nurse checks your blood pressure.\n"))
        self.assertEqual((code, out), (0, ""))
        self.assertIn("blocking=0", err)

    def test_passive_exits_1_and_names_the_line(self):
        code, out, _err = run(AV, self.write("The nurse calls you.\nThe dose was changed.\n"))
        self.assertEqual(code, 1)
        self.assertIn(":2: [HIT:be/get/stay + participle] was changed", out)

    def test_markers_on_one_line_close_the_zone(self):
        text = "<!-- av:mention -->The dose was changed.<!-- /av:mention -->\nThe form was signed.\n"
        code, out, err = run(AV, self.write(text))
        self.assertEqual(code, 1)
        self.assertIn(":1: [MENTION:", out)
        self.assertIn(":2: [HIT:", out)
        self.assertIn("blocking=1 verbatim=0 mention=1", err)

    def test_strict_counts_mention_hits(self):
        text = "<!-- av:mention -->\nThe dose was changed.\n<!-- /av:mention -->\n"
        self.assertEqual(run(AV, self.write(text))[0], 0)
        self.assertEqual(run(AV, "--strict", self.write(text))[0], 1)

    def test_verbatim_zone_never_blocks_but_always_prints(self):
        text = "<!-- av:verbatim -->\nTHIS NOTICE DESCRIBES HOW INFORMATION MAY BE USED.\n<!-- /av:verbatim -->\n"
        code, out, err = run(AV, "--strict", self.write(text))
        self.assertEqual(code, 0)
        self.assertIn("[VERBATIM:", out)
        self.assertIn("verbatim=1", err)

    def test_ignore_markers_makes_every_hit_blocking(self):
        text = "<!-- av:verbatim -->\nThe form was signed.\n<!-- /av:verbatim -->\n"
        code, out, _err = run(AV, "--ignore-markers", self.write(text))
        self.assertEqual(code, 1)
        self.assertIn("[HIT:", out)

    def test_marker_that_never_closes_is_a_fault(self):
        code, out, err = run(AV, self.write("Text.\n<!-- av:verbatim -->\nThe form was signed.\n"))
        self.assertEqual(code, 1)
        self.assertIn("FAULT: the av:verbatim marker on line 2 never closes", out)
        self.assertIn("faults=1", err)

    def test_code_fence_that_never_closes_is_a_fault(self):
        code, out, _err = run(AV, self.write("Text.\n```\nThe form was signed.\n"))
        self.assertEqual(code, 1)
        self.assertIn("FAULT: the code fence on line 2 never closes", out)

    def test_passive_across_a_line_break(self):
        code, out, _err = run(AV, self.write("Each month the record was\nchanged without a note.\n"))
        self.assertEqual(code, 1)
        self.assertIn(":1: [HIT:be/get/stay + participle (across lines)] was changed", out)

    def test_a_blank_line_stops_the_join(self):
        _code, out, _err = run(AV, self.write("The record was\n\nchanged a lot.\n"))
        self.assertNotIn("across lines", out)

    def test_code_fence_is_skipped_unless_asked(self):
        text = "Text.\n```\nThe form was signed.\n```\n"
        self.assertEqual(run(AV, self.write(text))[0], 0)
        self.assertEqual(run(AV, "--include-code", self.write(text))[0], 1)

    def test_front_matter_is_skipped(self):
        text = "---\ndescription: The form was signed.\n---\nThe nurse calls you.\n"
        self.assertEqual(run(AV, self.write(text))[0], 0)

    def test_front_matter_that_never_closes_is_scanned(self):
        code, _out, err = run(AV, self.write("---\nThe form was signed.\n"))
        self.assertEqual(code, 1)
        self.assertIn("front matter that never closes", err)

    def test_missing_file_exits_2_without_a_traceback(self):
        code, _out, err = run(AV, os.path.join(self.folder, "absent.md"))
        self.assertEqual(code, 2)
        self.assertIn("ERROR: No such file or directory", err)
        self.assertNotIn("Traceback", err)

    def test_directory_exits_2(self):
        code, _out, err = run(AV, self.folder)
        self.assertEqual(code, 2)
        self.assertIn("is a directory", err)

    def test_binary_file_exits_2(self):
        self.assertEqual(run(AV, self.write("", raw=b"abc\x00def"))[0], 2)

    def test_invalid_utf8_is_scanned_with_a_note(self):
        code, _out, err = run(AV, self.write("", raw=b"The form was signed \xff.\n"))
        self.assertEqual(code, 1)
        self.assertIn("not valid UTF-8", err)

    def test_crlf_and_byte_order_mark(self):
        code, out, _err = run(AV, self.write("", raw=b"\xef\xbb\xbf---\r\nname: x\r\n---\r\nThe form was signed.\r\n"))
        self.assertEqual(code, 1)
        self.assertIn(":4: [HIT:", out)

    def test_standard_input(self):
        code, out, _err = run(AV, "-", stdin="The form was signed.\n")
        self.assertEqual(code, 1)
        self.assertIn("-:1: [HIT:", out)

    def test_one_unreadable_file_does_not_hide_hits_in_another(self):
        code, out, _err = run(AV, os.path.join(self.folder, "absent.md"), self.write("The form was signed.\n"))
        self.assertEqual(code, 2)
        self.assertIn("[HIT:", out)

    def test_pattern_set_matches_the_writing_standard(self):
        import re
        with open(os.path.join(SKILL, "references", "one-way-optimal-language.md"), encoding="utf-8") as handle:
            block = re.search(r"^P = \(r.*?^\]$", handle.read(), re.M | re.S).group(0)
        with open(AV, encoding="utf-8") as handle:
            self.assertIn(block, handle.read())


class WatchlistScannerTests(ScratchCase):
    def test_exit_0_with_hits_and_exit_1_with_fail(self):
        path = self.write("You should call the clinic.\n")
        code, out, err = run(WATCH, path)
        self.assertEqual(code, 0)
        self.assertIn("[R1/lexicon] should", out)
        self.assertIn("hits=1", err)
        self.assertEqual(run(WATCH, "--fail", path)[0], 1)

    def test_long_sentence_across_wrapped_lines(self):
        text = ("The nurse calls each patient who has a new prescription and who lives alone\n"
                "and asks the patient to read the label aloud and to say when the patient takes the dose.\n")
        _code, out, _err = run(WATCH, self.write(text))
        self.assertIn(":1: [S5 length", out)

    def test_limit_option(self):
        path = self.write("Take one tablet every morning with a full glass of water before you eat breakfast today.\n")
        self.assertNotIn("S5 length", run(WATCH, path)[1])
        self.assertIn("S5 length 16 > 15", run(WATCH, "--limit", "15", path)[1])
        self.assertEqual(run(WATCH, "--limit", "0", path)[0], 2)

    def test_table_cells_are_measured_separately(self):
        row = "| " + " | ".join(["Take one tablet each day now"] * 6) + " |\n"
        self.assertNotIn("S5 length", run(WATCH, self.write("| a | b | c | d | e | f |\n|---|---|---|---|---|---|\n" + row))[1])

    def test_urls_comments_and_inline_code_are_skipped(self):
        text = "See https://example.org/a/b for more. <!-- should --> Use `and/or` here.\n"
        _code, out, _err = run(WATCH, self.write(text))
        self.assertNotIn("R28 slash", out)
        self.assertNotIn("should", out)
        self.assertNotIn("and/or", out)
        self.assertIn("and/or", run(WATCH, "--include-code", self.write(text))[1])

    def test_dose_formats(self):
        _code, out, _err = run(WATCH, self.write("Give 5.0 mg QD, then .5 mg, then 10 U.\n"))
        for label in ("R14 trailing zero", "R6 Do Not Use: QD/QOD", "R14 missing leading zero", "R6 Do Not Use: U/IU"):
            self.assertIn(label, out)

    def test_one_space_after_a_sentence(self):
        _code, out, _err = run(WATCH, self.write("Call Dr. Lee today. Then rest.\n"))
        self.assertEqual(out.count("Typography: one space after sentence"), 1)

    def test_summary_and_missing_file(self):
        code, _out, err = run(WATCH, "--summary", self.write("You should rest. You should eat.\n"))
        self.assertEqual(code, 0)
        self.assertIn("2  R1/lexicon", err)
        code, _out, err = run(WATCH, os.path.join(self.folder, "absent.md"))
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)

    def test_standard_input(self):
        code, out, _err = run(WATCH, "-", stdin="You should rest.\n")
        self.assertEqual(code, 0)
        self.assertIn("-:1: [R1/lexicon] should", out)


class PackageTests(unittest.TestCase):
    def test_validator_passes(self):
        code, out, err = run(VALIDATOR)
        self.assertEqual(code, 0, out + err)
        self.assertIn("OK: package checks passed", out)

    def test_agents_match_the_build_tool(self):
        self.assertEqual(load(BUILD, "clo_build").agent_findings(), [])

    def test_no_agent_can_write_or_launch_agents(self):
        for name, text in load(BUILD, "clo_build").rendered_agents().items():
            tools_line = [line for line in text.split("\n") if line.startswith("tools: ")][0]
            for tool in ("Write", "Edit", "NotebookEdit", "Agent", "Task"):
                self.assertNotIn(tool, tools_line, name)

    def test_zips_are_current_and_deterministic(self):
        build = load(BUILD, "clo_build")
        self.assertEqual(build.zip_findings(), [])
        first, second = build.packages(), build.packages()
        self.assertEqual(first, second)
        for name, data in first.items():
            with open(os.path.join(HOME, "dist", name), "rb") as handle:
                self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), hashlib.sha256(data).hexdigest(), name)

    def test_zip_layout(self):
        build = load(BUILD, "clo_build")
        built = build.packages()
        with zipfile.ZipFile(io.BytesIO(built[build.SKILL_ZIP])) as archive:
            names = archive.namelist()
        self.assertIn(NAME + "/SKILL.md", names)
        self.assertEqual(len([n for n in names if n.endswith("SKILL.md")]), 1)
        with zipfile.ZipFile(io.BytesIO(built[build.PLUGIN_ZIP])) as archive:
            plugin_names = archive.namelist()
        for expected in (".claude-plugin/plugin.json", "skills/%s/SKILL.md" % NAME, "agents/rt-defender.md",
                         "commands/red-team.md", "commands/qc-review.md", "tools/validate_package.py"):
            self.assertIn(NAME + "/" + expected, plugin_names)
        for name in names + plugin_names:
            self.assertTrue(name.startswith(NAME + "/"), name)
            self.assertNotIn("__pycache__", name)
            self.assertNotIn("..", name.split("/"))

    def test_validator_catches_a_planted_defect(self):
        folder = tempfile.mkdtemp(prefix="clo-plant-")
        self.addCleanup(shutil.rmtree, folder, True)
        copy = os.path.join(folder, NAME)
        shutil.copytree(PLUGIN, copy, ignore=shutil.ignore_patterns("__pycache__"))
        validator = os.path.join(copy, "tools", "validate_package.py")
        self.assertEqual(run(validator)[0], 0)
        plants = (
            ("skills/%s/SKILL.md" % NAME, 'description: "Quality-control', "description: Quality: control", "front matter"),
            ("agents/rt-defender.md", "tools: Read, Grep, Glob, Bash", "tools: Read, Write", "read-only list"),
            ("agents/rt-defender.md", "- **D5 Forbidden defenses.**", "- **D5 Allowed defenses.**", "Defender rule"),
            ("skills/%s/references/one-way-optimal-language.md" % NAME, "One Way", "One  Way", "byte for byte"),
            ("skills/%s/scripts/av_scan.py" % NAME, "|shaken|", "|shakn|", "pattern set"),
            (".claude-plugin/plugin.json", '"version": "2.0.0"', '"version": "9.9.9"', "version"),
        )
        for relative, old, new, expected in plants:
            path = os.path.join(copy, relative)
            with open(path, encoding="utf-8") as handle:
                original = handle.read()
            self.assertIn(old, original, relative)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(original.replace(old, new, 1))
            code, out, _err = run(validator)
            self.assertEqual(code, 1, "the validator missed: %s in %s" % (new, relative))
            self.assertIn(expected, out)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(original)
        self.assertEqual(run(validator)[0], 0)

    def test_backup_of_the_original_uploads_is_intact(self):
        folder = os.path.join(HOME, "backup", "original-uploads")
        with open(os.path.join(folder, "SHA256SUMS"), encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            digest, name = line.split("  ")
            with open(os.path.join(folder, name), "rb") as handle:
                self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), digest, name)


if __name__ == "__main__":
    unittest.main()
