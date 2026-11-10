"""Tests for lib/ad_gates.py: tool log, trimmer, completion gate, provenance."""
import datetime
import importlib
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import ad_core  # noqa: E402
import ad_gates  # noqa: E402

FIXED_NOW = datetime.datetime(2030, 5, 2, 8, 30, 0, tzinfo=datetime.timezone.utc)

# Messages that declare completion. The gate must treat every one as a claim.
POSITIVE_CLAIMS = [
    "All tests pass.",
    "All tests are passing now.",
    "All of the tests passed.",
    "All unit tests pass and the linter is clean.",
    "The tests are passing.",
    "Tests are green.",
    "The tests now pass.",
    "Done.",
    "Done!",
    "Done - the migration ran cleanly.",
    "Done with the refactor.",
    "Fixed.",
    "Fixed the bug in the date parser.",
    "Fixed it.",
    "Completed the migration to the new API.",
    "Implemented the retry logic in client.py.",
    "Finished the cleanup.",
    "Resolved: the import cycle is gone.",
    "The feature is now implemented.",
    "The bug is fixed.",
    "The bug has been fixed.",
    "The issue has been resolved.",
    "The refactor is complete.",
    "The work is done.",
    "The migration is now complete and verified.",
    "Everything is working.",
    "Everything works.",
    "It works now.",
    "The build now works.",
    "The endpoint works again.",
    "It's fixed.",
    "That's done.",
    "I've fixed the issue.",
    "I have implemented the feature.",
    "I've now completed the refactoring.",
    "I fixed the failing test.",
    "We have resolved the conflict.",
    "I successfully migrated the database.",
    "Successfully deployed the service.",
    "The branch is ready for review.",
    "This is ready to merge.",
    "Task complete.",
    "The task is finished.",
    "All done.",
    "All set.",
    "After the fix, all tests pass.",
    "## Summary\n\nI've completed the refactoring. Here's a summary of the changes.",
    "- Fixed the off-by-one error\n- Added a regression test",
    "**Done.** The parser handles empty input.",
    "The login flow is working and the session bug has been fixed.",
]

# Messages that use the same words without declaring completion.
NEGATIVE_CLAIMS = [
    "Here is the complete list of files.",
    "Once this is done we can merge.",
    "Not done yet.",
    "This is to be implemented in the next step.",
    "Is it done?",
    "Are all tests passing?",
    "Did you say the bug is fixed?",
    "I will fix the bug next.",
    "The plan: fix the parser, then run the tests.",
    "Fixed costs are high this quarter.",
    "If the tests pass, we merge.",
    "This should be fixed now.",
    "The tests are not passing.",
    "The tests aren't passing yet.",
    "The work isn't done.",
    "Nothing is fixed yet.",
    "When this is complete, notify the team.",
    "Until the migration is complete, keep the old table.",
    "Unless the build is green, do not merge.",
    "It would be done faster with a cache.",
    "We need to make sure all tests pass before merging.",
    "To be done: update the docs.",
    "TODO: mark the task as complete.",
    "I am going to check whether the bug is fixed.",
    "Let me verify that the tests are passing.",
    "Let me check if everything works.",
    "The user said the feature is done, and the code disagrees.",
    "The ticket claims the bug is fixed.",
    "Definition of done: the tests are green.",
    "Acceptance criteria: all tests pass.",
    "I could not confirm that the fix is complete.",
    "I cannot say the bug is fixed.",
    "The complete output is below.",
    "A completed form is required.",
    "Use the fixed-width font.",
    "Completed tasks are listed in the changelog.",
    "Implemented interfaces must be documented.",
    "The function returns the resolved path.",
    "The working directory is /tmp/build.",
    "Finished goods inventory rose.",
    "What does done mean for this task?",
    "How do we know when it is finished?",
    "Should I mark it as resolved?",
    "I plan to have it implemented by Friday.",
    "The next step will be complete after the review.",
    "Step 2 of 5: run the tests.",
    "Running the tests now.",
    "I am still working on the fix.",
    "The first attempt failed; trying a different approach.",
    "Here are three options for the design.",
    "The test suite has 40 tests.",
    "I read the file and found two problems.",
    "No changes were made.",
    "The parser does not handle empty input.",
    "It may be fixed by the upstream patch.",
    "It might be done by tomorrow.",
    "This needs to be fixed before release.",
    "I was not able to get the tests passing.",
    "Almost done: one test still fails.",
    "The fix is partially implemented.",
    "Status: partial. Two of five endpoints are migrated.",
    "The log says:\n```\nAll tests passed.\n```\nI have not checked it myself yet.",
    "The CI badge shows `tests passing` on the main branch page.",
    "> All done, fixed.\n\nThat message came from the previous run.",
    "",
    "   ",
]

