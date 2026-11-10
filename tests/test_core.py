"""Tests for lib/ad_core.py: state directory, file helpers, time, text, hook I/O."""
import contextlib
import datetime
import importlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import ad_core  # noqa: E402

FIXED_NOW = datetime.datetime(2030, 1, 15, 12, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))


class CoreCase(unittest.TestCase):
    """Base class: fresh temp directory, own AGENT_STATE_DIR, module reloaded per class."""

    @classmethod
    def setUpClass(cls):
        importlib.reload(ad_core)

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="ad-core-"))
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

    def capture(self, function, *args, **kwargs):
        """Run a function that prints and exits; return (stdout, stderr, exit code)."""
        out = io.StringIO()
        err = io.StringIO()
        code = None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                function(*args, **kwargs)
            except SystemExit as exit_info:
                code = exit_info.code
        return out.getvalue(), err.getvalue(), code


class StateDirTests(CoreCase):
    def test_override_absolute(self):
        self.assertEqual(ad_core.state_dir(create=False), self.state)

    def test_override_relative_resolves_against_start_dir(self):
        os.environ["AGENT_STATE_DIR"] = "rel/state"
        self.assertEqual(ad_core.state_dir(create=False), os.path.join(self.tmp, "rel", "state"))

    def test_override_tilde_is_expanded_not_created_literally(self):
        os.environ["HOME"] = self.tmp
        os.environ["AGENT_STATE_DIR"] = "~/adstate"
        self.assertEqual(ad_core.state_dir(create=False), os.path.join(self.tmp, "adstate"))

    def test_walks_up_to_git_directory(self):
        del os.environ["AGENT_STATE_DIR"]
        repo = os.path.join(self.tmp, "repo")
        sub = os.path.join(repo, "a", "b")
        os.makedirs(sub)
        os.mkdir(os.path.join(repo, ".git"))
        ad_core.set_start_dir(sub)
        self.assertEqual(ad_core.state_dir(create=False), os.path.join(repo, ".agent"))

    def test_git_file_counts_as_repository_root(self):
        del os.environ["AGENT_STATE_DIR"]
        worktree = os.path.join(self.tmp, "wt")
        os.makedirs(os.path.join(worktree, "src"))
        with open(os.path.join(worktree, ".git"), "w") as handle:
            handle.write("gitdir: elsewhere\n")
        ad_core.set_start_dir(os.path.join(worktree, "src"))
        self.assertEqual(ad_core.state_dir(create=False), os.path.join(worktree, ".agent"))

    def test_marked_state_directory_wins_over_outer_git(self):
        del os.environ["AGENT_STATE_DIR"]
        repo = os.path.join(self.tmp, "repo")
        inner = os.path.join(repo, "pkg")
        os.makedirs(os.path.join(inner, ".agent"))
        os.mkdir(os.path.join(repo, ".git"))
        with open(os.path.join(inner, ".agent", ".ad-state"), "w") as handle:
            handle.write("2.0.0\n")
        ad_core.set_start_dir(os.path.join(inner))
        self.assertEqual(ad_core.state_dir(create=False), os.path.join(inner, ".agent"))

    def test_subdirectory_and_root_share_one_state_directory(self):
        # GS-06 / HC-09: state must not fork when the working directory changes.
        del os.environ["AGENT_STATE_DIR"]
        repo = os.path.join(self.tmp, "repo")
        sub = os.path.join(repo, "sub")
        os.makedirs(sub)
        os.mkdir(os.path.join(repo, ".git"))
        ad_core.set_start_dir(repo)
        ad_core.save_json("x.json", {"a": 1})
        ad_core.set_start_dir(sub)
        self.assertEqual(ad_core.load_json("x.json", {}), {"a": 1})
        self.assertFalse(os.path.exists(os.path.join(sub, ".agent")))

    def test_fallback_is_start_directory(self):
        del os.environ["AGENT_STATE_DIR"]
        lonely = os.path.join(self.tmp, "lonely")
        os.makedirs(lonely)
        ad_core.set_start_dir(lonely)
        resolved = ad_core.state_dir(create=False)
        # No .git above a temp directory is expected; if the machine has one, the walk finds it.
        self.assertTrue(resolved.endswith(os.sep + ".agent"))

    def test_creation_writes_marker_gitignore_and_private_mode(self):
        path = ad_core.state_dir()
        with open(os.path.join(path, ".ad-state")) as handle:
            self.assertEqual(handle.read().strip(), ad_core.VERSION)
        with open(os.path.join(path, ".gitignore")) as handle:
            self.assertEqual(handle.read().strip(), "*")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o700)

    def test_read_helpers_do_not_create_the_state_directory(self):
        self.assertFalse(ad_core.state_exists())
        self.assertEqual(ad_core.load_json("x.json", {"d": 1}), {"d": 1})
        self.assertEqual(ad_core.read_lines("x.txt"), [])
        self.assertEqual(ad_core.read_jsonl("x.jsonl"), [])
        self.assertFalse(ad_core.rotate("x.jsonl", 1, 1))
        ad_core.state_dir(create=False)
        self.assertFalse(os.path.exists(self.state))

    def test_state_path(self):
        self.assertEqual(ad_core.state_path("a.json", create=False), os.path.join(self.state, "a.json"))
        self.assertFalse(os.path.exists(self.state))
        ad_core.state_path("a.json")
        self.assertTrue(ad_core.state_exists())


