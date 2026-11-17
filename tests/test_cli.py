"""Tests for lib/ad.py as a command line: exit codes, no tracebacks, every sub-command wired.

Every test runs a copy of ``lib/`` as a subprocess from a temp directory, so
the suite also proves that the CLI works from any working directory and
leaves no byte-code behind.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(REPO, "lib")
GUARD_MODULES = ("ad_shell.py", "ad_guards.py", "ad_rules.py")
HAVE_GUARDS = all(os.path.isfile(os.path.join(LIB, name)) for name in GUARD_MODULES)
NEEDS_GUARDS = "lib/ad_shell.py, lib/ad_guards.py or lib/ad_rules.py is not present yet"

EVIDENCE = ("Acceptance: unit tests green\nCommand: pytest tests/unit -q\nOutput: 12 passed in 0.31s\n"
            "Diff: src/parser.py\nNot verified: Windows paths\n")


class CliCase(unittest.TestCase):
    """Base class: a copy of lib/ per class, a temp project and state directory per test."""

    @classmethod
    def setUpClass(cls):
        cls.class_tmp = os.path.realpath(tempfile.mkdtemp(prefix="ad-cli-lib-"))
        cls.lib = os.path.join(cls.class_tmp, "scripts")
        os.mkdir(cls.lib)
        for name in os.listdir(LIB):
            if name.endswith(".py"):
                shutil.copy(os.path.join(LIB, name), os.path.join(cls.lib, name))
        cls.ad = os.path.join(cls.lib, "ad.py")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.class_tmp, True)

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="ad-cli-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project = os.path.join(self.tmp, "project")
        os.mkdir(self.project)
        self.state = os.path.join(self.tmp, "state")
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("AD_") and key not in ("AGENT_STATE_DIR", "CLAUDE_PROJECT_DIR",
                                                                 "PYTHONIOENCODING", "PYTHONUTF8")}
        self.env["AGENT_STATE_DIR"] = self.state
        self.env["HOME"] = self.tmp

    def run_ad(self, *args, **options):
        """Run ad.py; return (exit code, stdout, stderr)."""
        env = dict(self.env)
        env.update(options.get("env") or {})
        stdin = options.get("stdin")
        completed = subprocess.run(
            [sys.executable, self.ad] + list(args),
            input=(stdin if stdin is not None else "").encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=options.get("cwd") or self.project, env=env, timeout=60)
        return (completed.returncode, completed.stdout.decode("utf-8", "replace"),
                completed.stderr.decode("utf-8", "replace"))

    def ok(self, *args, **options):
        code, out, err = self.run_ad(*args, **options)
        self.assertEqual(code, 0, "%r failed: %s %s" % (args, out, err))
        self.assertNotIn("Traceback", err)
        return out

    def write(self, relative, text):
        path = os.path.join(self.project, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path


class BasicsTests(CliCase):
    def test_version(self):
        self.assertEqual(self.ok("version"), "agent-discipline 2.1.0\n")

    def test_usage_errors_exit_2_without_traceback(self):
        for args in ([], ["bogus"], ["manifest"], ["manifest", "check"], ["ledger", "add"],
                     ["ledger", "add", "GRANT"], ["regress", "record", "X"], ["provenance", "audit"],
                     ["scope", "set"], ["trim"], ["gate", "--file"], ["approve", "--minutes", "soon", "x"]):
            code, _out, err = self.run_ad(*args)
            self.assertEqual(code, 2, args)
            self.assertNotIn("Traceback", err, args)

    def test_help_exits_0(self):
        for args in (["--help"], ["manifest", "--help"], ["ledger", "add", "--help"], ["regress", "record", "-h"]):
            code, out, _err = self.run_ad(*args)
            self.assertEqual(code, 0, args)
            self.assertIn("usage:", out)

    def test_runtime_errors_are_one_line_and_exit_2(self):
        cases = (["manifest", "record", "missing.txt"], ["ledger", "add", "PERMIT", "x"],
                 ["manifest", "record", "ad.py", "--range", "9-1"], ["trim", "missing.log"],
                 ["gate", "--file", "missing.md"], ["provenance", "audit", "missing.md"],
                 ["provenance", "add", "S", "src", "--confidence", "certain"],
                 ["regress", "record", "F1-inventory", "maybe", "m"], ["rules", "rewrite", "missing.md"])
        for args in cases:
            code, out, err = self.run_ad(*args)
            self.assertEqual(code, 2, args)
            self.assertTrue(err.startswith("error: "), (args, err))
            self.assertEqual(len(err.strip().splitlines()), 1, (args, err))
            self.assertEqual(out, "", args)

    def test_read_only_commands_do_not_create_the_state_directory(self):
        # GS-21: `manifest show` used to create .agent/.
        self.write("doc.md", "# T\n")
        for args in (["manifest", "show"], ["ledger", "show"], ["checkpoint", "show"], ["reinject"],
                     ["regress", "show"], ["regress", "report"], ["provenance", "show"]):
            self.ok(*args)
        self.assertEqual(self.run_ad("manifest", "check", "doc.md")[0], 1)
        self.assertEqual(self.run_ad("ledger", "check", "push", "to", "main")[0], 3)
        self.assertEqual(self.run_ad("provenance", "audit", "doc.md")[0], 1)
        self.ok("gate", "Here is the plan.")
        self.ok("trim", "doc.md")
        self.assertFalse(os.path.exists(self.state))
        self.assertFalse(os.path.exists(os.path.join(self.project, ".agent")))

    def test_unusable_state_directory(self):
        # GS-21: read-only commands used to end in NotADirectoryError tracebacks.
        blocker = os.path.join(self.tmp, "blocker")
        with open(blocker, "w") as handle:
            handle.write("x")
        env = {"AGENT_STATE_DIR": os.path.join(blocker, "state")}
        for args in (["manifest", "show"], ["ledger", "show"], ["checkpoint", "show"], ["reinject"],
                     ["regress", "show"], ["regress", "report"]):
            code, _out, err = self.run_ad(*args, env=env)
            self.assertEqual(code, 0, (args, err))
        for args in (["ledger", "add", "NOTE", "x"], ["checkpoint", "write", "x"],
                     ["manifest", "record", self.ad], ["regress", "init"]):
            code, _out, err = self.run_ad(*args, env=env)
            self.assertEqual(code, 2, args)
            self.assertTrue(err.startswith("error: "), err)
            self.assertNotIn("Traceback", err)

    def test_no_bytecode_is_written_next_to_the_scripts(self):
        # GS-33-V: __pycache__ in a skill folder shows up as an untracked directory.
        self.ok("version")
        self.ok("ledger", "add", "NOTE", "x")
        self.ok("regress", "show")
        self.run_ad("hook", "session-start", stdin="{}")
        self.assertFalse(os.path.exists(os.path.join(self.lib, "__pycache__")))

    def test_state_is_found_from_a_subdirectory_of_a_repository(self):
        # GS-06: a sub-directory used to see an empty ledger.
        env = {"AGENT_STATE_DIR": ""}
        os.mkdir(os.path.join(self.project, ".git"))
        sub = os.path.join(self.project, "pkg", "api")
        os.makedirs(sub)
        self.ok("ledger", "add", "FORBID", "never touch prod", env=env)
        out = self.ok("ledger", "show", env=env, cwd=sub)
        self.assertIn("never touch prod", out)
        self.assertFalse(os.path.exists(os.path.join(sub, ".agent")))
        with open(os.path.join(self.project, ".agent", ".gitignore")) as handle:
            self.assertEqual(handle.read().strip(), "*")

    def test_output_is_utf8_whatever_the_locale(self):
        # HC-25-V: a non-UTF-8 locale used to end `reinject` in UnicodeEncodeError.
        env = {"PYTHONIOENCODING": "ascii:strict", "LC_ALL": "C"}
        self.ok("ledger", "add", "NOTE", "café — résumé", env=env)
        out = self.ok("reinject", env=env)
        self.assertIn("café — résumé", out)
        out = self.ok("checkpoint", "write", env=env, stdin="Goal: naïve “quote”\n")
        self.assertIn("naïve “quote”", self.ok("checkpoint", "show", env=env))


class StateCommandTests(CliCase):
    def test_manifest_flow(self):
        path = self.write("notes.txt", "one\ntwo\n")
        out = self.ok("manifest", "record", "notes.txt", "--range", "1-2", "--range", "2-9", "--summary", "two lines")
        self.assertIn("recorded " + os.path.realpath(path), out)
        code, out, _err = self.run_ad("manifest", "check", "notes.txt")
        self.assertEqual(code, 0)
        self.assertIn("UNCHANGED | 8 B | read 1x", out)
        self.assertIn("ranges 1-9 | summary two lines", out)
        self.assertIn("notes.txt", self.ok("manifest", "show"))
        self.write("notes.txt", "changed\n")
        code, out, _err = self.run_ad("manifest", "check", "notes.txt")
        self.assertEqual((code, out.split(" | ")[0]), (1, "CHANGED"))
        os.remove(path)
        code, out, _err = self.run_ad("manifest", "check", path)
        self.assertEqual((code, out.split(" | ")[0]), (1, "MISSING"))

    def test_manifest_record_of_a_fetch_that_left_no_file(self):
        out = self.ok("manifest", "record", "gone.bin", "--url", "https://example.org/gone.bin")
        self.assertIn("gone.bin", out)

    def test_ledger_flow_and_exit_codes(self):
        self.ok("ledger", "add", "GRANT", "edit", "the", "docs", "folder", "freely")
        self.ok("ledger", "add", "forbid", "never push to main")
        code, out, _err = self.run_ad("ledger", "check", "delete the production database")
        self.assertEqual((code, out.splitlines()[0]), (3, "NO MATCH"))
        code, out, _err = self.run_ad("ledger", "check", "edit", "docs", "folder")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("MATCH GRANT ["))
        code, out, _err = self.run_ad("ledger", "check", "git push origin main")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("MATCH FORBID ["))
        self.assertIn("keyword match", out)
        self.assertIn("archived", self.ok("ledger", "clear"))
        self.assertEqual(self.ok("ledger", "show"), "(ledger empty)\n")

    def test_ledger_add_help_records_nothing(self):
        # GS-13: `ledger add --help` used to be recorded as an entry.
        self.ok("ledger", "add", "--help")
        self.assertEqual(self.ok("ledger", "show"), "(ledger empty)\n")

    def test_checkpoint_write_from_arguments_and_stdin(self):
        self.ok("checkpoint", "write", "Goal:", "ship")
        self.assertIn("Goal: ship", self.ok("checkpoint", "show"))
        self.ok("checkpoint", "write", stdin="Goal: from stdin\nOpen: tests\n")
        shown = self.ok("checkpoint", "show")
        self.assertIn("Goal: from stdin\nOpen: tests", shown)
        self.assertTrue(shown.startswith("# CHECKPOINT "))

    def test_checkpoint_is_not_overwritten_by_help_or_empty_input(self):
        # GS-25
        self.ok("checkpoint", "write", "real goal")
        self.ok("checkpoint", "write", "--help")
        code, _out, err = self.run_ad("checkpoint", "write", stdin="")
        self.assertEqual(code, 2)
        self.assertIn("empty", err)
        self.assertIn("real goal", self.ok("checkpoint", "show"))

    def test_reinject(self):
        self.assertEqual(self.ok("reinject"), "(no state recorded)\n")
        self.ok("ledger", "add", "STOP", "stop when two runs fail")
        for index in range(60):
            self.ok("manifest", "record", self.write("f%02d.txt" % index, "x\n"), "--summary", "s" * 300)
        short = self.ok("reinject")
        self.assertTrue(short.startswith("State recorded earlier by the agent-discipline tools"))
        self.assertLessEqual(len(short), 6001)
        self.assertIn("stop when two runs fail", short)
        full = self.ok("reinject", "--full")
        self.assertGreater(len(full), len(short))
        self.assertEqual(sum(1 for line in full.splitlines() if ".txt (" in line), 60)


class GateAndTrimTests(CliCase):
    def test_gate_inputs_and_exit_codes(self):
        # GS-09: a piped message printed PASS, and a blocked message exited 0.
        code, out, _err = self.run_ad("gate", stdin="All done, fixed.\n")
        self.assertEqual(code, 1)
        self.assertIn("Acceptance:", out)
        code, out, _err = self.run_ad("gate", "All", "done,", "fixed.")
        self.assertEqual(code, 1)
        path = self.write("final.md", "All done.\n" + EVIDENCE)
        code, out, _err = self.run_ad("gate", "--file", path)
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "PASS")
        self.assertIn("tool log has no shell commands", out)
        self.assertEqual(self.ok("gate", stdin="Here is the plan for tomorrow.\n"), "PASS\n")

    def test_gate_without_a_message_is_a_usage_error(self):
        code, out, err = self.run_ad("gate", stdin="")
        self.assertEqual(code, 2)
        self.assertNotIn("PASS", out)
        self.assertIn("no message", err)

    def test_gate_accepts_a_very_long_message_on_stdin(self):
        message = "Notes.\n" + ("filler line\n" * 20000) + "All done.\n" + EVIDENCE
        self.assertEqual(self.ok("gate", stdin=message).splitlines()[0], "PASS")

    def test_gate_checks_the_cited_command_against_the_tool_log(self):
        os.makedirs(self.state)
        record = {"ts": "2030-01-01T00:00:00+00:00", "session": "s", "prompt": "", "tool": "Bash",
                  "cmd": "git status", "ok": True, "exit": 0}
        with open(os.path.join(self.state, "toollog.jsonl"), "w") as handle:
            handle.write(json.dumps(record) + "\n")
        code, out, _err = self.run_ad("gate", stdin="All done.\n" + EVIDENCE)
        self.assertEqual(code, 1)
        self.assertIn("pytest tests/unit -q", out)
        self.assertEqual(self.ok("gate", "--lenient", stdin="All done.\n" + EVIDENCE), "PASS\n")
        self.assertEqual(self.ok("gate", stdin="All done.\n" + EVIDENCE, env={"AD_GATE_STRICT": "0"}), "PASS\n")
        self.assertEqual(self.ok("gate", stdin="All done, fixed.", env={"AD_GATE": "off"}), "PASS\n")

    def test_trim_states_only_what_it_did(self):
        # GS-34-V / spec section 10 item 12: the CLI stores nothing and must not say "stored".
        path = self.write("big.log", "\n".join("line %d" % index for index in range(5000)))
        out = self.ok("trim", path)
        header = out.splitlines()[0]
        self.assertTrue(header.startswith("[head-tail] source: " + path))
        self.assertIn("nothing was stored", header)
        self.assertIn("line 4999", out)
        self.assertLess(len(out), 7000)
        self.assertFalse(os.path.exists(self.state))
        out = self.ok("trim", "-", stdin="short text\n")
        self.assertEqual(out.splitlines()[0][:13], "[passthrough]")
        self.assertIn("short text", out)

    def test_bad_trim_setting_falls_back(self):
        path = self.write("big.log", "x\n" * 5000)
        self.ok("trim", path, env={"AD_TRIM_CHARS": "6k"})


class ProvenanceAndRegressTests(CliCase):
    def test_provenance_flow(self):
        doc = self.write("report.md", "# Summary\n\n## Costs\n")
        self.assertIn("Summary", self.ok("provenance", "add", "Summary", "notes.md", "--quote", "q",
                                         "--confidence", "established"))
        code, out, _err = self.run_ad("provenance", "audit", doc)
        self.assertEqual(code, 1)
        self.assertIn("- Costs", out)
        self.ok("provenance", "add", "costs", "ledger.csv")
        self.assertEqual(self.run_ad("provenance", "audit", doc)[0], 0)
        self.assertIn("| Summary | notes.md | established | q |", self.ok("provenance", "show"))
        self.assertNotIn("Summary", self.ok("provenance", "show", "Costs"))

    def test_regress_flow(self):
        path = self.ok("regress", "init").strip()
        self.assertEqual(path, os.path.join(self.state, "regress", "set.json"))
        self.assertIn("[F1-inventory]", self.ok("regress", "show"))
        self.assertIn("annual_report.pdf", self.ok("regress", "show"))
        code, _out, err = self.run_ad("regress", "record", "F1-inventroy", "pass", "model-a")
        self.assertEqual(code, 2)
        self.assertIn("unknown item id", err)
        self.assertIn("Warning", self.ok("regress", "record", "F1-inventroy", "pass", "model-a", "--force"))
        self.ok("regress", "record", "F1-inventory", "partial", "model-a", "--note", "asked first")
        report = self.ok("regress", "report")
        self.assertIn("| F1-inventory | partial (", report)
        self.assertIn("model-a: passed 0 of 1 run (12 in set); partial 1, fail 0, not run 11", report)
        self.assertIn("not in the set (not counted): F1-inventroy", report)
        self.assertEqual(self.ok("regress", "init", "--force").strip(), path)

    def test_regress_report_survives_a_damaged_set(self):
        self.ok("regress", "init")
        with open(os.path.join(self.state, "regress", "set.json"), "w") as handle:
            handle.write("[{,]")
        code, _out, err = self.run_ad("regress", "report")
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", err)


@unittest.skipUnless(HAVE_GUARDS, NEEDS_GUARDS)
class GuardCommandTests(CliCase):
    def test_fence_check_exit_codes(self):
        code, out, _err = self.run_ad("fence-check", "rm", "-rf", "/")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("BLOCK "))
        self.assertIn("approve", out)
        self.assertEqual(self.ok("fence-check", "ls", "-la"), "ALLOW\n")
        self.assertEqual(self.ok("fence-check", "echo 'rm -rf / is dangerous'"), "ALLOW\n")
        code, out, _err = self.run_ad("fence-check", "--", "git", "push", "--force", "origin", "main")
        self.assertEqual(code, 1)
        self.assertEqual(self.run_ad("fence-check")[0], 2)

    def test_approve_unlocks_exactly_one_command(self):
        command = "git push --force origin feature/x"
        self.assertEqual(self.run_ad("fence-check", command)[0], 1)
        out = self.ok("approve", "--minutes", "5", "--note", "user said yes", "--", "git", "push", "--force",
                      "origin", "feature/x")
        self.assertIn("approved", out)
        self.assertEqual(self.ok("fence-check", command), "ALLOW\n")
        self.assertEqual(self.run_ad("fence-check", "git push --force origin other")[0], 1)
        self.assertIn("git push --force origin feature/x", self.ok("approvals", "show"))
        self.ok("approvals", "clear")
        self.assertEqual(self.run_ad("fence-check", command)[0], 1)

    def test_approve_accepts_one_quoted_command(self):
        self.ok("approve", "rm -rf build")
        self.assertEqual(self.ok("fence-check", "rm -rf build"), "ALLOW\n")
        code, _out, err = self.run_ad("approve")
        self.assertEqual(code, 2)
        self.assertIn("no command", err)

    def test_a_ledger_grant_never_unlocks_the_fence(self):
        # GS-01 / HC-21-V: planted or self-written GRANT text used to unlock `rm -rf`.
        self.ok("ledger", "add", "GRANT", "rm -rf anything recursive force delete build")
        self.assertEqual(self.run_ad("fence-check", "rm -rf build anything")[0], 1)

    def test_scope_commands(self):
        self.assertIn(self.project, self.ok("scope", "show"))
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        # GS-25: an invalid --allow regex must not silently widen or disable the fence.
        code, _out, err = self.run_ad("scope", "set", self.project, "--allow", "(")
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)
        self.ok("scope", "set", self.project, "--allow", "^/opt/data/")
        self.ok("scope", "add", other)
        shown = self.ok("scope", "show")
        self.assertIn(other, shown)
        self.assertIn("^/opt/data/", shown)
        self.assertEqual(self.ok("fence-check", "touch %s/x" % other), "ALLOW\n")
        code, out, _err = self.run_ad("fence-check", "touch /etc/ad-test-x")
        self.assertEqual(code, 1, out)

    def test_fetch_check_exit_codes(self):
        self.assertEqual(self.ok("fetch-check", "ls"), "ALLOW\n")
        code, out, _err = self.run_ad("fetch-check", "curl", "-O", "https://example.org/disk.iso")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("BLOCK "))
        self.assertEqual(self.ok("fetch-check", "curl", "-O", "https://example.org/notes.txt").splitlines()[0],
                         "ALLOW")

    def test_rules_commands(self):
        self.write("CLAUDE.md", "# Rules\n\nNever run `git push --force`.\nBe careful.\n")
        code, out, _err = self.run_ad("rules", "lint", self.project)
        self.assertEqual(code, 1)
        self.assertIn("CLAUDE.md", out)
        self.assertIn("L3 [", out)
        out = self.ok("rules", "rewrite", os.path.join(self.project, "CLAUDE.md"))
        self.assertIn("L3:", out)
        self.assertIn("When ", out)
        compiled = json.loads(self.ok("rules", "compile", self.project, "--script-path", "/opt/ad.py"))
        self.assertIn("Bash(git push --force *)", compiled["permissions"]["deny"])
        self.assertIn("/opt/ad.py", json.dumps(compiled))
        empty = os.path.join(self.tmp, "empty")
        os.mkdir(empty)
        self.assertIn("no rules files", self.ok("rules", "lint", empty))

    def test_test_impact_outside_a_repository_is_a_usage_error(self):
        code, _out, err = self.run_ad("test-impact", "--root", self.project)
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("error: "))
        self.assertNotIn("Traceback", err)

    def test_test_impact_rejects_an_option_as_base(self):
        # Spec section 10 item 11.
        code, _out, err = self.run_ad("test-impact", "--base=--output=/tmp/x", "--root", self.project)
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)

    def test_deny_regex_always_exits_0(self):
        payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                              "tool_input": {"command": "git push --force origin main"}})
        code, out, _err = self.run_ad("deny-regex", r"git\s+push\s+.*--force", "(", stdin=payload)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")
        code, out, _err = self.run_ad("deny-regex", r"git\s+push\s+.*--force", stdin=payload.replace("--force", ""))
        self.assertEqual((code, out), (0, ""))
        code, out, _err = self.run_ad("deny-regex", stdin="not json")
        self.assertEqual((code, out), (0, ""))


if __name__ == "__main__":
    unittest.main()