EVIDENCE = (
    "Acceptance: unit tests green\n"
    "Command: pytest tests/unit -q\n"
    "Output: 12 passed in 0.31s\n"
    "Diff: src/parser.py, tests/unit/test_parser.py\n"
    "Not verified: Windows paths\n"
)


class GatesCase(unittest.TestCase):
    """Base class: temp directory, own AGENT_STATE_DIR, fixed clock, modules reloaded per class."""

    @classmethod
    def setUpClass(cls):
        importlib.reload(ad_core)
        importlib.reload(ad_gates)

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="ad-gates-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = dict(os.environ)
        self.addCleanup(self._restore_env, saved)
        for name in list(os.environ):
            if name.startswith("AD_") or name in ("AGENT_STATE_DIR", "CLAUDE_PROJECT_DIR"):
                del os.environ[name]
        self.state = os.path.join(self.tmp, "state")
        os.environ["AGENT_STATE_DIR"] = self.state
        ad_core.set_start_dir(self.tmp)
        self.addCleanup(ad_core.set_start_dir, None)
        original_clock = ad_core.time_now
        ad_core.time_now = lambda: FIXED_NOW
        self.addCleanup(setattr, ad_core, "time_now", original_clock)

    @staticmethod
    def _restore_env(saved):
        os.environ.clear()
        os.environ.update(saved)

    def bash_post(self, command, stdout="", session="abc123", tool_use_id="toolu_01"):
        """A PostToolUse input for Bash with the documented structured tool_response."""
        return {
            "session_id": session,
            "prompt_id": "550e8400-e29b-41d4-a716-446655440000",
            "transcript_path": "/home/user/.claude/projects/x/transcript.jsonl",
            "cwd": self.tmp,
            "permission_mode": "default",
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command, "description": "Run /etc/secret thing"},
            "tool_response": {"stdout": stdout, "stderr": "", "interrupted": False, "isImage": False},
            "tool_use_id": tool_use_id,
            "duration_ms": 12,
        }

    def bash_failure(self, command, error, session="abc123", tool_use_id="toolu_02"):
        """A PostToolUseFailure input shaped like the documented example."""
        return {
            "session_id": session,
            "transcript_path": "/home/user/.claude/projects/x/transcript.jsonl",
            "cwd": self.tmp,
            "permission_mode": "default",
            "hook_event_name": "PostToolUseFailure",
            "tool_name": "Bash",
            "tool_input": {"command": command, "description": "Run test suite"},
            "tool_use_id": tool_use_id,
            "error": error,
            "is_interrupt": False,
            "duration_ms": 4187,
        }


