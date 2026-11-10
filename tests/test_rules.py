"""Tests for lib/ad_rules.py: rule files, lint, rewrite template, compile (run as the host runs it), test impact."""
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import ad_core  # noqa: E402
import ad_rules  # noqa: E402

AD = os.path.join(LIB, "ad.py")
HAS_GIT = shutil.which("git") is not None

# A stand-in for `ad.py deny-regex`, so the compiled hook is tested even without the CLI.
DRIVER = """import sys
sys.dont_write_bytecode = True
sys.path.insert(0, %r)
import ad_rules
if sys.argv[1] == "deny-regex":
    ad_rules.deny_regex_hook(sys.argv[2:])
"""


class RulesCase(unittest.TestCase):
    """Base class: temp directory and own AGENT_STATE_DIR."""

    @classmethod
    def setUpClass(cls):
        importlib.reload(ad_core)
        importlib.reload(ad_rules)

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="ad-rules-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = dict(os.environ)
        self.addCleanup(self._restore_env, saved)
        for name in list(os.environ):
            if name.startswith("AD_") or name in ("AGENT_STATE_DIR", "CLAUDE_PROJECT_DIR"):
                del os.environ[name]
        os.environ["AGENT_STATE_DIR"] = os.path.join(self.tmp, "state")

    @staticmethod
    def _restore_env(saved):
        os.environ.clear()
        os.environ.update(saved)

    def write(self, relative, text="x\n"):
        path = os.path.join(self.tmp, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def lint_text(self, text, **kwargs):
        return ad_rules.lint_rules(self.write("CLAUDE.md", text), **kwargs)

    def kinds(self, text):
        return [(finding["line"], finding["kind"]) for finding in self.lint_text(text)["findings"]]


class FindRuleFilesTests(RulesCase):

    def test_finds_every_supported_file_and_skips_the_rest(self):
        wanted = ["CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md", ".claude/rules/style.md",
                  ".claude/rules/api/errors.md", "AGENTS.md", "GEMINI.md", ".cursorrules",
                  ".cursor/rules/base.mdc", ".windsurfrules", ".github/copilot-instructions.md",
                  "packages/api/CLAUDE.md"]
        unwanted = ["README.md", "docs/rules/style.md", "docs/copilot-instructions.md", "notes.mdc",
                    "node_modules/pkg/CLAUDE.md", ".git/CLAUDE.md", ".venv/lib/AGENTS.md", "venv/AGENTS.md",
                    "dist/CLAUDE.md", "build/CLAUDE.md", ".claude/worktrees/w1/CLAUDE.md",
                    ".claude/skills/x/SKILL.md", "a/b/c/d/e/CLAUDE.md"]
        for relative in wanted + unwanted:
            self.write(relative)
        found = [os.path.relpath(path, self.tmp) for path in ad_rules.find_rule_files(self.tmp)]
        self.assertEqual(sorted(found), sorted(wanted))

    def test_depth_does_not_depend_on_how_root_is_spelled(self):
        self.write("a/b/c/d/CLAUDE.md")
        self.write("a/b/c/d/e/CLAUDE.md")
        for root in (self.tmp, self.tmp + "/", os.path.join(self.tmp, "a", "..")):
            with self.subTest(root=root):
                self.assertEqual(len(ad_rules.find_rule_files(root)), 1)

    def test_symlinked_directories_are_not_followed_and_files_are_listed_once(self):
        real = self.write("CLAUDE.md")
        os.makedirs(os.path.join(self.tmp, "outside"))
        self.write("outside/AGENTS.md")
        os.symlink(os.path.join(self.tmp, "outside"), os.path.join(self.tmp, "linked"))
        os.symlink(real, os.path.join(self.tmp, "CLAUDE.local.md"))
        found = [os.path.relpath(path, self.tmp) for path in ad_rules.find_rule_files(self.tmp)]
        self.assertEqual(found, ["CLAUDE.md", "outside/AGENTS.md"])

    def test_a_file_argument_is_returned_as_is(self):
        path = self.write("docs/team-rules.md")
        self.assertEqual(ad_rules.find_rule_files(path), [path])
        self.assertEqual(ad_rules.find_rule_files(os.path.join(self.tmp, "missing")), [])


RULE_LINES = [
    # (rule line, expected kinds, expected blockable labels)
    ("- Do not remove the directory listing from the README.", ["negative-only"], []),
    ("- Never delete the files in tests/fixtures; tests depend on them.", ["negative-only"], []),
    ("- Never push a commit without running the main test suite.", ["negative-only"], []),
    ("- Do not commit code that breaks the main build.", ["negative-only"], []),
    ("- Avoid committing large binaries; the master copy lives in S3.", ["negative-only"], []),
    ("- Do not put secrets in logs.", ["negative-only"], []),
    ("- Never connect to the production database from tests.", ["negative-only"], []),
    ("- Don't publish draft posts from the CMS package.", ["negative-only"], []),
    ("- Never commit secrets or API keys.", ["negative-only"], []),
    ("- Never edit existing migrations.", ["negative-only"], []),
    ("- You must not skip code review.", ["negative-only"], []),
    ("- Under no circumstances share customer data.", ["negative-only"], []),
    ("- Don’t log request bodies.", ["negative-only"], []),
    ("- Direct database access from views is prohibited.", ["negative-only"], []),
    ("- IMPORTANT: never bypass the linter.", ["negative-only"], []),
    ("- Do not use `git push -f`.", ["blockable"], ["force push"]),
    ("- Don't force-push to shared branches.", ["blockable"], ["force push"]),
    ("- Never run `git reset --hard` or `terraform destroy`.", ["blockable", "blockable"],
     ["hard reset", "command `terraform destroy`"]),
    ("- Never push directly to main.", ["blockable"], ["push to protected branch"]),
    ("- Never run rm -rf outside build/.", ["blockable"], ["recursive delete"]),
    ("- Never run npm publish; use the release workflow instead.", ["blockable"], ["package publish"]),
    ("- Do not run `kubectl delete` against the shared cluster.", ["blockable"], ["command `kubectl delete`"]),
    ("- Never DROP TABLE without a reviewed migration.", ["blockable"], ["destructive SQL"]),
    ("- Never deploy to production from a laptop.", ["blockable"], ["production deploy"]),
    ("- Use the error helpers in src/lib/errors.ts, never throw raw strings.", [], []),
    ("- Never use `var`; use `const` instead.", [], []),
    ("- Do not hand-edit `dist/`; run `npm run build` instead.", [], []),
    ("- Prefer pnpm; avoid adding a second lockfile only when CI needs it.", [], []),
    ("- Run `npm test` before every commit.", [], []),
    ("- No trailing whitespace.", [], []),
    ("- Keep functions short so we never need long comments.", [], []),
    ("- Tests to avoid flakiness: mock the clock.", [], []),
    ("- Be careful with migrations.", ["vague"], []),
    ("- Use best judgment when naming things.", ["vague"], []),
    ("- Add logging as appropriate.", ["vague"], []),
    ("- Refactor when needed.", ["vague"], []),
    ("- Try to keep PRs small.", ["vague"], []),
    ("- Cache results if possible.", ["vague"], []),
    ("- Add types where applicable.", ["vague"], []),
    ("- Try to run `make lint` first.", [], []),
]


class LintTests(RulesCase):

    def test_rule_line_classification(self):
        for line, expected_kinds, expected_labels in RULE_LINES:
            with self.subTest(line=line):
                result = self.lint_text("# Rules\n\n" + line + "\n")
                self.assertEqual([finding["kind"] for finding in result["findings"]], expected_kinds)
                self.assertEqual([hook["label"] for hook in result["hooks"]], expected_labels)
                for finding in result["findings"]:
                    self.assertEqual(finding["line"], 3)

    def test_blockable_rule_lists_the_rules_it_compiles_to(self):
        hook = self.lint_text("- Do not use `git push -f`.\n")["hooks"][0]
        self.assertEqual(hook["line"], 1)
        self.assertIn("Bash(git push --force *)", hook["deny"])
        self.assertIn("Bash(git push -f *)", hook["deny"])
        self.assertTrue(hook["deny_regex"])
        self.assertIn("git push -f", hook["rule"])
        hook = self.lint_text("- Never run `terraform destroy`.\n")["hooks"][0]
        self.assertEqual(hook["deny"], ["Bash(terraform destroy)", "Bash(terraform destroy *)"])

    def test_only_commands_after_the_negation_are_blocked(self):
        hooks = self.lint_text("- Use `pnpm install`, never `npm install`.\n")["hooks"]
        self.assertEqual([hook["label"] for hook in hooks], ["command `npm install`"])
        self.assertEqual(self.lint_text("- Never edit `src/generated/` or `.env`.\n")["hooks"], [])

    def test_size_finding_uses_200_lines_and_no_statistic(self):
        self.assertEqual(self.kinds("- Run `make test`.\n" + "\n" * 199), [])
        result = self.lint_text("- Run `make test`.\n" + "\n" * 200)
        self.assertEqual([(finding["line"], finding["kind"]) for finding in result["findings"]], [(0, "size")])
        message = result["findings"][0]["message"]
        self.assertIn("201 lines", message)
        self.assertIn("200", message)
        self.assertNotIn("%", message)
        self.assertEqual(self.lint_text("a\nb\nc\n", max_lines=2)["findings"][0]["kind"], "size")

    def test_duplicates_are_reported_at_the_later_line(self):
        text = "- Run `make test` before every commit.\n\n- run  `make test` before every commit\n- Short.\n- Short.\n"
        result = self.lint_text(text)
        self.assertEqual([(finding["line"], finding["kind"]) for finding in result["findings"]], [(3, "duplicate")])
        self.assertIn("line 1", result["findings"][0]["message"])

    def test_headings_code_and_front_matter_are_not_linted(self):
        text = ("---\npaths: never/**\ndescription: do not be careful\n---\n"
                "# Never do this\n\n## Things to avoid\n\n"
                "```bash\n# never run this: be careful\nrm -rf build/\n```\n\n"
                "    never indent code like this, be careful\n\n"
                "~~~\nDo not push --force\n~~~\n")
        result = self.lint_text(text)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["hooks"], [])

    def test_official_style_sample_file_is_clean(self):
        text = ("# Code style\n- Use ES modules (import/export) syntax, not CommonJS (require)\n"
                "- Destructure imports when possible (eg. import { foo } from 'bar')\n\n"
                "# Workflow\n- Be sure to typecheck when you're done making a series of code changes\n"
                "- Prefer running single tests, and not the whole test suite, for performance\n"
                "- Use the error helpers in src/lib/errors.ts, never throw raw strings\n")
        self.assertEqual(self.lint_text(text)["findings"], [])

    def test_unreadable_file_becomes_a_finding(self):
        result = ad_rules.lint_rules(os.path.join(self.tmp, "missing", "CLAUDE.md"))
        self.assertEqual([finding["kind"] for finding in result["findings"]], ["unreadable"])
        self.assertEqual(result["hooks"], [])
        binary = os.path.join(self.tmp, "AGENTS.md")
        with open(binary, "wb") as handle:
            handle.write(b"- Never \xff commit secrets.\n")
        self.assertEqual([finding["kind"] for finding in ad_rules.lint_rules(binary)["findings"]], ["negative-only"])

    def test_result_shape(self):
        result = self.lint_text("- Never push directly to main.\n")
        self.assertEqual(sorted(result), ["file", "findings", "hooks", "lines", "rewrites"])
        self.assertEqual(result["lines"], 1)
        self.assertEqual(sorted(result["findings"][0]), ["kind", "line", "message"])
        self.assertEqual(result["rewrites"][0]["line"], 1)


