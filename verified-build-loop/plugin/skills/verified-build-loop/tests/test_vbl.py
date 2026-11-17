"""Tests for the verified-build-loop hook scripts.

Each test builds a small project in a temporary directory, copies the hook
scripts into ``.claude/hooks/`` and runs them as subprocesses with the hook
input on stdin, the way Claude Code runs them.

Run from any directory:
    python3 -B -m unittest discover -s <skill folder>/tests
"""
import importlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SKILL, "scripts")
TEMPLATES = os.path.join(SKILL, "templates")
SCRIPT_NAMES = ("vbl_common.py", "stop_check.py", "protect_paths.py", "post_edit_lint.py", "plan_check.py")
HAVE_GIT = shutil.which("git") is not None

GOOD_CODE = "def add(a, b):\n    return a + b\n"
BAD_CODE = "def add(a, b):\n    return a - b\n"
TEST_CODE = (
    "import sys, unittest\n"
    "sys.path.insert(0, 'src')\n"
    "import calc\n"
    "class T(unittest.TestCase):\n"
    "    def test_add(self):\n"
    "        self.assertEqual(calc.add(1, 2), 3)\n"
)
FEATURES = {"features": [{"id": "F001", "description": "add", "spec_section": "2.1",
                          "steps": ["a"], "passes": False}]}
GOOD_PLAN = (
    "# Plan\n\n1. Write the test.\n2. Write the code.\n\n"
    "## Acceptance checks\n- `python3 -m unittest` prints OK\n\n"
    "## Assumptions\n- none\n"
)