class ToolLogTests(GatesCase):
    def test_record_shape(self):
        record = ad_gates.log_tool(self.bash_post("npm   test\n  --silent"))
        self.assertEqual(record, {
            "ts": "2030-05-02T08:30:00+00:00",
            "session": "abc123",
            "prompt": "550e8400-e29b-41d4-a716-446655440000",
            "tool": "Bash",
            "cmd": "npm test --silent",
            "ok": True,
            "exit": 0,
            "id": "toolu_01",
        })
        self.assertEqual(ad_gates.tool_log(), [record])

    def test_output_text_never_invents_a_failure(self):
        # GS-08 / HC-07: stdout that contains "exit 1" used to be logged as exit code 1.
        record = ad_gates.log_tool(self.bash_post("grep -rn exit src", stdout="src/a.sh:3: exit 1\nexit code 2"))
        self.assertTrue(record["ok"])
        self.assertEqual(record["exit"], 0)

    def test_failure_exit_code_comes_from_the_first_line_only(self):
        record = ad_gates.log_tool(
            self.bash_failure("npm test", "Exit code 1\nError: Cannot find module 'express'"), failed=True)
        self.assertEqual((record["ok"], record["exit"]), (False, 1))
        record = ad_gates.log_tool(
            self.bash_failure("make", "Exit code 127\nmake: not found\nExit code 3", tool_use_id="t3"), failed=True)
        self.assertEqual(record["exit"], 127)
        record = ad_gates.log_tool(
            self.bash_failure("x", "spawn failed\nExit code 9", tool_use_id="t4"), failed=True)
        self.assertEqual((record["ok"], record["exit"]), (False, None))

    def test_interrupt_is_marked(self):
        inp = self.bash_failure("sleep 100", "Request interrupted")
        inp["is_interrupt"] = True
        self.assertTrue(ad_gates.log_tool(inp, failed=True)["interrupt"])

    def test_command_is_redacted_and_cut(self):
        record = ad_gates.log_tool(self.bash_post("curl -H 'Authorization: Bearer abcdef123456' https://x"))
        self.assertNotIn("abcdef123456", record["cmd"])
        record = ad_gates.log_tool(self.bash_post("echo " + "y" * 2000, tool_use_id="t2"))
        self.assertEqual(len(record["cmd"]), 500)

    def test_cmd_field_per_tool_and_never_content_or_description(self):
        cases = [
            ("Write", {"file_path": "/p/a.txt", "content": "rm -rf / # content"}, "/p/a.txt"),
            ("Edit", {"file_path": "/p/b.txt", "old_string": "x", "new_string": "/etc/passwd"}, "/p/b.txt"),
            ("NotebookEdit", {"notebook_path": "/p/n.ipynb", "new_source": "x"}, "/p/n.ipynb"),
            ("WebFetch", {"url": "https://example.com/api", "prompt": "Extract"}, "https://example.com/api"),
            ("Grep", {"pattern": "TODO.*fix", "path": "/p/src"}, "TODO.*fix"),
            ("Glob", {"pattern": "**/*.ts", "path": "/p"}, "**/*.ts"),
            ("WebSearch", {"query": "react hooks"}, "react hooks"),
            ("mcp__memory__create", {"name": "x"}, ""),
        ]
        for index, (tool, tool_input, expected) in enumerate(cases):
            record = ad_gates.log_tool({"tool_name": tool, "tool_input": tool_input, "session_id": "s",
                                        "tool_use_id": "id%d" % index})
            self.assertEqual(record["cmd"], expected, tool)
            self.assertIsNone(record["exit"], tool)
        for record in ad_gates.tool_log():
            self.assertNotIn("secret", record["cmd"])

    def test_malformed_input_does_not_raise(self):
        for inp in ({}, {"tool_name": 5, "tool_input": "text"}, {"tool_name": "Bash", "tool_input": {"command": 7}}):
            self.assertIsNotNone(ad_gates.log_tool(inp))

    def test_unwritable_state_returns_none(self):
        blocker = os.path.join(self.tmp, "file")
        with open(blocker, "w") as handle:
            handle.write("x")
        os.environ["AGENT_STATE_DIR"] = os.path.join(blocker, "state")
        self.assertIsNone(ad_gates.log_tool(self.bash_post("ls")))

    def test_session_filter_and_duplicate_registration(self):
        # HC-18: a hook registered twice logs one call twice; readers collapse by tool-use id.
        ad_gates.log_tool(self.bash_post("ls", session="A", tool_use_id="t1"))
        ad_gates.log_tool(self.bash_post("ls", session="A", tool_use_id="t1"))
        ad_gates.log_tool(self.bash_post("pwd", session="B", tool_use_id="t2"))
        self.assertEqual(len(ad_gates.tool_log()), 2)
        self.assertEqual([record["cmd"] for record in ad_gates.tool_log("A")], ["ls"])
        self.assertEqual(ad_gates.tool_log("nobody"), [])

    def test_bad_log_lines_are_skipped(self):
        # GS-20
        ad_gates.log_tool(self.bash_post("ls"))
        ad_core.append_line("toollog.jsonl", '{"ts": "2030", "cmd": "cut sho')
        ad_core.append_line("toollog.jsonl", "[]")
        self.assertEqual(len(ad_gates.tool_log()), 1)

    def test_log_rotates(self):
        original = (ad_gates.TOOL_LOG_MAX_BYTES, ad_gates.TOOL_LOG_KEEP_LINES)
        ad_gates.TOOL_LOG_MAX_BYTES, ad_gates.TOOL_LOG_KEEP_LINES = 2000, 5
        self.addCleanup(setattr, ad_gates, "TOOL_LOG_MAX_BYTES", original[0])
        self.addCleanup(setattr, ad_gates, "TOOL_LOG_KEEP_LINES", original[1])
        for index in range(40):
            ad_gates.log_tool(self.bash_post("echo %d" % index, tool_use_id="t%d" % index))
        records = ad_gates.tool_log()
        self.assertLessEqual(len(records), 20)
        self.assertEqual(records[-1]["cmd"], "echo 39")