class RewriteTemplateTests(RulesCase):

    def test_template_shows_the_original_and_never_invents_the_action(self):
        cases = [
            ("- Never commit secrets or API keys.", "When <trigger>, do <positive action>; check <observable>."),
            ("- Do not use `git push -f`.", "When about to run `git push -f`, do <positive action>"),
            ("- Never run `terraform destroy`.", "When about to run `terraform destroy`, do <positive action>"),
            ("- Never edit `migrations/`.", "When about to change `migrations/`, do <positive action>"),
            ("- Never push directly to main.", "When about to push to main or master, do <positive action>"),
            ("1. **Don't** force-push to shared branches.", "When about to force-push, do <positive action>"),
        ]
        for line, expected in cases:
            with self.subTest(line=line):
                template = ad_rules.rewrite_template(line)
                self.assertIn(expected, template)
                self.assertIn("original: ", template)
                self.assertIn("check <observable>.", template)
                self.assertNotIn("\n", template)
                self.assertNotIn("ask once", template)

    def test_non_prohibitions_give_none(self):
        for line in ("- Run `npm test` before every commit.", "- Use X, never Y.", "# Never do this", "", "```",
                     "- Keep functions short so we never need long comments.", None, 5):
            with self.subTest(line=line):
                self.assertIsNone(ad_rules.rewrite_template(line))


