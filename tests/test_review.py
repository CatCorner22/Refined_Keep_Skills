"""Backward review: the review record parser, the review gate, its CLI and its 4 hooks."""
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
AD = os.path.join(LIB, "ad.py")
sys.path.insert(0, LIB)

import ad_gates  # noqa: E402

RECORD = "Backward review: 4 parts, last to first; forward re-read done. Corrections: none."
EVIDENCE = ("Acceptance: unit tests green\nCommand: npm test\nOutput: 48 passing (2m)\n"
            "Diff: src/app.ts\nNot verified: Safari\n")


class EnvCase(unittest.TestCase):
    def setUp(self):
        self.saved = {name: os.environ.pop(name, None) for name in ("AD_REVIEW", "AD_REVIEW_MIN_CHARS", "AD_GATE")}
        self.addCleanup(self.restore)

    def restore(self):
        for name, value in self.saved.items():
            os.environ.pop(name, None)
            if value is not None:
                os.environ[name] = value


class RecordTests(EnvCase):
    def test_complete_record_passes(self):
        self.assertIsNone(ad_gates.review_gate_decide("The answer is 4.\n\n" + RECORD))

    def test_record_behind_markup_and_in_any_case_passes(self):
        for line in ("**Backward review:** 1 part, last to first; forward re-read done. Corrections: none.",
                     "- backward review: 12 parts, last to first; forward reread done. Corrections: fixed step 3",
                     "_Backward review_: 2 parts, last-to-first; forward re-read done. Correction: swapped steps 1 and 2"):
            self.assertIsNone(ad_gates.review_gate_decide("Text.\n" + line), line)

    def test_corrections_on_the_next_line_pass(self):
        message = "Text.\nBackward review: 3 parts, last to first; forward re-read done.\nCorrections: none"
        self.assertIsNone(ad_gates.review_gate_decide(message))

    def test_missing_record_blocks_with_the_template(self):
        reason = ad_gates.review_gate_decide("The answer is 4.")
        self.assertIn("no review record", reason)
        self.assertIn(ad_gates.REVIEW_TEMPLATE, reason)
        self.assertIn("once per stop attempt", reason)

    def test_each_missing_element_is_named(self):
        cases = (
            ("Backward review: last to first; forward re-read done. Corrections: none", "number of parts"),
            ("Backward review: 0 parts, last to first; forward re-read done. Corrections: none", "number of parts"),
            ("Backward review: 3 parts; forward re-read done. Corrections: none", "last to first"),
            ("Backward review: 3 parts, last to first. Corrections: none", "forward re-read"),
            ("Backward review: 3 parts, last to first. Corrections: I re-read it", "forward re-read"),
            ("Backward review: 3 parts, last to first; forward re-read done.", "`Corrections:` value"),
            ("Backward review: 3 parts, last to first; forward re-read done. Corrections:", "placeholder"),
            ("Backward review: 3 parts, last to first; forward re-read done. Corrections: <what you corrected, or none>",
             "placeholder"),
            ("Backward review: 3 parts, last to first; forward re-read done. Corrections: TBD", "placeholder"),
        )
        for record, expected in cases:
            reason = ad_gates.review_gate_decide("Text.\n" + record)
            self.assertIsNotNone(reason, record)
            self.assertIn(expected, reason, record)

    def test_the_unfilled_template_does_not_pass(self):
        self.assertIsNotNone(ad_gates.review_gate_decide("Text.\n" + ad_gates.REVIEW_TEMPLATE))

    def test_a_record_inside_a_fence_or_a_quote_does_not_count(self):
        self.assertIsNotNone(ad_gates.review_gate_decide("Use this line:\n```\n%s\n```\n" % RECORD))
        self.assertIsNotNone(ad_gates.review_gate_decide("They wrote:\n> %s\n" % RECORD))

    def test_the_last_record_decides(self):
        bad = "Backward review: 3 parts. Corrections: none"
        self.assertIsNone(ad_gates.review_gate_decide("%s\n\nMore text.\n\n%s" % (bad, RECORD)))
        self.assertIsNotNone(ad_gates.review_gate_decide("%s\n\nMore text.\n\n%s" % (RECORD, bad)))

    def test_empty_and_non_text_messages_pass(self):
        for message in ("", "   \n", None, 7):
            self.assertIsNone(ad_gates.review_gate_decide(message))

    def test_off_switch(self):
        os.environ["AD_REVIEW"] = "OFF"
        self.assertIsNone(ad_gates.review_gate_decide("The answer is 4."))

    def test_minimum_length(self):
        os.environ["AD_REVIEW_MIN_CHARS"] = "200"
        self.assertIsNone(ad_gates.review_gate_decide("Short answer."))
        self.assertIsNotNone(ad_gates.review_gate_decide("Long answer. " * 40))
        os.environ["AD_REVIEW_MIN_CHARS"] = "not a number"
        self.assertIsNotNone(ad_gates.review_gate_decide("Short answer."))

    def test_plan_reason_names_the_plan(self):
        reason = ad_gates.review_gate_decide("1. Do A.\n2. Do B.", kind="plan", note="NEXT")
        self.assertIn("This plan has no review record", reason)
        self.assertTrue(reason.endswith("NEXT"))
        self.assertNotIn("already seen", reason)


class ProcessCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="ad-review-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(os.path.join(self.project, ".git"))
        self.state = os.path.join(self.tmp, "state")
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("AD_") and key not in ("AGENT_STATE_DIR", "CLAUDE_PROJECT_DIR")}
        self.env["AGENT_STATE_DIR"] = self.state
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"

    def run_ad(self, args, data=b"", env=None):
        environment = dict(self.env)
        environment.update(env or {})
        completed = subprocess.run([sys.executable, AD] + list(args), input=data, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=self.tmp, env=environment, timeout=60)
        return completed.returncode, completed.stdout.decode("utf-8", "replace"), completed.stderr.decode("utf-8", "replace")

    def hook(self, name, payload, env=None):
        code, out, _err = self.run_ad(["hook", name], json.dumps(payload).encode("utf-8"), env)
        return code, (json.loads(out) if out.strip() else None)

    def payload(self, event, **extra):
        data = {"session_id": "abc123", "cwd": self.project, "hook_event_name": event,
                "transcript_path": os.path.join(self.tmp, "t.jsonl"), "permission_mode": "default"}
        data.update(extra)
        return data


class CliTests(ProcessCase):
    def test_pass_and_block_exit_codes(self):
        self.assertEqual(self.run_ad(["review", "Text.\n" + RECORD])[:2], (0, "PASS\n"))
        code, out, _err = self.run_ad(["review", "Text."])
        self.assertEqual(code, 1)
        self.assertIn("no review record", out)
        self.assertNotIn("once per stop attempt", out)

    def test_file_stdin_and_plan(self):
        path = os.path.join(self.tmp, "plan.md")
        with open(path, "w") as handle:
            handle.write("1. A\n2. B\n")
        code, out, _err = self.run_ad(["review", "--plan", "--file", path])
        self.assertEqual(code, 1)
        self.assertIn("This plan has no review record", out)
        self.assertEqual(self.run_ad(["review"], ("Text.\n" + RECORD).encode("utf-8"))[:2], (0, "PASS\n"))

    def test_no_message_is_a_usage_error(self):
        code, _out, err = self.run_ad(["review"])
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("error:"))

    def test_review_creates_no_state_directory(self):
        self.run_ad(["review", "Text."])
        self.assertFalse(os.path.exists(self.state))