class TrimTests(GatesCase):
    def assert_bounded(self, text, limit):
        """The view is at most ``limit`` characters plus one final marker line."""
        view, kind = ad_gates.trim_output(text, limit)
        body, _newline, marker = view.rpartition("\n")
        self.assertLessEqual(len(body), limit, kind)
        self.assertTrue(marker.startswith("[trimmed " + kind), marker)
        self.assertNotIn("\n", marker)
        self.assertNotRegex(view, r"-\d+ lines")
        self.assertLess(len(view), len(text), kind)
        return view, kind

    def test_short_text_passes_through(self):
        self.assertEqual(ad_gates.trim_output("short", 100), ("short", "passthrough"))

    def test_default_limit_comes_from_environment_and_survives_bad_values(self):
        os.environ["AD_TRIM_CHARS"] = "6k"
        self.assertEqual(ad_gates.trim_limit(), 6000)
        os.environ["AD_TRIM_CHARS"] = "1000"
        self.assertEqual(ad_gates.trim_output("z" * 900)[1], "passthrough")
        self.assertNotEqual(ad_gates.trim_output("z\n" * 900)[1], "passthrough")

    def test_few_very_long_lines(self):
        # GS-17: five lines of 3,000 characters used to give "-95 lines omitted" and a longer view.
        view, kind = self.assert_bounded("\n".join("x" * 3000 for _ in range(5)), 6000)
        self.assertEqual(kind, "head-tail")
        self.assertIn("chars]", view)

    def test_one_huge_line(self):
        self.assert_bounded("y" * 1000000, 6000)

    def test_head_tail_keeps_both_ends_and_error_lines(self):
        lines = ["line %05d ok" % index for index in range(4000)]
        lines[2000] = "line 02000 ERROR disk full"
        view, kind = self.assert_bounded("\n".join(lines), 3000)
        self.assertEqual(kind, "head-tail")
        self.assertIn("line 00000 ok", view)
        self.assertIn("line 03999 ok", view)
        self.assertIn("ERROR disk full", view)
        self.assertRegex(view, r"\[\d+ lines omitted here\]")

    def test_timestamped_log_is_not_mistaken_for_grep_output(self):
        # GS-30-V: ISO-stamped logs were reduced to a list of minute stamps and lost the CRITICAL line.
        lines = ["2026-11-10T17:%02d:%02d INFO request %d handled" % (index // 60, index % 60, index)
                 for index in range(300)]
        lines.append("2026-11-10T17:05:01 CRITICAL database connection lost: password authentication failed")
        lines.extend("10:00:%02d worker started job %d" % (index % 60, index) for index in range(300))
        view, kind = self.assert_bounded("\n".join(lines), 4000)
        self.assertEqual(kind, "head-tail")
        self.assertIn("CRITICAL database connection lost", view)

    def test_grep_output_keeps_the_matched_text(self):
        # GS-16: mypy-style lines were reduced to file:line and the diagnostics were gone.
        lines = ["src/mod%d.py:%d: error: Incompatible types in assignment [assignment]" % (index % 7, index)
                 for index in range(1, 400)]
        view, kind = self.assert_bounded("\n".join(lines), 3000)
        self.assertEqual(kind, "grep")
        self.assertIn("src/mod1.py:1: error: Incompatible types in assignment", view)
        self.assertIn("7 files have hits", view)

    def test_test_output_keeps_failures_and_summary(self):
        lines = ["tests/test_a.py::test_%d PASSED" % index for index in range(600)]
        lines.insert(300, "tests/test_a.py::test_bad FAILED")
        lines.append("E   AssertionError: expected 3, got 4")
        lines.append("=========== 1 failed, 600 passed in 2.31s ===========")
        view, kind = self.assert_bounded("\n".join(lines), 2000)
        self.assertEqual(kind, "test-failures")
        self.assertIn("test_bad FAILED", view)
        self.assertIn("AssertionError: expected 3, got 4", view)
        self.assertIn("1 failed, 600 passed", view)

    def test_json_keeps_structure_and_sample_values(self):
        # GS-34-V / GS-16: the old view showed only type names such as "str".
        data = [{"id": index, "error": "disk full on node %d" % index} for index in range(400)]
        view, kind = self.assert_bounded(json.dumps(data), 2000)
        self.assertEqual(kind, "json")
        self.assertIn("disk full on node 0", view)
        self.assertIn("more items", view)
        self.assertNotIn('"str"', view)
        self.assertNotIn("stored", view)

    def test_json_that_cannot_fit_falls_back(self):
        data = {"key%04d" % index: "v" * 50 for index in range(3000)}
        view, kind = self.assert_bounded(json.dumps(data, indent=1), 500)
        self.assertIn(kind, ("json", "head-tail"))

    def test_many_shapes_stay_bounded(self):
        samples = [
            "\n" * 20000,
            "a b c\n" * 5000,
            "\n".join("%d\t%s" % (index, "w" * (index % 700)) for index in range(900)),
            "{" + "x" * 9000,
            "FAILED\n" * 3000 + "3000 failed",
            "é中文 " * 4000,
        ]
        for text in samples:
            for limit in (400, 1000, 6000):
                if len(text) > limit:
                    self.assert_bounded(text, limit)


class StoredOutputTests(GatesCase):
    def test_store_and_cap(self):
        original = ad_gates.MAX_STORED_OUTPUTS
        ad_gates.MAX_STORED_OUTPUTS = 3
        self.addCleanup(setattr, ad_gates, "MAX_STORED_OUTPUTS", original)
        paths = []
        for index in range(6):
            path = ad_gates.store_full_output("output number %d\nsecond line\n" % index)
            os.utime(path, (1000 + index, 1000 + index))
            paths.append(path)
        remaining = sorted(os.listdir(os.path.join(self.state, "outputs")))
        self.assertEqual(len(remaining), 3)
        self.assertTrue(os.path.exists(paths[-1]))
        self.assertFalse(os.path.exists(paths[0]))
        with open(paths[-1], encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "output number 5\nsecond line\n")

    def test_same_text_is_stored_once(self):
        self.assertEqual(ad_gates.store_full_output("same"), ad_gates.store_full_output("same"))
        self.assertEqual(len(os.listdir(os.path.join(self.state, "outputs"))), 1)

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symbolic links")
    def test_linked_outputs_directory_is_refused(self):
        # GS-32-V: tool output must not be copied into a directory the repository chose.
        ad_core.state_dir()
        victim = os.path.join(self.tmp, "victim")
        os.mkdir(victim)
        os.symlink(victim, os.path.join(self.state, "outputs"))
        with self.assertRaises(OSError):
            ad_gates.store_full_output("secret output")
        self.assertEqual(os.listdir(victim), [])


class TrimmedToolOutputTests(GatesCase):
    def long_stdout(self):
        return "\n".join("tests/test_a.py::test_%d PASSED" % index for index in range(300)) + \
            "\ntests/test_a.py::test_x FAILED\n===== 1 failed, 300 passed ====="

    def test_off_by_default(self):
        self.assertIsNone(ad_gates.trimmed_tool_output(self.bash_post("pytest", self.long_stdout())))
        self.assertFalse(os.path.exists(self.state))

    def test_replacement_keeps_the_bash_output_shape(self):
        # GS-03 / HC-08: the old hook serialized the object and showed {"stdout": "str", ...}.
        os.environ["AD_TRIM_HOOK"] = "1"
        os.environ["AD_TRIM_CHARS"] = "2000"
        inp = self.bash_post("pytest", self.long_stdout())
        inp["tool_response"]["stderr"] = "warning: x"
        replacement = ad_gates.trimmed_tool_output(inp)
        self.assertEqual(sorted(replacement), ["interrupted", "isImage", "stderr", "stdout"])
        self.assertEqual(replacement["stderr"], "warning: x")
        self.assertIs(replacement["interrupted"], False)
        self.assertIs(replacement["isImage"], False)
        self.assertLess(len(replacement["stdout"]), len(self.long_stdout()))
        self.assertIn("test_x FAILED", replacement["stdout"])
        stored = os.listdir(os.path.join(self.state, "outputs"))
        self.assertEqual(len(stored), 1)
        self.assertIn(os.path.join(self.state, "outputs", stored[0]), replacement["stdout"])
        with open(os.path.join(self.state, "outputs", stored[0]), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), self.long_stdout())
        self.assertEqual(inp["tool_response"]["stdout"], self.long_stdout())

    def test_only_bash_objects_are_replaced(self):
        os.environ["AD_TRIM_HOOK"] = "1"
        os.environ["AD_TRIM_CHARS"] = "400"
        inp = self.bash_post("pytest", self.long_stdout())
        self.assertIsNone(ad_gates.trimmed_tool_output(dict(inp, tool_name="Grep")))
        self.assertIsNone(ad_gates.trimmed_tool_output(dict(inp, tool_response=self.long_stdout())))
        self.assertIsNone(ad_gates.trimmed_tool_output(dict(inp, tool_response={"stdout": "short"})))
        self.assertIsNone(ad_gates.trimmed_tool_output(dict(inp, tool_response={"stdout": None})))