RULES_FILE = """# Project rules
- Do not use `git push -f`.
- Never push directly to main.
- Never run rm -rf outside build/.
- Never run npm publish; use the release workflow instead.
- Never run `git reset --hard` or `terraform destroy`.
- Never DROP TABLE without a reviewed migration.
- Never deploy to production from a laptop.
- Never commit secrets or API keys.
"""

# (command, denied by the compiled hook)
HOOK_MATRIX = [
    ("git push --force origin feat", True),
    ("git push -f origin feat", True),
    ("git push origin feat --force", True),
    ("git push origin +feat", True),
    ("git -C . push --force origin feat", True),
    ("cd repo && git push -f", True),
    ("git push --force-with-lease origin feat", False),
    ("git push --force-if-includes origin feat", False),
    ("git push origin feat", False),
    ("git push origin main", True),
    ("git push -u origin main", True),
    ("git push origin HEAD:main", True),
    ("git push origin master", True),
    ("git push origin main-nav-fix", False),
    ("git push origin feature/main-menu", False),
    ("rm -rf build/", True),
    ("rm -R build/", True),
    ("rm -Rf build/", True),
    ("rm -f -r build/", True),
    ("rm --recursive --force build/", True),
    ("sudo rm -rf /var/cache/x", True),
    ("/bin/rm -rf build", True),
    ("make clean; rm -fr dist", True),
    ("rm build/output.txt", False),
    ("rm -f build/output.txt", False),
    ("git rm -r --cached .", False),
    ("grep -rn 'rm -rf' scripts/", False),
    ("git commit -m 'docs: explain why rm -rf is banned'", False),
    ("npm publish", True),
    ("npm publish --access public", True),
    ("yarn publish", True),
    ("npm publish --dry-run", False),
    ("npm run publish-docs", False),
    ("git reset --hard", True),
    ("git reset --hard HEAD~1", True),
    ("git reset --soft HEAD~1", False),
    ("terraform destroy", True),
    ("terraform destroy -auto-approve", True),
    ("terraform plan -destroy", False),
    ("echo terraform destroy", False),
    ("psql -c 'DROP TABLE users;'", True),
    ("psql -c 'drop schema public cascade;'", True),
    ("psql -c 'TRUNCATE orders;'", True),
    ("psql -c 'select 1'", False),
    ("grep -rn 'DROP TABLE' migrations", False),
    ("vercel --prod", True),
    ("vercel deploy --prebuilt --prod", True),
    ("netlify deploy --dir=dist --prod", True),
    ("vercel deploy", False),
    ("ls -la", False),
    ("git status", False),
]