class FileHelperTests(CoreCase):
    def test_save_and_load_json(self):
        ad_core.save_json("m.json", {"k": [1, 2]})
        self.assertEqual(ad_core.load_json("m.json", {}), {"k": [1, 2]})
        if os.name == "posix":
            mode = stat.S_IMODE(os.stat(os.path.join(self.state, "m.json")).st_mode)
            self.assertEqual(mode, 0o600)
        leftovers = [name for name in os.listdir(self.state) if name.startswith(".tmp-")]
        self.assertEqual(leftovers, [])

    def test_load_json_returns_default_on_corrupt_or_wrong_type(self):
        ad_core.state_dir()
        with open(os.path.join(self.state, "bad.json"), "w") as handle:
            handle.write("{not json")
        self.assertEqual(ad_core.load_json("bad.json", {"d": 1}), {"d": 1})
        ad_core.save_json("list.json", [1])
        # GS-20: a manifest that holds a list must not crash callers that expect a dict.
        self.assertEqual(ad_core.load_json("list.json", {}), {})

    def test_update_json_returns_new_value_and_accepts_in_place_edit(self):
        self.assertEqual(ad_core.update_json("c.json", {}, lambda data: dict(data, n=1)), {"n": 1})

        def bump(data):
            data["n"] += 1

        self.assertEqual(ad_core.update_json("c.json", {}, bump), {"n": 2})

    def test_parallel_updates_lose_nothing(self):
        # GS-05 / HC-06: parallel writers must not drop each other's entries or corrupt the file.
        script = (
            "import sys; sys.dont_write_bytecode = True; sys.path.insert(0, %r)\n"
            "import ad_core\n"
            "def add(data):\n"
            "    data[sys.argv[1] + '-' + str(len(data))] = 1\n"
            "for _ in range(10):\n"
            "    ad_core.update_json('par.json', {}, add)\n" % LIB)
        processes = [subprocess.Popen([sys.executable, "-c", script, "w%d" % index], env=dict(os.environ))
                     for index in range(8)]
        for process in processes:
            self.assertEqual(process.wait(), 0)
        self.assertEqual(len(ad_core.load_json("par.json", {})), 80)

    def test_append_line_keeps_one_line_per_call(self):
        ad_core.append_line("log.txt", "first\nforged second line")
        ad_core.append_line("log.txt", "third")
        self.assertEqual(ad_core.read_lines("log.txt"), ["first forged second line", "third"])

    def test_read_jsonl_skips_bad_lines(self):
        for line in ('{"a": 1}', "", "not json", '{"cut": "sho', "[1, 2]", '{"b": 2}'):
            ad_core.append_line("rows.jsonl", line)
        self.assertEqual(ad_core.read_jsonl("rows.jsonl"), [{"a": 1}, {"b": 2}])

    def test_rotate_keeps_last_lines(self):
        for index in range(100):
            ad_core.append_line("big.log", "line %03d" % index)
        self.assertFalse(ad_core.rotate("big.log", 10 ** 6, 5))
        self.assertTrue(ad_core.rotate("big.log", 100, 5))
        self.assertEqual(ad_core.read_lines("big.log"), ["line %03d" % index for index in range(95, 100)])

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symbolic links")
    def test_symbolic_links_are_refused(self):
        # GS-32-V: a planted link must not redirect reads or writes outside the state directory.
        ad_core.state_dir()
        victim = os.path.join(self.tmp, "victim.txt")
        with open(victim, "w") as handle:
            handle.write("original\n")
        for name in ("linked.json", "linked.md"):
            os.symlink(victim, os.path.join(self.state, name))
        self.assertEqual(ad_core.load_json("linked.json", {"d": 1}), {"d": 1})
        self.assertEqual(ad_core.read_lines("linked.md"), [])
        with self.assertRaises(OSError):
            ad_core.save_json("linked.json", {"x": 1})
        with self.assertRaises(OSError):
            ad_core.append_line("linked.md", "pwned")
        with self.assertRaises(OSError):
            ad_core.write_text("linked.md", "pwned")
        with open(victim) as handle:
            self.assertEqual(handle.read(), "original\n")

    @unittest.skipIf(ad_core.fcntl is None, "needs fcntl")
    def test_lock_gives_up_and_proceeds(self):
        import fcntl
        ad_core.state_dir()
        original = ad_core.LOCK_TIMEOUT_SECONDS
        ad_core.LOCK_TIMEOUT_SECONDS = 0.1
        self.addCleanup(setattr, ad_core, "LOCK_TIMEOUT_SECONDS", original)
        with open(os.path.join(self.state, ".lock"), "w") as holder:
            fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
            with ad_core.state_lock():
                ad_core.save_json("after.json", {"ok": True})
        self.assertEqual(ad_core.load_json("after.json", {}), {"ok": True})

    def test_lock_is_reentrant(self):
        with ad_core.state_lock():
            with ad_core.state_lock():
                self.assertEqual(ad_core.update_json("r.json", {}, lambda data: {"n": 1}), {"n": 1})

    def test_unusable_state_directory_raises_oserror_for_writes_only(self):
        # GS-21: reads report "empty"; writes raise OSError, which the CLI turns into exit 2.
        blocker = os.path.join(self.tmp, "file")
        with open(blocker, "w") as handle:
            handle.write("x")
        os.environ["AGENT_STATE_DIR"] = os.path.join(blocker, "state")
        self.assertEqual(ad_core.load_json("m.json", {}), {})
        self.assertFalse(ad_core.state_exists())
        with self.assertRaises(OSError):
            ad_core.save_json("m.json", {})