class ClaimTests(GatesCase):
    def test_corpus_sizes(self):
        self.assertGreaterEqual(len(POSITIVE_CLAIMS), 40)
        self.assertGreaterEqual(len(NEGATIVE_CLAIMS), 60)

    def test_positive_corpus(self):
        missed = [message for message in POSITIVE_CLAIMS if not ad_gates.claims_completion(message)]
        self.assertEqual(missed, [])

    def test_negative_corpus(self):
        # GS-12: ordinary prose with "done" or "complete" used to trigger the gate.
        wrong = [message for message in NEGATIVE_CLAIMS if ad_gates.claims_completion(message)]
        self.assertEqual(wrong, [])

    def test_non_string_input(self):
        self.assertFalse(ad_gates.claims_completion(None))
        self.assertFalse(ad_gates.claims_completion(42))


class EvidenceBlockTests(GatesCase):
    def test_plain_block(self):
        self.assertEqual(ad_gates.find_evidence_block("Done.\n" + EVIDENCE), {
            "acceptance": "unit tests green",
            "command": "pytest tests/unit -q",
            "output": "12 passed in 0.31s",
            "diff": "src/parser.py, tests/unit/test_parser.py",
            "not_verified": "Windows paths",
        })

    def test_markdown_variants_any_order_any_case(self):
        # GS-11: bold labels and bullets used to be rejected.
        message = (
            "- **Not-verified:** Safari\n"
            "* `DIFF`: a.py\n"
            "> output: `5 passed`\n"
            "1. **Commands run**: `pytest -q`\n"
            "## acceptance criteria: green\n")
        block = ad_gates.find_evidence_block(message)
        self.assertEqual(block["not_verified"], "Safari")
        self.assertEqual(block["diff"], "a.py")
        self.assertEqual(block["output"], "`5 passed`")
        self.assertEqual(block["command"], "`pytest -q`")
        self.assertEqual(block["acceptance"], "green")

    def test_unverified_label_and_fullwidth_colon(self):
        message = EVIDENCE.replace("Not verified:", "Unverified：")
        self.assertEqual(ad_gates.find_evidence_block(message)["not_verified"], "Windows paths")

    def test_value_on_following_lines(self):
        message = ("Acceptance: green\nCommand: pytest -q\nOutput:\n```\n5 passed in 0.1s\nOK\n```\n"
                   "Diff: a.py\nNot verified: none\n")
        self.assertEqual(ad_gates.find_evidence_block(message)["output"], "5 passed in 0.1s\nOK")

    def test_missing_label_gives_none(self):
        for label in ("Acceptance", "Command", "Output", "Diff", "Not verified"):
            lines = [line for line in EVIDENCE.splitlines() if not line.startswith(label + ":")]
            self.assertIsNone(ad_gates.find_evidence_block("\n".join(lines)), label)
        self.assertIsNone(ad_gates.find_evidence_block(None))
        self.assertIsNone(ad_gates.find_evidence_block("The output: fine. The diff: small."))

    def test_many_blank_lines_are_fast(self):
        # GS-11: thousands of blank lines used to take seconds.
        started = time.perf_counter()
        ad_gates.find_evidence_block("done\n" + "\n" * 20000 + "x")
        ad_gates.claims_completion("done\n" + "\n" * 20000 + "x")
        self.assertLess(time.perf_counter() - started, 2.0)