class ProjectCase(unittest.TestCase):
    """A temporary project with the hooks installed. ``git`` is on unless a test turns it off."""

    use_git = True

    def setUp(self):
        if self.use_git and not HAVE_GIT:
            self.skipTest("git is not installed")
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="vbl-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "project")
        self.counter = os.path.join(self.tmp, "fast-ran")
        self.full_counter = os.path.join(self.tmp, "full-ran")
        hooks = os.path.join(self.root, ".claude", "hooks")
        os.makedirs(hooks)
        for name in SCRIPT_NAMES:
            shutil.copy(os.path.join(SCRIPTS, name), hooks)
        self.write("src/calc.py", GOOD_CODE)
        self.write("tests/test_calc.py", TEST_CODE)
        self.write("feature_list.json", json.dumps(FEATURES))
        self.write(".gitignore", ".claude/verify-lock.json\nignored/\n__pycache__/\n")
        self.config = {
            "fast_checks": [{
                "name": "unit",
                "command": "echo ran >> %s; %s -B -m unittest discover -s tests -q" % (self.counter, sys.executable),
                "timeout_seconds": 60,
            }],
            "full_checks": [{"name": "full", "command": "echo ran >> %s" % self.full_counter,
                             "timeout_seconds": 60}],
            "lint_on_edit": {
                "command": sys.executable + " -B -c \"import ast,sys;ast.parse(open(sys.argv[1]).read())\" {file}",
                "extensions": [".py"], "timeout_seconds": 30,
            },
            "protected": ["tests/test_calc.py"],
            "feature_list": "feature_list.json",
            "fingerprint_exclude": [],
        }
        self.save_config()
        self.env = {key: value for key, value in os.environ.items() if key != "CLAUDE_PROJECT_DIR"}
        self.env["CLAUDE_PROJECT_DIR"] = self.root
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        if self.use_git:
            self.git("init", "-q", ".")
            self.git("config", "user.email", "t@example.com")
            self.git("config", "user.name", "t")
            self.commit("init")

    # -- helpers -----------------------------------------------------------

    def path(self, relative):
        return os.path.join(self.root, *relative.split("/"))

    def write(self, relative, text):
        target = self.path(relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(text)

    def read(self, relative):
        with open(self.path(relative), encoding="utf-8") as handle:
            return handle.read()

    def save_config(self):
        self.write(".claude/verify.json", json.dumps(self.config, indent=2))

    def git(self, *args):
        return subprocess.run(("git",) + args, cwd=self.root, capture_output=True, text=True, check=True)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def hook(self, script, payload, env=None):
        """Run one hook script; return (exit code, stdout, stderr)."""
        result = subprocess.run(
            [sys.executable, "-B", self.path(".claude/hooks/" + script)],
            input=json.dumps(payload) if not isinstance(payload, str) else payload,
            capture_output=True, text=True, cwd=self.root, env=env or self.env, timeout=120,
        )
        return result.returncode, result.stdout, result.stderr

    def stop(self, active=False):
        return self.hook("stop_check.py", {"stop_hook_active": active, "cwd": self.root})

    def assert_stop_passes(self, active=False):
        code, out, err = self.stop(active)
        self.assertEqual(code, 0, "the Stop hook blocked:\n" + err + out)
        return out

    def assert_stop_blocks(self, text, active=False):
        code, out, err = self.stop(active)
        self.assertEqual(code, 2, "the Stop hook did not block (exit %d):\n%s%s" % (code, err, out))
        self.assertIn(text, err)
        for script in SCRIPT_NAMES:  # a traceback of the hook itself, not of the project's tests
            self.assertNotIn(script + '", line', err)
        return err

    def runs(self, counter=None):
        try:
            with open(counter or self.counter) as handle:
                return len(handle.read().splitlines())
        except FileNotFoundError:
            return 0

    def file_tool(self, tool, relative, **tool_input):
        tool_input["file_path"] = self.path(relative)
        return self.hook("protect_paths.py", {"tool_name": tool, "tool_input": tool_input, "cwd": self.root})

    def bash(self, command):
        return self.hook("protect_paths.py",
                         {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": self.root})

    def assert_bash(self, command, blocked):
        code, _out, err = self.bash(command)
        self.assertEqual(code, 2 if blocked else 0, "%r -> exit %d\n%s" % (command, code, err))

    def edit_config(self, old, new):
        return self.file_tool("Edit", ".claude/verify.json", old_string=old, new_string=new)


class StopCheckTests(ProjectCase):
    def test_first_run_passes_and_creates_the_lock(self):
        self.assert_stop_passes()
        self.assertTrue(os.path.isfile(self.path(".claude/verify-lock.json")))
        self.assertEqual(self.runs(), 1)

    def test_no_change_skips_the_checks(self):
        self.assert_stop_passes()
        self.assert_stop_passes()
        self.assertEqual(self.runs(), 1)

    def test_a_code_change_reruns_and_a_failure_blocks(self):
        self.assert_stop_passes()
        self.write("src/calc.py", BAD_CODE)
        err = self.assert_stop_blocks("Check 'unit' failed")
        self.assertIn("AssertionError", err)
        self.assertEqual(self.runs(), 2)

    def test_a_fix_after_a_failure_passes(self):
        self.assert_stop_passes()
        self.write("src/calc.py", BAD_CODE)
        self.assert_stop_blocks("Check 'unit' failed")
        self.write("src/calc.py", GOOD_CODE)
        self.assert_stop_passes(active=True)

    def test_the_third_identical_failure_lets_the_turn_end_with_a_message(self):
        self.assert_stop_passes()
        self.write("src/calc.py", BAD_CODE)
        self.assert_stop_blocks("checks failed")
        self.assert_stop_blocks("checks failed", active=True)
        out = self.assert_stop_passes(active=True)
        message = json.loads(out)["systemMessage"]
        self.assertIn("3 times", message)
        self.assertIn("Check 'unit' failed", message)

    def test_a_new_turn_blocks_again_after_the_repeat_limit(self):
        self.assert_stop_passes()
        self.write("src/calc.py", BAD_CODE)
        self.assert_stop_blocks("checks failed")
        self.assert_stop_blocks("checks failed", active=True)
        self.assert_stop_passes(active=True)
        self.assert_stop_blocks("checks failed", active=False)

    def test_a_file_that_git_ignores_does_not_rerun_the_checks(self):
        self.assert_stop_passes()
        self.write("ignored/toollog.jsonl", "x\n")
        self.assert_stop_passes()
        self.assertEqual(self.runs(), 1)

    def test_a_tracked_file_in_a_build_folder_reruns_the_checks(self):
        self.write("dist/package.txt", "a\n")
        self.commit("add dist")
        self.assert_stop_passes()
        self.write("dist/package.txt", "bb\n")
        self.assert_stop_passes()
        self.assertEqual(self.runs(), 2)

    def test_a_new_untracked_file_reruns_the_checks(self):
        self.assert_stop_passes()
        self.write("src/extra.py", "x = 1\n")
        self.assert_stop_passes()
        self.assertEqual(self.runs(), 2)

    def test_a_deleted_file_reruns_the_checks(self):
        self.write("src/extra.py", "x = 1\n")
        self.commit("extra")
        self.assert_stop_passes()
        os.remove(self.path("src/extra.py"))
        self.assert_stop_passes()
        self.assertEqual(self.runs(), 2)

    def test_failing_output_that_is_not_utf8_still_blocks(self):
        self.config["fast_checks"] = [{"name": "bin", "command": "printf '\\377\\n'; exit 1", "timeout_seconds": 5}]
        self.save_config()
        self.assert_stop_blocks("Check 'bin' failed (exit 1)")

    def test_a_timeout_blocks_and_stops_the_whole_process_group(self):
        marker = os.path.join(self.tmp, "late")
        self.config["fast_checks"] = [{"name": "slow", "command": "sleep 2; touch %s" % marker,
                                       "timeout_seconds": 1}]
        self.save_config()
        started = time.time()
        self.assert_stop_blocks("timed out after 1 seconds")
        self.assertLess(time.time() - started, 1.9)
        time.sleep(1.6)
        self.assertFalse(os.path.exists(marker), "the timed-out command kept running")

    def test_a_check_does_not_wait_for_input(self):
        self.config["fast_checks"] = [{"name": "reads", "command": "cat", "timeout_seconds": 5}]
        self.save_config()
        self.assert_stop_passes()

    def test_a_malformed_config_blocks_with_a_plain_message(self):
        cases = (
            ("[]", "must hold a JSON object"),
            (json.dumps({"fast_checks": "pytest"}), "'fast_checks' must be a list"),
            (json.dumps({"fast_checks": [{"name": "a"}]}), "needs a 'command'"),
            (json.dumps({"fast_checks": [{"name": "a", "command": "true", "timeout_seconds": "soon"}]}),
             "'timeout_seconds'"),
            (json.dumps({"fast_checks": [], "protected": "tests"}), "'protected' must be a list"),
            ("{not json", "not valid JSON"),
        )
        for text, expected in cases:
            with self.subTest(config=text):
                self.write(".claude/verify.json", text)
                self.assert_stop_blocks(expected)

    def test_a_malformed_lock_blocks_and_names_relock(self):
        self.write(".claude/verify-lock.json", "[]")
        self.assert_stop_blocks("relock")

    def test_a_project_without_verify_json_is_left_alone(self):
        os.remove(self.path(".claude/verify.json"))
        self.assertEqual(self.stop(), (0, "", ""))

    def test_a_project_without_a_feature_list_works(self):
        os.remove(self.path("feature_list.json"))
        self.commit("no features")
        self.assert_stop_passes()
        self.write("src/calc.py", BAD_CODE)
        self.assert_stop_blocks("Check 'unit' failed")


class IntegrityTests(ProjectCase):
    def test_a_protected_file_changed_by_a_script_blocks_until_it_is_restored(self):
        self.assert_stop_passes()
        self.write("tests/test_calc.py", TEST_CODE + "# weakened\n")
        self.assert_stop_blocks("protected file 'tests/test_calc.py' changed")
        self.git("restore", "tests/test_calc.py")
        self.assert_stop_passes()

    def test_a_missing_protected_file_blocks(self):
        self.assert_stop_passes()
        os.remove(self.path("tests/test_calc.py"))
        self.assert_stop_blocks("protected file 'tests/test_calc.py' is missing")

    def test_a_hook_script_changed_by_a_script_blocks(self):
        self.assert_stop_passes()
        with open(self.path(".claude/hooks/post_edit_lint.py"), "a") as handle:
            handle.write("# changed\n")
        self.assert_stop_blocks("protected file '.claude/hooks/post_edit_lint.py' changed")

    def test_excluding_a_folder_from_the_fingerprint_does_not_unprotect_it(self):
        self.config["fingerprint_exclude"] = ["tests"]
        self.save_config()
        self.assert_stop_passes()
        self.write("tests/test_calc.py", TEST_CODE + "# weakened\n")
        self.assert_stop_blocks("protected file 'tests/test_calc.py' changed")

    def test_a_changed_fingerprint_exclude_blocks(self):
        self.assert_stop_passes()
        self.config["fingerprint_exclude"] = ["src"]
        self.save_config()
        self.assert_stop_blocks("setting 'fingerprint_exclude' was changed")

    def test_the_fingerprint_exclude_loophole_is_closed_end_to_end(self):
        self.assert_stop_passes()
        self.config["fingerprint_exclude"] = ["src"]
        self.save_config()
        self.write("src/calc.py", BAD_CODE)
        code, _out, _err = self.stop()
        self.assertEqual(code, 2)

    def test_removed_or_changed_checks_block(self):
        self.assert_stop_passes()
        self.config["fast_checks"][0]["command"] = "true"
        self.save_config()
        self.assert_stop_blocks("fast_checks check 'unit' was removed or changed")

    def test_an_added_check_and_an_added_protected_path_are_allowed(self):
        self.assert_stop_passes()
        self.config["fast_checks"].append({"name": "more", "command": "true", "timeout_seconds": 5})
        self.config["protected"].append("tests/test_other.py")
        self.save_config()
        self.assert_stop_passes()

    def test_a_redirected_feature_list_blocks(self):
        del self.config["feature_list"]
        self.save_config()
        self.assert_stop_passes()
        self.config["feature_list"] = "other.json"
        self.save_config()
        self.assert_stop_blocks("setting 'feature_list' was changed")

    def test_a_changed_feature_field_blocks(self):
        self.assert_stop_passes()
        changed = json.loads(json.dumps(FEATURES))
        changed["features"][0]["steps"] = ["easier"]
        self.write("feature_list.json", json.dumps(changed))
        self.assert_stop_blocks("feature F001 changed a field other than 'passes'")

    def test_a_feature_set_to_passes_runs_the_full_checks(self):
        self.assert_stop_passes()
        self.assertEqual(self.runs(self.full_counter), 0)
        passed = json.loads(json.dumps(FEATURES))
        passed["features"][0]["passes"] = True
        self.write("feature_list.json", json.dumps(passed))
        self.assert_stop_passes()
        self.assertEqual(self.runs(self.full_counter), 1)

    def test_a_failing_full_check_blocks_and_runs_again_next_time(self):
        self.config["full_checks"] = [{"name": "full", "command": "echo ran >> %s; exit 1" % self.full_counter,
                                       "timeout_seconds": 60}]
        self.save_config()
        self.assert_stop_passes()
        passed = json.loads(json.dumps(FEATURES))
        passed["features"][0]["passes"] = True
        self.write("feature_list.json", json.dumps(passed))
        err = self.assert_stop_blocks("Check 'full' failed")
        self.assertIn("F001", err)
        self.assert_stop_blocks("Check 'full' failed", active=True)
        self.assertEqual(self.runs(self.full_counter), 2)

    def test_unlock_and_relock(self):
        self.assert_stop_passes()
        common = self.path(".claude/hooks/vbl_common.py")
        result = subprocess.run([sys.executable, "-B", common, "unlock", "tests/test_calc.py"],
                                cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.read(".claude/verify.json"))["protected"], [])
        self.write("tests/test_calc.py", TEST_CODE + "# the user changed this\n")
        self.assert_stop_passes()
        with open(self.path(".claude/hooks/post_edit_lint.py"), "a") as handle:
            handle.write("# the user changed this\n")
        self.assert_stop_blocks("changed")
        result = subprocess.run([sys.executable, "-B", common, "relock"],
                                cwd=self.root, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_stop_passes()


class UnlockTests(ProjectCase):
    def unlock(self, target):
        return subprocess.run([sys.executable, "-B", self.path(".claude/hooks/vbl_common.py"), "unlock", target],
                              cwd=self.root, env=self.env, capture_output=True, text=True)

    def test_unlocking_a_pattern_forgets_the_files_it_covered(self):
        self.config["protected"] = ["tests/*"]
        self.save_config()
        self.assert_stop_passes()
        self.assertEqual(self.unlock("tests/*").returncode, 0)
        self.write("tests/test_calc.py", TEST_CODE + "# the user changed this\n")
        self.assert_stop_passes()

    def test_unlock_says_so_when_the_path_is_not_in_the_list(self):
        result = self.unlock("tests/other.py")
        self.assertEqual(result.returncode, 1)
        self.assertIn("is not in the 'protected' list", result.stdout)
        self.assertIn("tests/test_calc.py", result.stdout)


class NoGitTests(ProjectCase):
    use_git = False

    def test_without_git_the_folder_walk_decides(self):
        self.assert_stop_passes()
        self.assert_stop_passes()
        self.assertEqual(self.runs(), 1)
        self.write("node_modules/pkg/index.js", "x\n")
        self.assert_stop_passes()
        self.assertEqual(self.runs(), 1)
        self.write("src/calc.py", BAD_CODE)
        self.assert_stop_blocks("Check 'unit' failed")


class CrashGuardTests(unittest.TestCase):
    """An internal error in the Stop hook must reach Claude or the user; it must not pass in silence."""

    def call(self, active):
        sys.path.insert(0, SCRIPTS)
        self.addCleanup(sys.path.remove, SCRIPTS)
        vbl = importlib.import_module("vbl_common")

        def broken(_hook_input):
            raise RuntimeError("boom")

        out, err = io.StringIO(), io.StringIO()
        old = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            code = vbl.run_stop_hook(broken, {"stop_hook_active": active})
        except SystemExit as exit_request:
            code = exit_request.code
        finally:
            sys.stdout, sys.stderr = old
        return code, out.getvalue(), err.getvalue()

    def test_the_first_attempt_blocks_and_tells_claude(self):
        code, _out, err = self.call(active=False)
        self.assertEqual(code, 2)
        self.assertIn("did not run", err)
        self.assertIn("RuntimeError: boom", err)

    def test_the_next_attempt_lets_the_turn_end_and_tells_the_user(self):
        code, out, _err = self.call(active=True)
        self.assertEqual(code, 0)
        self.assertIn("did not run", json.loads(out)["systemMessage"])


class ProtectPathsTests(ProjectCase):
    def test_file_tools_cannot_write_protected_paths(self):
        for relative in ("tests/test_calc.py", ".claude/hooks/stop_check.py", ".claude/settings.json",
                         ".claude/verify-lock.json", ".claude/agents/reviewer.md"):
            for tool in ("Write", "Edit"):
                with self.subTest(path=relative, tool=tool):
                    code, _out, err = self.file_tool(tool, relative, content="x", old_string="a", new_string="b")
                    self.assertEqual(code, 2)
                    self.assertIn("is protected", err)

    def test_other_files_are_writable(self):
        self.assertEqual(self.file_tool("Write", "src/calc.py", content=BAD_CODE)[0], 0)
        self.assertEqual(self.file_tool("Write", "tests/test_new.py", content="x")[0], 0)

    def test_a_file_outside_the_project_is_not_this_hook_s_business(self):
        code, _out, _err = self.hook("protect_paths.py", {
            "tool_name": "Write", "tool_input": {"file_path": os.path.join(self.tmp, "elsewhere.txt"), "content": "x"}})
        self.assertEqual(code, 0)

    def test_feature_list_rules(self):
        flip = self.file_tool("Edit", "feature_list.json", old_string='"passes": false', new_string='"passes": true')
        self.assertEqual(flip[0], 0, flip[2])
        changed = self.file_tool("Edit", "feature_list.json", old_string='"add"', new_string='"anything"')
        self.assertEqual(changed[0], 2)
        self.assertIn("changed a field other than 'passes'", changed[2])
        added = json.loads(json.dumps(FEATURES))
        added["features"].append({"id": "F002", "description": "sub", "passes": False})
        self.assertEqual(self.file_tool("Write", "feature_list.json", content=json.dumps(added))[0], 0)
        added["features"][1]["passes"] = True
        self.assertEqual(self.file_tool("Write", "feature_list.json", content=json.dumps(added))[0], 2)
        self.assertEqual(self.file_tool("Write", "feature_list.json", content='{"features": []}')[0], 2)
        self.assertEqual(self.file_tool("Write", "feature_list.json", content="{broken")[0], 2)

    def test_verify_json_rules(self):
        allowed = self.edit_config('"tests/test_calc.py"', '"tests/test_calc.py", "tests/test_new.py"')
        self.assertEqual(allowed[0], 0, allowed[2])
        for old, new, expected in (
            ('"tests/test_calc.py"', '"tests/none.py"', "protected path 'tests/test_calc.py' was removed"),
            ('"timeout_seconds": 60', '"timeout_seconds": 1', "was removed or changed"),
            ('"fingerprint_exclude": []', '"fingerprint_exclude": ["src"]', "setting 'fingerprint_exclude' was changed"),
            ('"feature_list": "feature_list.json"', '"feature_list": "other.json"', "setting 'feature_list' was changed"),
            ('".py"', '".txt"', "setting 'lint_on_edit' was changed"),
        ):
            with self.subTest(new=new):
                code, _out, err = self.edit_config(old, new)
                self.assertEqual(code, 2)
                self.assertIn(expected, err)

    def test_a_plan_gate_cannot_be_switched_off_by_claude(self):
        code, _out, err = self.edit_config('"protected"', '"plan_gate": false, "protected"')
        self.assertEqual(code, 2)
        self.assertIn("setting 'plan_gate' was changed", err)

    def test_bash_commands_that_write_a_guarded_path_are_blocked(self):
        for command in (
            "rm tests/test_calc.py",
            "rm -r tests",
            "mv tests/test_calc.py /tmp/x",
            "sed -i 's/3/4/' tests/test_calc.py",
            "echo x > tests/test_calc.py",
            "echo x >> .claude/verify.json",
            "python3 -c \"open('tests/test_calc.py','w')\"",
            "git checkout main -- tests/test_calc.py",
            "git restore --source=HEAD~1 tests/test_calc.py",
            "git restore -s HEAD~1 tests/test_calc.py",
            "git restore tests/test_calc.py && rm tests/test_calc.py",
            "git restore tests/test_calc.py; echo x > tests/test_calc.py",
            "git stash push tests/test_calc.py",
            "python3 .claude/hooks/vbl_common.py unlock tests/test_calc.py",
            "python3 .claude/hooks/vbl_common.py relock",
            "rm .claude/verify-lock.json",
        ):
            with self.subTest(command=command):
                self.assert_bash(command, blocked=True)

    def test_bash_commands_that_do_not_write_a_guarded_path_pass(self):
        for command in (
            "cat tests/test_calc.py",
            "python3 -m unittest discover -s tests",
            "git add -A",
            "git commit -m 'F001: add'",
            "git diff tests/test_calc.py",
            "rm src/old.py",
            "echo done > /dev/null",
            "ls tests 2>/dev/null",
        ):
            with self.subTest(command=command):
                self.assert_bash(command, blocked=False)

    def test_claude_can_restore_a_protected_file_to_its_committed_content(self):
        for command in (
            "git restore tests/test_calc.py",
            "git restore -- tests/test_calc.py",
            "git restore --worktree tests/test_calc.py",
            "git checkout -- tests/test_calc.py",
            "git checkout HEAD -- tests/test_calc.py",
        ):
            with self.subTest(command=command):
                self.assert_bash(command, blocked=False)

    def test_no_config_means_no_rules(self):
        os.remove(self.path(".claude/verify.json"))
        self.assertEqual(self.file_tool("Write", ".claude/settings.json", content="{}")[0], 0)
        self.assert_bash("rm -r tests", blocked=False)


class LintTests(ProjectCase):
    def lint(self, relative, tool="Edit"):
        return self.hook("post_edit_lint.py",
                         {"tool_name": tool, "tool_input": {"file_path": self.path(relative)}, "cwd": self.root})

    def test_a_syntax_error_is_reported_to_claude(self):
        self.write("src/calc.py", "def add(a, b:\n")
        code, _out, err = self.lint("src/calc.py")
        self.assertEqual(code, 2)
        self.assertIn("lint errors", err)
        self.assertIn("SyntaxError", err)

    def test_clean_files_other_extensions_and_missing_files_pass(self):
        self.assertEqual(self.lint("src/calc.py")[0], 0)
        self.write("notes.txt", "def broken(:\n")
        self.assertEqual(self.lint("notes.txt")[0], 0)
        self.assertEqual(self.lint("src/missing.py")[0], 0)

    def test_a_file_name_with_a_space_and_a_quote_is_passed_whole(self):
        self.write("src/it's a file.py", "x = 1\n")
        self.assertEqual(self.lint("src/it's a file.py")[0], 0)
        self.write("src/it's a file.py", "x = (\n")
        self.assertEqual(self.lint("src/it's a file.py")[0], 2)

    def test_no_lint_setting_means_no_lint(self):
        del self.config["lint_on_edit"]
        self.save_config()
        self.write("src/calc.py", "def add(a, b:\n")
        self.assertEqual(self.lint("src/calc.py")[0], 0)


class PlanGateTests(ProjectCase):
    def plan(self, text, tool_input=None):
        payload = {"tool_name": "ExitPlanMode", "cwd": self.root,
                   "tool_input": tool_input if tool_input is not None else {"plan": text}}
        return self.hook("plan_check.py", payload)

    def test_a_plan_with_checks_and_assumptions_passes(self):
        self.assertEqual(self.plan(GOOD_PLAN), (0, "", ""))

    def test_labels_on_one_line_pass(self):
        text = "1. Do it.\n\n**Acceptance checks:** `make test` exits 0\n**Assumptions:** none\n"
        self.assertEqual(self.plan(text)[0], 0)

    def test_a_plan_without_acceptance_checks_is_denied(self):
        code, _out, err = self.plan("# Plan\n1. Write the code.\n\n## Assumptions\n- none\n")
        self.assertEqual(code, 2)
        self.assertIn("Acceptance checks", err)

    def test_acceptance_checks_need_a_command(self):
        text = "# Plan\n\n## Acceptance checks\n- it works\n\n## Assumptions\n- none\n"
        code, _out, err = self.plan(text)
        self.assertEqual(code, 2)
        self.assertIn("command", err)

    def test_a_command_in_a_later_section_does_not_count(self):
        text = "## Acceptance checks\n- it works\n\n## Assumptions\n- `git status` is clean\n"
        self.assertEqual(self.plan(text)[0], 2)

    def test_a_fenced_command_counts(self):
        text = "## Acceptance checks\n```bash\nmake test\n```\n\n## Assumptions\nnone\n"
        self.assertEqual(self.plan(text)[0], 0)

    def test_a_plan_without_assumptions_is_denied(self):
        code, _out, err = self.plan("# Plan\n\n## Acceptance checks\n- `make test` exits 0\n")
        self.assertEqual(code, 2)
        self.assertIn("Assumptions", err)

    def test_a_missing_plan_text_passes(self):
        self.assertEqual(self.plan("", tool_input={})[0], 0)

    def test_the_user_can_switch_the_gate_off(self):
        self.config["plan_gate"] = False
        self.save_config()
        self.assertEqual(self.plan("# Plan\n1. Just do it.\n")[0], 0)

    def test_no_config_means_no_gate(self):
        os.remove(self.path(".claude/verify.json"))
        self.assertEqual(self.plan("# Plan\n1. Just do it.\n")[0], 0)


class PackageTests(unittest.TestCase):
    """The skill text, the scripts and the templates must agree."""

    def skill_text(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as handle:
            return handle.read()

    def test_every_script_exists_and_compiles(self):
        for name in SCRIPT_NAMES:
            with open(os.path.join(SCRIPTS, name), encoding="utf-8") as handle:
                compile(handle.read(), name, "exec")
        self.assertEqual(sorted(os.listdir(SCRIPTS)), sorted(SCRIPT_NAMES))

    def test_every_file_that_the_skill_names_exists(self):
        import re
        text = self.skill_text()
        named = set(re.findall(r"\b((?:scripts|templates)/[A-Za-z0-9_.\-]+\.[a-z]+)", text))
        self.assertGreaterEqual(len(named), len(SCRIPT_NAMES))
        for relative in sorted(named):
            self.assertTrue(os.path.isfile(os.path.join(SKILL, *relative.split("/"))), relative)
        for folder in (SCRIPTS, TEMPLATES):
            for name in os.listdir(folder):
                self.assertIn(name, text, "SKILL.md never names " + name)

    def test_frontmatter_and_length(self):
        text = self.skill_text()
        self.assertTrue(text.startswith("---\nname: \"verified-build-loop\"\n"))
        description = [line for line in text.splitlines() if line.startswith("description:")][0]
        self.assertLessEqual(len(description), 420)
        self.assertNotIn("<", description)
        self.assertLessEqual(len(text.splitlines()), 500)

    def test_json_templates_parse_and_the_hooks_block_names_every_hook_script(self):
        with open(os.path.join(TEMPLATES, "verify.json"), encoding="utf-8") as handle:
            config = json.load(handle)
        for key in ("fast_checks", "full_checks", "lint_on_edit", "protected", "feature_list",
                    "fingerprint_exclude", "plan_gate"):
            self.assertIn(key, config)
        with open(os.path.join(TEMPLATES, "feature_list.json"), encoding="utf-8") as handle:
            self.assertIs(json.load(handle)["features"][0]["passes"], False)
        with open(os.path.join(TEMPLATES, "settings-hooks.json"), encoding="utf-8") as handle:
            hooks_text = handle.read()
        hooks = json.loads(hooks_text)["hooks"]
        self.assertEqual(sorted(hooks), ["PostToolUse", "PreToolUse", "Stop"])
        for name in ("stop_check.py", "protect_paths.py", "post_edit_lint.py", "plan_check.py"):
            self.assertIn(name, hooks_text)

    def test_the_template_config_passes_the_shape_check(self):
        sys.path.insert(0, SCRIPTS)
        self.addCleanup(sys.path.remove, SCRIPTS)
        vbl = importlib.import_module("vbl_common")
        with open(os.path.join(TEMPLATES, "verify.json"), encoding="utf-8") as handle:
            self.assertEqual(vbl.config_shape_problems(json.load(handle)), [])


if __name__ == "__main__":
    unittest.main()