class CompileTests(RulesCase):

    def compiled(self, script_path=None):
        results = [ad_rules.lint_rules(self.write("CLAUDE.md", RULES_FILE))]
        return ad_rules.compile_rules(results, script_path=script_path)

    def driver(self, directory="driver"):
        return self.write(os.path.join(directory, "ad.py"), DRIVER % LIB)

    def run_emitted(self, compiled, payload, raw=None):
        """Run the emitted exec-form hook the way the host does: argv verbatim, hook input on stdin."""
        handler = compiled["hooks"]["PreToolUse"][0]["hooks"][0]
        self.assertEqual(handler["command"], "python3")
        argv = [sys.executable] + handler["args"]
        data = raw if raw is not None else json.dumps(payload).encode("utf-8")
        completed = subprocess.run(argv, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.tmp,
                                   env=dict(os.environ), timeout=60)
        output = completed.stdout.decode("utf-8").strip()
        return completed.returncode, (json.loads(output) if output else None), completed.stderr.decode("utf-8")

    def payload(self, command):
        return {"session_id": "abc123", "transcript_path": "/home/dev/.claude/projects/x/t.jsonl", "cwd": self.tmp,
                "permission_mode": "default", "hook_event_name": "PreToolUse", "tool_name": "Bash",
                "tool_input": {"command": command, "description": "never rm -rf or git push --force"},
                "tool_use_id": "toolu_01ABC"}

    def test_permissions_deny_entries(self):
        deny = self.compiled()["permissions"]["deny"]
        for rule in ("Bash(git push --force *)", "Bash(git push -f *)", "Bash(rm -rf *)", "Bash(npm publish *)",
                     "Bash(git push * main)", "Bash(git reset --hard *)", "Bash(terraform destroy *)",
                     "Bash(vercel --prod *)"):
            with self.subTest(rule=rule):
                self.assertIn(rule, deny)
        self.assertEqual(len(deny), len(set(deny)))
        for rule in deny:
            self.assertRegex(rule, r"^Bash\(.+\)$")

    def test_hook_fragment_is_exec_form_with_the_bootstrap(self):
        compiled = self.compiled(script_path="/opt/tools/ad.py")
        entry = compiled["hooks"]["PreToolUse"][0]
        self.assertEqual(entry["matcher"], "Bash")
        handler = entry["hooks"][0]
        self.assertEqual(handler["type"], "command")
        self.assertEqual(handler["command"], "python3")
        self.assertEqual(handler["args"][0], "-c")
        self.assertEqual(handler["args"][1],
                         "import os,runpy,sys; p=sys.argv[1]; sys.argv=sys.argv[1:]; "
                         "os.path.isfile(p) and runpy.run_path(p, run_name='__main__')")
        self.assertEqual(handler["args"][2:4], ["/opt/tools/ad.py", "deny-regex"])
        patterns = handler["args"][4:]
        self.assertGreaterEqual(len(patterns), 7)
        for pattern in patterns:
            self.assertNotIn("\\\\", pattern)
        self.assertIn("machine-specific", compiled["note"])
        self.assertEqual(len(compiled["sources"]), 8)
        json.dumps(compiled)

    def test_default_script_path_is_the_absolute_ad_py_next_to_the_module(self):
        handler = self.compiled()["hooks"]["PreToolUse"][0]["hooks"][0]
        self.assertEqual(handler["args"][2], AD)
        self.assertTrue(os.path.isabs(handler["args"][2]))

    def test_nothing_blockable_gives_empty_output(self):
        results = [ad_rules.lint_rules(self.write("CLAUDE.md", "- Never commit secrets.\n"))]
        compiled = ad_rules.compile_rules(results)
        self.assertEqual(compiled["permissions"], {"deny": []})
        self.assertEqual(compiled["hooks"], {})
        self.assertEqual(ad_rules.compile_rules([])["hooks"], {})

    def test_emitted_hook_denies_and_allows_per_matrix(self):
        compiled = self.compiled(script_path=self.driver())
        for command, denied in HOOK_MATRIX:
            with self.subTest(command=command):
                code, output, _ = self.run_emitted(compiled, self.payload(command))
                self.assertEqual(code, 0)
                if denied:
                    decision = output["hookSpecificOutput"]
                    self.assertEqual(decision["hookEventName"], "PreToolUse")
                    self.assertEqual(decision["permissionDecision"], "deny")
                    self.assertIn("compiled rule", decision["permissionDecisionReason"])
                else:
                    self.assertIsNone(output)

    @unittest.skipUnless(os.path.isfile(AD), "ad.py is not present")
    def test_emitted_hook_runs_through_the_real_cli(self):
        compiled = self.compiled()
        code, output, _ = self.run_emitted(compiled, self.payload("git push -f origin feat"))
        self.assertEqual(code, 0)
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.run_emitted(compiled, self.payload("git status"))[:2], (0, None))

    def test_missing_script_exits_0_and_blocks_nothing(self):
        compiled = self.compiled(script_path=os.path.join(self.tmp, "gone", "ad.py"))
        code, output, _ = self.run_emitted(compiled, self.payload("rm -rf /"))
        self.assertEqual((code, output), (0, None))
        compiled = self.compiled(script_path="${CLAUDE_PLUGIN_ROOT}/lib/ad.py")
        self.assertEqual(self.run_emitted(compiled, self.payload("ls"))[:2], (0, None))

    def test_script_path_with_a_space_works(self):
        compiled = self.compiled(script_path=self.driver("my tools"))
        code, output, _ = self.run_emitted(compiled, self.payload("terraform destroy"))
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.run_emitted(compiled, self.payload("ls"))[:2], (0, None))

    def test_hook_is_fail_open_on_bad_input_and_other_tools(self):
        compiled = self.compiled(script_path=self.driver())
        for raw in (b"", b"not json", b"[]", b'{"tool_input": "rm -rf /"}', b'{"tool_input": {"command": 5}}',
                    b'{"tool_name": "Write", "tool_input": {"file_path": "/x", "content": "rm -rf /"}}'):
            with self.subTest(raw=raw):
                code, output, stderr = self.run_emitted(compiled, None, raw=raw)
                self.assertEqual((code, output), (0, None))
                self.assertNotIn("Traceback", stderr)

    def test_invalid_pattern_is_skipped_with_a_note(self):
        script = self.driver()
        argv = [sys.executable, "-c", ad_rules.HOOK_BOOTSTRAP, script, "deny-regex", "(", r"^ls\b"]
        completed = subprocess.run(argv, input=json.dumps(self.payload("ls -la")).encode("utf-8"),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(completed.returncode, 0)
        self.assertIn(b"skipping invalid pattern", completed.stderr)
        self.assertIn(b'"deny"', completed.stdout)

    def test_denial_text_redacts_secrets(self):
        compiled = self.compiled(script_path=self.driver())
        command = "API_TOKEN=abc123secretvalue git push --force 'https://user:hunter2pass@example.org/r.git'; git push -f"
        _, output, _ = self.run_emitted(compiled, self.payload(command))
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertNotIn("hunter2pass", reason)


def git(repo, *args):
    """Run git in a temp repository with a fixed identity, independent of the user's configuration."""
    environment = dict(os.environ)
    environment.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                        "GIT_CONFIG_NOSYSTEM": "1"})
    command = ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
               "-c", "init.defaultBranch=trunk"] + list(args)
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, timeout=60)
    if completed.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), completed.stderr.decode("utf-8", "replace")))
    return completed.stdout.decode("utf-8")