class CompletionGateTests(GatesCase):
    def log(self, command, session="S1", tool="Bash", index=[0]):
        index[0] += 1
        inp = self.bash_post(command, session=session, tool_use_id="g%d" % index[0])
        inp["tool_name"] = tool
        if tool != "Bash":
            inp["tool_input"] = {"pattern": command, "path": command}
        return ad_gates.log_tool(inp)

    def test_no_claim_passes(self):
        self.assertIsNone(ad_gates.completion_gate_decide("Here is the plan for tomorrow."))
        self.assertIsNone(ad_gates.completion_gate_decide(""))

    def test_claim_without_block_is_blocked_with_the_template(self):
        reason = ad_gates.completion_gate_decide("All done, fixed.")
        for label in ("Acceptance:", "Command:", "Output:", "Diff:", "Not verified:"):
            self.assertIn(label, reason)
        self.assertIn("prompts once", reason)

    def test_claim_with_block_passes_when_nothing_is_logged(self):
        self.assertIsNone(ad_gates.completion_gate_decide("Done.\n" + EVIDENCE))
        self.assertFalse(os.path.exists(self.state))

    def test_bare_paraphrase_output_is_blocked(self):
        for verdict in ("passed", "OK", "Success.", "it worked", "works", "fine"):
            message = "Done.\n" + EVIDENCE.replace("12 passed in 0.31s", verdict)
            reason = ad_gates.completion_gate_decide(message)
            self.assertIsNotNone(reason, verdict)
            self.assertIn("Output:", reason)

    def test_quoted_short_output_passes(self):
        # GS-11: real output such as unittest's "OK" must be quotable.
        message = "Done.\n" + EVIDENCE.replace("12 passed in 0.31s", "`OK`")
        self.assertIsNone(ad_gates.completion_gate_decide(message))

    def test_placeholder_block_is_blocked(self):
        # GS-11: the pasted template used to pass.
        message = "Done.\n" + ad_gates.EVIDENCE_TEMPLATE
        self.assertIn("no value", ad_gates.completion_gate_decide(message))
        message = "Done.\n" + EVIDENCE.replace("src/parser.py, tests/unit/test_parser.py", "")
        self.assertIn("`Diff:`", ad_gates.completion_gate_decide(message))

    def test_cited_command_must_be_in_the_log(self):
        # HC-15 / GS-07
        self.log("git status")
        reason = ad_gates.completion_gate_decide("Done.\n" + EVIDENCE, session="S1")
        self.assertIn("pytest tests/unit -q", reason)
        self.assertIn("1 shell commands", reason)
        self.log("cd /repo && pytest   tests/unit -q 2>&1 | tail -5")
        self.assertIsNone(ad_gates.completion_gate_decide("Done.\n" + EVIDENCE, session="S1"))

    def test_non_shell_records_do_not_satisfy_the_check(self):
        # GS-07: a Grep whose path was "src" used to satisfy `pytest src/tests -q`.
        self.log("ls")
        self.log("pytest tests/unit -q", tool="Grep")
        self.assertIsNotNone(ad_gates.completion_gate_decide("Done.\n" + EVIDENCE, session="S1"))

    def test_session_scope(self):
        self.log("pytest tests/unit -q", session="OTHER")
        self.log("ls", session="S1")
        self.assertIsNotNone(ad_gates.completion_gate_decide("Done.\n" + EVIDENCE, session="S1"))
        self.assertIsNone(ad_gates.completion_gate_decide("Done.\n" + EVIDENCE, session=None))
        self.assertIsNone(ad_gates.completion_gate_decide("Done.\n" + EVIDENCE, session="EMPTY"))

    def test_command_none_skips_the_log_check(self):
        self.log("ls")
        for value in ("none", "N/A", "not run", "-", "`none`"):
            message = "Done.\n" + EVIDENCE.replace("pytest tests/unit -q", value)
            self.assertIsNone(ad_gates.completion_gate_decide(message, session="S1"), value)

    def test_short_command_must_match_exactly(self):
        self.log("ls -la")
        message = "Done.\n" + EVIDENCE.replace("pytest tests/unit -q", "ls")
        self.assertIsNotNone(ad_gates.completion_gate_decide(message, session="S1"))
        self.log("ls")
        self.assertIsNone(ad_gates.completion_gate_decide(message, session="S1"))

    def test_backticks_prompt_and_one_of_several_commands(self):
        self.log("npm run test:e2e -- --headless=false")
        message = "Done.\n" + EVIDENCE.replace(
            "pytest tests/unit -q", "`$ npm run test:e2e -- --headless=false` then `npm run lint`")
        self.assertIsNone(ad_gates.completion_gate_decide(message, session="S1"))

    def test_redacted_command_still_matches(self):
        self.log("curl -H 'Authorization: Bearer abcdef123456' https://api.example.com/health")
        message = "Done.\n" + EVIDENCE.replace(
            "pytest tests/unit -q", "curl -H 'Authorization: Bearer abcdef123456' https://api.example.com/health")
        self.assertIsNone(ad_gates.completion_gate_decide(message, session="S1"))

    def test_lenient_skips_the_log_check(self):
        self.log("git status")
        self.assertIsNone(ad_gates.completion_gate_decide("Done.\n" + EVIDENCE, session="S1", strict=False))

    def test_status_partial_with_valid_block_passes(self):
        message = "Status: partial\nI fixed 2 of 5 endpoints.\n" + EVIDENCE.replace(
            "pytest tests/unit -q", "none")
        self.assertIsNone(ad_gates.completion_gate_decide(message))

    def test_gate_off(self):
        os.environ["AD_GATE"] = "off"
        self.assertIsNone(ad_gates.completion_gate_decide("All done, fixed."))