class HookTests(ProcessCase):
    def stop(self, message, active=False, event="Stop"):
        return self.payload(event, stop_hook_active=active, last_assistant_message=message)

    def test_review_gate_blocks_once(self):
        for event in ("Stop", "SubagentStop"):
            code, parsed = self.hook("review-gate", self.stop("The answer is 4.", event=event))
            self.assertEqual(code, 0)
            self.assertEqual(parsed["decision"], "block")
            self.assertIn("no review record", parsed["reason"])
            self.assertEqual(self.hook("review-gate", self.stop("The answer is 4.", active=True, event=event)), (0, None))

    def test_review_gate_passes_a_record_and_an_empty_message(self):
        self.assertEqual(self.hook("review-gate", self.stop("The answer is 4.\n" + RECORD)), (0, None))
        self.assertEqual(self.hook("review-gate", self.stop("")), (0, None))

    def test_off_switch_silences_every_review_hook(self):
        off = {"AD_REVIEW": "off"}
        self.assertEqual(self.hook("review-gate", self.stop("Text."), off), (0, None))
        self.assertEqual(self.hook("stop", self.stop("Text."), off), (0, None))
        self.assertEqual(self.hook("review-reminder", self.payload("UserPromptSubmit", prompt="hi"), off), (0, None))
        plan = self.payload("PreToolUse", tool_name="ExitPlanMode", tool_input={"plan": "1. A"})
        self.assertEqual(self.hook("pre-plan", plan, off), (0, None))

    def test_stop_joins_both_reasons(self):
        code, parsed = self.hook("stop", self.stop("All tests pass and the work is done."))
        self.assertEqual(code, 0)
        self.assertEqual(parsed["decision"], "block")
        self.assertIn("no review record", parsed["reason"])
        self.assertIn("evidence block", parsed["reason"])

    def test_stop_with_one_gate_satisfied(self):
        _code, parsed = self.hook("stop", self.stop("The work is done.\n" + EVIDENCE))
        self.assertIn("no review record", parsed["reason"])
        self.assertNotIn("evidence block", parsed["reason"])
        _code, parsed = self.hook("stop", self.stop("The work is done.\n\n" + RECORD))
        self.assertNotIn("no review record", parsed["reason"])
        self.assertIn("evidence block", parsed["reason"])

    def test_stop_passes_when_both_gates_are_satisfied(self):
        self.assertEqual(self.hook("stop", self.stop("The work is done.\n" + EVIDENCE + "\n" + RECORD)), (0, None))
        self.assertEqual(self.hook("stop", self.stop("Here is the status.\n" + RECORD)), (0, None))
        self.assertEqual(self.hook("stop", self.stop("The work is done.", active=True)), (0, None))

    def test_completion_gate_hook_is_unchanged(self):
        self.assertEqual(self.hook("completion-gate", self.stop("Here is the status.")), (0, None))

    def test_pre_plan_denies_a_plan_without_a_record(self):
        plan = self.payload("PreToolUse", tool_name="ExitPlanMode",
                            tool_input={"plan": "1. Do A.\n2. Do B.", "planFilePath": "/x/plan.md"})
        code, parsed = self.hook("pre-plan", plan)
        self.assertEqual(code, 0)
        output = parsed["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("This plan has no review record", output["permissionDecisionReason"])
        self.assertIn("call ExitPlanMode again", output["permissionDecisionReason"])

    def test_pre_plan_passes_a_plan_with_a_record(self):
        plan = self.payload("PreToolUse", tool_name="ExitPlanMode",
                            tool_input={"plan": "1. Do A.\n2. Do B.\n\n" + RECORD})
        self.assertEqual(self.hook("pre-plan", plan), (0, None))

    def test_pre_plan_without_plan_text_adds_the_reminder_and_does_not_deny(self):
        for tool_input in ({}, {"plan": ""}, {"plan": 7}, None):
            plan = self.payload("PreToolUse", tool_name="ExitPlanMode", tool_input=tool_input)
            code, parsed = self.hook("pre-plan", plan)
            self.assertEqual(code, 0)
            output = parsed["hookSpecificOutput"]
            self.assertNotIn("permissionDecision", output)
            self.assertIn("Standing rule", output["additionalContext"])

    def test_reminder_adds_context_for_every_prompt(self):
        code, parsed = self.hook("review-reminder", self.payload("UserPromptSubmit", prompt="hi"))
        self.assertEqual(code, 0)
        output = parsed["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "UserPromptSubmit")
        self.assertIn(ad_gates.REVIEW_TEMPLATE, output["additionalContext"])
        self.assertNotIn("decision", parsed)

    def test_review_hooks_create_no_state_directory(self):
        self.hook("review-gate", self.stop("Text."))
        self.hook("review-reminder", self.payload("UserPromptSubmit", prompt="hi"))
        self.hook("pre-plan", self.payload("PreToolUse", tool_name="ExitPlanMode", tool_input={"plan": "1. A"}))
        self.assertFalse(os.path.exists(self.state))

    def test_bad_input_never_fails(self):
        for name in ("review-gate", "stop", "pre-plan", "review-reminder"):
            code, _out, _err = self.run_ad(["hook", name], b"not json")
            self.assertEqual(code, 0, name)


if __name__ == "__main__":
    unittest.main()