@unittest.skipUnless(HAS_GIT, "git is not installed")
class ChangedFilesTests(RulesCase):

    def setUp(self):
        RulesCase.setUp(self)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q")
        for relative in ("src/parser.py", "src/old.py", "tests/test_parser.py", "tests/test_old.py", "README.md"):
            self.commit_file(relative, add_only=True)
        git(self.repo, "commit", "-q", "-m", "initial")
        git(self.repo, "branch", "base")

    def path(self, relative):
        return os.path.join(self.repo, relative)

    def put(self, relative, text="changed\n"):
        os.makedirs(os.path.dirname(self.path(relative)), exist_ok=True)
        with open(self.path(relative), "w", encoding="utf-8") as handle:
            handle.write(text)

    def commit_file(self, relative, add_only=False):
        self.put(relative, "original %s\n" % relative)
        git(self.repo, "add", "--", relative)
        if not add_only:
            git(self.repo, "commit", "-q", "-m", "add " + relative)

    def test_clean_tree_has_no_changes(self):
        self.assertEqual(ad_rules.changed_files(root=self.repo), ([], []))

    def test_unstaged_staged_untracked_and_deleted(self):
        self.put("src/parser.py")
        self.put("src/staged.py")
        git(self.repo, "add", "src/staged.py")
        self.put("src/new file with spaces.py")
        self.put("src/café.py")
        os.remove(self.path("src/old.py"))
        git(self.repo, "rm", "-q", "tests/test_old.py")
        changed, deleted = ad_rules.changed_files(root=self.repo)
        self.assertEqual(changed, sorted(["src/parser.py", "src/staged.py", "src/new file with spaces.py",
                                          "src/café.py"]))
        self.assertEqual(deleted, ["src/old.py", "tests/test_old.py"])

    def test_ignored_files_are_not_listed(self):
        self.put(".gitignore", "*.log\n")
        self.put("debug.log")
        self.assertEqual(ad_rules.changed_files(root=self.repo)[0], [".gitignore"])

    def test_committed_work_shows_only_with_a_base(self):
        self.commit_file("src/feature.py")
        self.assertEqual(ad_rules.changed_files(root=self.repo), ([], []))
        self.assertEqual(ad_rules.changed_files(base="base", root=self.repo), (["src/feature.py"], []))
        self.put("src/parser.py")
        self.assertEqual(ad_rules.changed_files(base="base", root=self.repo)[0], ["src/feature.py", "src/parser.py"])

    def test_rename_lists_the_new_name_as_changed_and_the_old_as_deleted(self):
        git(self.repo, "mv", "src/old.py", "src/renamed.py")
        self.assertEqual(ad_rules.changed_files(root=self.repo), (["src/renamed.py"], ["src/old.py"]))

    def test_root_in_a_subdirectory_gives_paths_relative_to_it(self):
        self.put("src/parser.py")
        self.put("tests/test_parser.py")
        changed, _ = ad_rules.changed_files(root=self.path("src"))
        self.assertEqual(changed, ["../tests/test_parser.py", "parser.py"])

    def test_repository_without_commits(self):
        fresh = os.path.join(self.tmp, "fresh")
        os.makedirs(fresh)
        git(fresh, "init", "-q")
        with open(os.path.join(fresh, "a.py"), "w") as handle:
            handle.write("x\n")
        with open(os.path.join(fresh, "b.py"), "w") as handle:
            handle.write("x\n")
        git(fresh, "add", "a.py")
        self.assertEqual(ad_rules.changed_files(root=fresh), (["a.py", "b.py"], []))

    def test_outside_a_repository_raises_a_clear_error(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        environment_ceiling = os.environ.get("GIT_CEILING_DIRECTORIES")
        os.environ["GIT_CEILING_DIRECTORIES"] = self.tmp
        self.addCleanup(os.environ.pop, "GIT_CEILING_DIRECTORIES", None)
        self.assertIsNone(environment_ceiling)
        with self.assertRaises(ValueError) as caught:
            ad_rules.changed_files(root=plain)
        self.assertIn("not a git repository", str(caught.exception))
        with self.assertRaises(ValueError):
            ad_rules.changed_files(root=os.path.join(self.tmp, "missing"))

    def test_option_like_or_unknown_base_is_rejected_and_writes_nothing(self):
        victim = self.path("victim.txt")
        for base in ("--output=" + victim, "--output=victim.txt", "-p", "no-such-ref", "", "base; touch x"):
            with self.subTest(base=base):
                with self.assertRaises(ValueError):
                    ad_rules.changed_files(base=base, root=self.repo)
        self.assertFalse(os.path.exists(victim))
        self.assertEqual(ad_rules.changed_files(root=self.repo), ([], []))

    @unittest.skipUnless(os.path.isfile(AD), "ad.py is not present")
    def test_cli_exit_codes(self):
        def run(*args):
            return subprocess.run([sys.executable, AD, "test-impact"] + list(args), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, cwd=self.repo, env=dict(os.environ), timeout=60)
        clean = run()
        self.assertEqual(clean.returncode, 0)
        self.assertEqual(json.loads(clean.stdout.decode("utf-8"))["advice"], "no changes detected")
        self.put("src/parser.py")
        mapped = json.loads(run("--root", self.repo).stdout.decode("utf-8"))
        self.assertEqual(mapped["run"], ["tests/test_parser.py"])
        bad = run("--base=--output=victim.txt")
        self.assertEqual(bad.returncode, 2)
        self.assertNotIn(b"Traceback", bad.stderr)
        self.assertFalse(os.path.exists(self.path("victim.txt")))
        os.environ["GIT_CEILING_DIRECTORIES"] = self.tmp
        self.addCleanup(os.environ.pop, "GIT_CEILING_DIRECTORIES", None)
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        outside = run("--root", plain)
        self.assertEqual(outside.returncode, 2)
        self.assertIn(b"not a git repository", outside.stderr)


TEST_FILES = [
    "tests/test_parser.py", "pkg/lexer_test.py",
    "web/src/Button.test.tsx", "web/src/api.spec.ts", "web/src/__tests__/store.js", "web/cart.test.mjs",
    "go/pkg/server_test.go",
    "rust/tests/integration.rs",
    "java/src/test/java/UserServiceTest.java", "java/src/test/java/OrderTests.java", "kt/RepoTest.kt",
    "ruby/spec/user_spec.rb", "ruby/test/order_test.rb",
    "cs/BillingTests.cs", "php/tests/InvoiceTest.php", "swift/Tests/AppTests/LoginTests.swift",
]
NOT_TEST_FILES = [
    "src/parser.py", "src/latest.py", "src/contest.py", "conftest.py", "tests/fixtures/data.json",
    "tests/helpers.py", "web/src/Button.tsx", "web/src/testing-utils.ts", "web/src/__tests__/snapshot.snap",
    "go/pkg/server.go", "rust/src/lib.rs", "rust/src/tests_support.rs", "java/src/main/java/UserService.java",
    "java/src/main/java/Contest.java", "ruby/lib/user.rb", "cs/Billing.cs", "docs/testing.md",
    "node_modules/pkg/index.test.js", ".venv/lib/test_x.py", "dist/app.test.js",
]


class DiscoverTests(RulesCase):

    def test_conventions_per_language(self):
        for relative in TEST_FILES + NOT_TEST_FILES:
            self.write(relative)
        self.assertEqual(ad_rules.discover_tests(self.tmp), sorted(TEST_FILES))

    def test_empty_tree(self):
        self.assertEqual(ad_rules.discover_tests(self.tmp), [])


class TestImpactTests(RulesCase):

    def setUp(self):
        RulesCase.setUp(self)
        self.write("src/parser.py", "def parse(): pass\n")
        self.write("src/tokenizer.py", "def tokens(): pass\n")
        self.write("src/billing.py")
        self.write("src/io.py")
        self.write("src/utils.py")
        self.write("src/index.ts")
        self.write("src/UserService.java")
        self.write("tests/test_parser.py", "from src.parser import parse\n")
        self.write("tests/test_cli.py", "from src import tokenizer, utils, io\nimport index\n")
        self.write("tests/test_parser_errors.py", "import pytest\n")
        self.write("tests/test_misc.py", "x = 'billing_address'\n")
        self.write("java/UserServiceTest.java", "class UserServiceTest {}\n")
        self.write("web/app.test.ts", "import { something } from './parser-utils'\n")

    def impact(self, files, deleted=None):
        return ad_rules.test_impact(files, root=self.tmp, deleted=deleted)

    def test_output_keys(self):
        result = self.impact(["src/parser.py"])
        for key in ("changed", "deleted", "run", "full_suite_reason", "unmapped", "skipped_count", "total_tests",
                    "advice"):
            with self.subTest(key=key):
                self.assertIn(key, result)
        json.dumps(result)

    def test_no_changes(self):
        result = self.impact([])
        self.assertEqual(result["advice"], "no changes detected")
        self.assertEqual(result["run"], [])
        self.assertEqual(result["skipped_count"], result["total_tests"])
        self.assertEqual(result["total_tests"], 6)

    def test_source_maps_by_whole_word_name(self):
        result = self.impact(["src/parser.py"])
        self.assertEqual(result["run"], ["tests/test_parser.py", "tests/test_parser_errors.py", "web/app.test.ts"])
        self.assertEqual(result["mapped"]["src/parser.py"][0], {"test": "tests/test_parser.py", "basis": "name"})
        self.assertEqual(result["mapped"]["src/parser.py"][2]["basis"], "content")
        self.assertEqual(result["unmapped"], [])
        self.assertIsNone(result["full_suite_reason"])
        self.assertEqual(result["skipped_count"], 3)
        self.assertIn("3 mapped test file(s)", result["advice"])
        self.assertIn("full suite before merging", result["advice"])

    def test_source_maps_by_content_reference(self):
        result = self.impact(["src/tokenizer.py"])
        self.assertEqual(result["run"], ["tests/test_cli.py"])
        self.assertEqual(result["mapped"]["src/tokenizer.py"], [{"test": "tests/test_cli.py", "basis": "content"}])

    def test_camel_case_test_names(self):
        self.assertEqual(self.impact(["src/UserService.java"])["run"], ["java/UserServiceTest.java"])

    def test_substring_is_not_a_match(self):
        result = self.impact(["src/billing.py"])
        self.assertEqual(result["run"], [])
        self.assertEqual(result["unmapped"], ["src/billing.py"])
        self.assertIn("src/billing.py", result["advice"])
        self.assertIn("full suite", result["advice"])
        self.assertNotIn("add", result["advice"])

    def test_short_and_generic_stems_do_not_match(self):
        result = self.impact(["src/io.py", "src/utils.py", "src/index.ts"])
        self.assertEqual(result["run"], [])
        self.assertEqual(result["unmapped"], ["src/index.ts", "src/io.py", "src/utils.py"])

    def test_changed_test_runs_itself(self):
        result = self.impact(["tests/test_cli.py"])
        self.assertEqual(result["run"], ["tests/test_cli.py"])
        self.assertEqual(result["unmapped"], [])

    def test_deleted_files_are_listed_and_never_run(self):
        result = self.impact(["src/parser.py"], deleted=["tests/test_gone.py", "src/removed.py"])
        self.assertEqual(result["deleted"], ["src/removed.py", "tests/test_gone.py"])
        self.assertNotIn("tests/test_gone.py", result["run"])
        self.assertEqual(result["unmapped"], [])
        only_deleted = self.impact([], deleted=["src/tokenizer.py"])
        self.assertEqual(only_deleted["run"], ["tests/test_cli.py"])
        self.assertNotEqual(only_deleted["advice"], "no changes detected")

    def test_shared_or_configuration_change_sets_full_suite_reason(self):
        for path in ("package.json", "pnpm-lock.yaml", "pyproject.toml", "poetry.lock", "requirements-dev.txt",
                     "Cargo.lock", "go.sum", "tsconfig.build.json", "jest.config.js", "conftest.py",
                     "tests/conftest.py", "Makefile", "Dockerfile", ".github/workflows/ci.yml",
                     "tests/fixtures/users.json", "tests/helpers/factory.py", "services/api/package.json"):
            with self.subTest(path=path):
                result = self.impact([path, "src/parser.py"])
                self.assertIn(path, result["full_suite_reason"])
                self.assertTrue(result["advice"].startswith("run the full suite"))
                self.assertIn("tests/test_parser.py", result["run"])

    def test_docs_and_feature_code_do_not_trigger_the_full_suite(self):
        for path in ("README.md", "docs/webpack-migration.md", ".github/ISSUE_TEMPLATE/bug.md", "src/lib/feature.py",
                     "docs/Makefile.md", "assets/logo.png"):
            with self.subTest(path=path):
                self.assertIsNone(self.impact([path])["full_suite_reason"])
        result = self.impact(["README.md", "docs/guide.rst"])
        self.assertEqual(result["advice"], "no source or test file changed; no tests selected")
        self.assertEqual(result["unmapped"], [])

    def test_each_test_file_is_read_once(self):
        opened = []
        original = ad_rules._TestContents.get

        def counting(contents, test_path):
            if test_path not in contents.cache:
                opened.append(test_path)
            return original(contents, test_path)

        ad_rules._TestContents.get = counting
        self.addCleanup(setattr, ad_rules._TestContents, "get", original)
        sources = []
        for index in range(30):
            name = "src/module_%02d.py" % index
            self.write(name)
            sources.append(name)
        self.impact(sources)
        self.assertEqual(len(opened), len(set(opened)))
        self.assertLessEqual(len(opened), 6)

    def test_is_not_collected_as_a_test(self):
        self.assertFalse(ad_rules.test_impact.__test__)


if __name__ == "__main__":
    unittest.main()