class TimeTests(CoreCase):
    def test_now_has_offset_and_second_precision(self):
        self.assertEqual(ad_core.now(), "2030-01-15T12:00:00+02:00")

    def test_real_clock_is_aware(self):
        importlib.reload(ad_core)
        self.addCleanup(importlib.reload, ad_core)
        self.assertIsNotNone(ad_core.time_now().tzinfo)
        self.assertRegex(ad_core.now(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")

    def test_parse_ts_round_trip(self):
        self.assertEqual(ad_core.parse_ts(ad_core.now()), FIXED_NOW)

    def test_parse_ts_accepts_z_and_naive_and_rejects_garbage(self):
        parsed = ad_core.parse_ts("2030-01-15T10:00:00Z")
        self.assertEqual(parsed, FIXED_NOW)
        self.assertIsNotNone(ad_core.parse_ts("2030-01-15T10:00:00").tzinfo)
        for bad in ("", "yesterday", None, 5, "2030-13-45"):
            self.assertIsNone(ad_core.parse_ts(bad))


class TextTests(CoreCase):
    def test_clean_removes_control_characters_and_collapses_whitespace(self):
        self.assertEqual(ad_core.clean("a\x00b\x1b[31m c\n\n- GRANT:\tx"), "ab[31m c - GRANT: x")

    def test_clean_removes_bidi_and_zero_width_characters(self):
        self.assertEqual(ad_core.clean("ab\u202ecd\u200bef"), "abcdef")

    def test_clean_truncates_with_ellipsis_within_limit(self):
        result = ad_core.clean("x" * 500, 50)
        self.assertEqual(len(result), 50)
        self.assertTrue(result.endswith("\u2026"))
        self.assertEqual(ad_core.clean("short", 50), "short")

    def test_clean_handles_non_strings(self):
        self.assertEqual(ad_core.clean(None), "")
        self.assertEqual(ad_core.clean(12), "12")

    def test_redact(self):
        cases = {
            "curl -H 'Authorization: Bearer abc.def-123456' https://x": "abc.def-123456",
            "curl -H \"Authorization: Basic dXNlcjpwYXNz\" https://x": "dXNlcjpwYXNz",
            "deploy --token=tok_live_998877": "tok_live_998877",
            "export API_KEY=sk_test_4242": "sk_test_4242",
            "mysql --password hunter2secret db": "hunter2secret",
            "git clone https://alice:s3cr3tpw@example.com/r.git": "s3cr3tpw",
            "PASSWORD='two words' ./run": "two words",
            "x api-key: zzzzyyyy": "zzzzyyyy",
        }
        for text, secret in cases.items():
            redacted = ad_core.redact(text)
            self.assertNotIn(secret, redacted, text)
            self.assertIn("[REDACTED]", redacted, text)

    def test_redact_leaves_ordinary_commands_alone(self):
        for text in ("pytest tests/unit -q", "git push origin feature/x", "ls -la /tmp", "npm run test:e2e"):
            self.assertEqual(ad_core.redact(text), text)
        self.assertEqual(ad_core.redact(None), "")

    def test_human_size(self):
        self.assertEqual(ad_core.human_size(0), "0 B")
        self.assertEqual(ad_core.human_size(1023), "1023 B")
        self.assertEqual(ad_core.human_size(1536), "1.5 KB")
        self.assertEqual(ad_core.human_size(5 * 1024 ** 3), "5.0 GB")
        self.assertEqual(ad_core.human_size(None), "?")
        self.assertEqual(ad_core.human_size(-1), "?")

    def test_sha256_text(self):
        self.assertEqual(ad_core.sha256_text("abc"),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_env_helpers_fall_back_on_bad_values(self):
        # GS-24 / HC-13: a typo in an environment variable must never raise.
        os.environ["AD_X"] = "6k"
        self.assertEqual(ad_core.env_int("AD_X", 6000), 6000)
        self.assertEqual(ad_core.env_float("AD_X", 1.5), 1.5)
        os.environ["AD_X"] = " 42 "
        self.assertEqual(ad_core.env_int("AD_X", 1), 42)
        self.assertEqual(ad_core.env_int("AD_X", 1, maximum=10), 10)
        self.assertEqual(ad_core.env_int("AD_X", 1, minimum=100), 100)
        os.environ["AD_X"] = "nan"
        self.assertEqual(ad_core.env_float("AD_X", 2.0), 2.0)
        os.environ["AD_X"] = "2.5"
        self.assertEqual(ad_core.env_float("AD_X", 1.0), 2.5)
        self.assertEqual(ad_core.env_int("AD_MISSING", 7), 7)


class HookIoTests(CoreCase):
    def feed(self, raw):
        original = sys.stdin
        sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="ascii", errors="strict")
        self.addCleanup(setattr, sys, "stdin", original)

    def test_read_hook_input_parses_utf8_whatever_the_stream_encoding(self):
        # HC-25-V / GS-26: the stream above claims ASCII; the bytes are UTF-8.
        self.feed(json.dumps({"tool_input": {"file_path": "/p/caf\u00e9 \u201cq\u201d.txt"}},
                             ensure_ascii=False).encode("utf-8"))
        self.assertEqual(ad_core.read_hook_input()["tool_input"]["file_path"], "/p/caf\u00e9 \u201cq\u201d.txt")

    def test_read_hook_input_returns_empty_dict_on_any_problem(self):
        for raw in (b"", b"   ", b"{broken", b"[1, 2]", b'"text"', b"\xff\xfe"):
            self.feed(raw)
            self.assertEqual(ad_core.read_hook_input(), {})

    def test_deny_prints_decision_and_exits_zero(self):
        out, err, code = self.capture(ad_core.deny, "blocked: reason")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "blocked: reason",
        }})
        self.assertIn("blocked: reason", err)

    def test_allow_without_context_prints_nothing(self):
        out, _err, code = self.capture(ad_core.allow)
        self.assertEqual((out, code), ("", 0))

    def test_allow_with_context(self):
        out, _err, code = self.capture(ad_core.allow, "a fact", "PostToolUse")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"hookSpecificOutput": {
            "hookEventName": "PostToolUse", "additionalContext": "a fact"}})

    def test_stop_block(self):
        out, _err, code = self.capture(ad_core.stop_block, "why")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"decision": "block", "reason": "why"})

    def test_emit_session_context(self):
        out, _err, code = self.capture(ad_core.emit_session_context, "state")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"hookSpecificOutput": {
            "hookEventName": "SessionStart", "additionalContext": "state"}})
        out, _err, code = self.capture(ad_core.emit_session_context, "")
        self.assertEqual((out, code), ("", 0))

    def test_injected_context_stays_under_the_limit_and_cuts_whole_lines(self):
        text = "\n".join("line %05d" % index for index in range(5000))
        out, _err, _code = self.capture(ad_core.allow, text)
        context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertLess(len(context), 9000)
        for line in context.splitlines()[:-1]:
            self.assertRegex(line, r"^line \d{5}$")

    def test_output_is_ascii_json(self):
        out, _err, _code = self.capture(ad_core.allow, "caf\u00e9 \u2014 x")
        out.encode("ascii")
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["additionalContext"], "caf\u00e9 \u2014 x")


if __name__ == "__main__":
    unittest.main()