class LastAssistantTextTests(GatesCase):
    def test_field_order(self):
        self.assertEqual(ad_gates.last_assistant_text(
            {"last_assistant_message": "from host", "last_message": "legacy"}), "from host")
        self.assertEqual(ad_gates.last_assistant_text({"last_message": "legacy"}), "legacy")
        self.assertEqual(ad_gates.last_assistant_text({}), "")
        self.assertEqual(ad_gates.last_assistant_text({"last_assistant_message": 5}), "")

    def test_transcript_fallback(self):
        path = os.path.join(self.tmp, "transcript.jsonl")
        rows = [
            {"type": "user", "message": {"role": "user", "content": "hi"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "first answer"}]}},
            "not json at all",
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash"}, {"type": "text", "text": "All done."}]}},
            {"type": "user", "message": {"role": "user", "content": "thanks"}},
        ]
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write((row if isinstance(row, str) else json.dumps(row)) + "\n")
        self.assertEqual(ad_gates.last_assistant_text({"transcript_path": path}), "All done.")
        self.assertEqual(ad_gates.last_assistant_text({"transcript_path": path + ".missing"}), "")


class ProvenanceTests(GatesCase):
    def test_add_validates(self):
        with self.assertRaises(ValueError):
            ad_gates.provenance_add("Intro", "a.md", confidence="certain")
        with self.assertRaises(ValueError):
            ad_gates.provenance_add("", "a.md")
        self.assertIn("Intro", ad_gates.provenance_add("Intro", "a.md", "the quote", "established"))

    def test_show_table_is_safe(self):
        self.assertEqual(ad_gates.provenance_show(), "(no provenance recorded)")
        ad_gates.provenance_add("Costs | 2030", "report.pdf p.4", "Revenue rose 12%\n| forged | row |", "probable")
        ad_gates.provenance_add("Other", "b.md")
        table = ad_gates.provenance_show()
        self.assertEqual(len(table.splitlines()), 4)
        self.assertIn("Costs \\| 2030", table)
        self.assertEqual(len(ad_gates.provenance_show("costs | 2030").splitlines()), 3)
        self.assertEqual(ad_gates.provenance_show("missing"), "(no provenance recorded)")

    def test_audit_headings(self):
        # GS-29: a comment inside a fence and a trailing ## used to be reported as sections.
        document = os.path.join(self.tmp, "doc.md")
        with open(document, "w", encoding="utf-8") as handle:
            handle.write("# Title\n\n```sh\n# comment in code\n```\n\n## [S1] Findings ##\n\n"
                         "### Sub Section\n\n##### level five\n\n~~~\n## also code\n~~~\n#NoSpace\n")
        text, code = ad_gates.provenance_audit(document)
        self.assertEqual(code, 1)
        self.assertEqual(text.splitlines(), ["3 of 3 sections have no provenance row:",
                                             "- Title", "- [S1] Findings", "- Sub Section"])
        ad_gates.provenance_add("title", "a.md")
        ad_gates.provenance_add("Findings", "b.md")
        ad_gates.provenance_add("## sub   section", "c.md")
        self.assertEqual(ad_gates.provenance_audit(document), ("all 3 sections have a provenance row", 0))

    def test_audit_survives_bad_rows_and_empty_documents(self):
        # GS-20: one bad JSONL line used to crash the audit.
        ad_gates.provenance_add("Title", "a.md")
        ad_core.append_line("provenance.jsonl", "{broken")
        ad_core.append_line("provenance.jsonl", '{"no_section": 1}')
        document = os.path.join(self.tmp, "doc.md")
        with open(document, "w", encoding="utf-8") as handle:
            handle.write("# Title\n")
        self.assertEqual(ad_gates.provenance_audit(document)[1], 0)
        with open(document, "w", encoding="utf-8") as handle:
            handle.write("no headings here\n")
        self.assertEqual(ad_gates.provenance_audit(document)[1], 0)
        with self.assertRaises(OSError):
            ad_gates.provenance_audit(document + ".missing")


if __name__ == "__main__":
    unittest.main()
