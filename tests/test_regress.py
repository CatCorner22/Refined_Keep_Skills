"""Tests for lib/ad_regress.py: the regression set, result rows and the scoreboard."""
import datetime
import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import ad_core  # noqa: E402
import ad_regress  # noqa: E402

START = datetime.datetime(2030, 10, 10, 9, 0, 0, tzinfo=datetime.timezone.utc)


class RegressCase(unittest.TestCase):
    """Base class: temp directory, own AGENT_STATE_DIR, injected clock."""

    @classmethod
    def setUpClass(cls):
        importlib.reload(ad_core)
        importlib.reload(ad_regress)

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="ad-regress-"))
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
        self.clock = START
        original_clock = ad_core.time_now
        ad_core.time_now = lambda: self.clock
        self.addCleanup(setattr, ad_core, "time_now", original_clock)

    @staticmethod
    def _restore_env(saved):
        os.environ.clear()
        os.environ.update(saved)

    def write_set(self, items):
        path = ad_regress.regress_init()
        with open(path, "w", encoding="utf-8") as handle:
            if isinstance(items, str):
                handle.write(items)
            else:
                json.dump(items, handle)
        return path

    def custom_set(self):
        keep = [item for item in ad_regress.DEFAULT_SET if item["id"] in ("F1-inventory", "F7-evidence")]
        mine = [{"id": "MY-1", "family": "mine", "turns": ["Do X."], "checks": ["X is done."]},
                {"id": "MY-2", "turns": ["Do Y."]}]
        return self.write_set(keep + mine)


class DefaultSetTests(RegressCase):
    def test_twelve_self_contained_items(self):
        # RR-09: every item carries its own setup, the turns to paste and yes/no checks.
        self.assertEqual(len(ad_regress.DEFAULT_SET), 12)
        ids = [item["id"] for item in ad_regress.DEFAULT_SET]
        self.assertEqual(len(set(ids)), 12)
        for item in ad_regress.DEFAULT_SET:
            self.assertTrue(item["family"], item["id"])
            self.assertTrue(item["setup"].strip(), item["id"])
            self.assertTrue(item["turns"], item["id"])
            self.assertTrue(item["checks"], item["id"])
            for turn in item["turns"]:
                self.assertFalse(turn.startswith("("), "turn starts with a precondition: " + item["id"])
            self.assertNotIn("fail_signals", item)

    def test_neutral_example_file(self):
        # The F1 item uses the neutral file name from the privacy table of the spec.
        first = ad_regress.DEFAULT_SET[0]
        self.assertEqual(first["turns"], ["My project has a file `annual_report.pdf`. Summarize section 3."])
        self.assertIn("annual_report.pdf", first["setup"])

    def test_default_set_is_valid_json_data(self):
        self.assertEqual(json.loads(json.dumps(ad_regress.DEFAULT_SET)), ad_regress.DEFAULT_SET)


class InitAndShowTests(RegressCase):
    def test_show_before_init_reads_defaults_and_writes_nothing(self):
        text = ad_regress.regress_show()
        self.assertIn("12 default items", text)
        self.assertIn("[F1-inventory] (resource blindness)", text)
        self.assertIn("  turn 1: My project has a file `annual_report.pdf`. Summarize section 3.", text)
        self.assertIn("  check 1:", text)
        self.assertIn("  setup:", text)
        self.assertFalse(os.path.exists(self.state))

    def test_init_creates_the_file_and_keeps_edits(self):
        path = ad_regress.regress_init()
        self.assertEqual(path, os.path.join(self.state, "regress", "set.json"))
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), ad_regress.DEFAULT_SET)
        self.custom_set()
        ad_regress.regress_init()
        self.assertIn("[MY-1] (mine)", ad_regress.regress_show())
        self.assertIn("4 items from", ad_regress.regress_show())

    def test_init_force_backs_up_the_users_set(self):
        # RR-21: `init --force` used to discard the user's items without a trace.
        path = self.custom_set()
        ad_regress.regress_init(force=True)
        backups = [name for name in os.listdir(os.path.dirname(path)) if name.endswith(".bak")]
        self.assertEqual(len(backups), 1)
        with open(os.path.join(os.path.dirname(path), backups[0]), encoding="utf-8") as handle:
            self.assertIn("MY-1", handle.read())
        self.assertIn("12 items from", ad_regress.regress_show())

    def test_show_tolerates_sparse_items_and_reports_problems(self):
        self.write_set([{"id": "X", "prompt": "old style prompt", "expect": "old style expectation"},
                        {"family": "no id"}, "junk", {"id": "X"}, {"id": "EMPTY"}])
        text = ad_regress.regress_show()
        self.assertIn("[X] (no family)", text)
        self.assertIn("turn 1: old style prompt", text)
        self.assertIn("check 1: old style expectation", text)
        self.assertIn("entry 2 has no id", text)
        self.assertIn("entry 3 has no id", text)
        self.assertIn("id X appears twice", text)
        self.assertIn("(this item has no turns)", text)

    def test_object_form_with_items_key(self):
        self.write_set({"version": 2, "items": [{"id": "ONLY", "turns": ["t"]}]})
        self.assertIn("1 items from", ad_regress.regress_show())

    def test_invalid_json_is_a_clear_error(self):
        self.write_set('[{"id": "X", "prompt": "p"},]')
        for function in (ad_regress.regress_show, ad_regress.regress_report):
            with self.assertRaisesRegex(ValueError, "not valid JSON"):
                function()
        self.write_set('"just a string"')
        with self.assertRaisesRegex(ValueError, "JSON list"):
            ad_regress.regress_show()


class RecordTests(RegressCase):
    def test_row_shape(self):
        message = ad_regress.regress_record("F1-inventory", "pass", "model-a-2030", note="looked first")
        self.assertEqual(message, "recorded F1-inventory pass for model-a-2030")
        rows = ad_core.read_jsonl("regress/results.jsonl")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ts"], "2030-10-10T09:00:00+00:00")
        self.assertEqual((rows[0]["id"], rows[0]["result"], rows[0]["model"], rows[0]["note"]),
                         ("F1-inventory", "pass", "model-a-2030", "looked first"))
        self.assertRegex(rows[0]["item_hash"], r"^[0-9a-f]{12}$")

    def test_unknown_id_needs_force(self):
        # RR-08: a typo used to create a new item that counted as a pass.
        with self.assertRaisesRegex(ValueError, r"unknown item id F1-inventroy\. Closest ids: F1-inventory"):
            ad_regress.regress_record("F1-inventroy", "pass", "model-a")
        self.assertEqual(ad_core.read_jsonl("regress/results.jsonl"), [])
        message = ad_regress.regress_record("F1-inventroy", "pass", "model-a", force=True)
        self.assertIn("Warning: F1-inventroy is not in the set", message)
        self.assertEqual(len(ad_core.read_jsonl("regress/results.jsonl")), 1)

    def test_validation(self):
        for args in (("F1-inventory", "passed", "m"), ("F1-inventory", "", "m"),
                     ("", "pass", "m"), ("F1-inventory", "pass", ""), ("F1-inventory", "pass", "  \n")):
            with self.assertRaises(ValueError):
                ad_regress.regress_record(*args)
        self.assertFalse(os.path.exists(os.path.join(self.state, "regress", "results.jsonl")))

    def test_ids_come_from_the_users_set(self):
        self.custom_set()
        ad_regress.regress_record("MY-1", "partial", "m")
        with self.assertRaises(ValueError):
            ad_regress.regress_record("F2-reread", "pass", "m")

    def test_long_note_is_cut_with_notice(self):
        message = ad_regress.regress_record("F1-inventory", "fail", "m", note="n" * 1000)
        self.assertIn("note cut from 1000 to 300 characters", message)
        self.assertEqual(len(ad_core.read_jsonl("regress/results.jsonl")[0]["note"]), 300)

    def test_note_and_model_are_single_line(self):
        ad_regress.regress_record("F1-inventory", "pass", "model\nx", note="a\nb")
        self.assertEqual(len(ad_core.read_lines("regress/results.jsonl")), 1)
        self.assertEqual(ad_core.read_jsonl("regress/results.jsonl")[0]["model"], "model x")


class ReportTests(RegressCase):
    def test_no_results(self):
        self.assertIn("no results yet", ad_regress.regress_report())
        self.assertFalse(os.path.exists(self.state))

    def test_rows_and_denominator_come_from_set_json(self):
        # RR-08: the report used the built-in set, so an edited set showed 3/13.
        self.custom_set()
        for item_id in ("F1-inventory", "F7-evidence", "MY-1"):
            ad_regress.regress_record(item_id, "pass", "model-A")
        report = ad_regress.regress_report()
        table_rows = [line.split("|")[1].strip() for line in report.splitlines()
                      if line.startswith("| ") and not line.startswith("| item")]
        self.assertEqual(table_rows, ["F1-inventory", "F7-evidence", "MY-1", "MY-2"])
        self.assertIn("| MY-2 | not run |", report)
        self.assertIn("model-A: passed 3 of 3 run (4 in set); partial 0, fail 0, not run 1", report)
        self.assertNotIn("F2-reread", report)

    def test_unknown_ids_are_listed_apart_and_not_counted(self):
        ad_regress.regress_record("F1-inventory", "pass", "m")
        ad_regress.regress_record("TYPO-9", "pass", "m", force=True)
        report = ad_regress.regress_report()
        self.assertIn("Recorded ids that are not in the set (not counted): TYPO-9", report)
        self.assertIn("m: passed 1 of 1 run (12 in set)", report)
        self.assertNotIn("| TYPO-9 |", report)

    def test_history_shows_the_previous_result(self):
        # RR-20: the latest result used to replace history, so a drop between two dates was invisible.
        for item_id in ("F1-inventory", "F5-passivity", "F7-evidence"):
            ad_regress.regress_record(item_id, "pass", "model-x")
        self.clock = START + datetime.timedelta(days=31)
        for item_id in ("F1-inventory", "F5-passivity"):
            ad_regress.regress_record(item_id, "fail", "model-x")
        ad_regress.regress_record("F7-evidence", "pass", "model-x")
        report = ad_regress.regress_report()
        self.assertIn("| F1-inventory | fail (2030-11-10), was pass (2030-10-10) |", report)
        self.assertIn("| F7-evidence | pass (2030-11-10) |", report)
        self.assertIn("model-x: passed 1 of 3 run (12 in set); partial 0, fail 2, not run 9", report)
        self.assertIn("Changed since the previous result:", report)
        self.assertIn("- F5-passivity on model-x: pass (2030-10-10) to fail (2030-11-10)", report)
        self.assertNotIn("- F7-evidence on", report)

    def test_partial_is_counted_separately(self):
        ad_regress.regress_record("F1-inventory", "partial", "m")
        ad_regress.regress_record("F2-reread", "pass", "m")
        self.assertIn("m: passed 1 of 2 run (12 in set); partial 1, fail 0, not run 10",
                      ad_regress.regress_report())

    def test_one_column_per_model(self):
        ad_regress.regress_record("F1-inventory", "pass", "model-a")
        ad_regress.regress_record("F1-inventory", "fail", "model-b")
        report = ad_regress.regress_report()
        self.assertEqual(report.splitlines()[0], "| item | model-a | model-b |")
        self.assertIn("| F1-inventory | pass (2030-10-10) | fail (2030-10-10) |", report)

    def test_edited_item_is_flagged(self):
        path = self.custom_set()
        ad_regress.regress_record("MY-1", "pass", "m")
        with open(path, encoding="utf-8") as handle:
            items = json.load(handle)
        items[2]["turns"] = ["Do X, differently."]
        self.write_set(items)
        self.assertIn("| MY-1 | pass (2030-10-10), item edited since |", ad_regress.regress_report())

    def test_damaged_lines_are_skipped_and_counted(self):
        # RR-21: one blank or cut line used to crash the report.
        ad_regress.regress_record("F1-inventory", "pass", "m")
        ad_core.append_line("regress/results.jsonl", "")
        ad_core.append_line("regress/results.jsonl", '{"ts": "2030-11-10T17:00:00", "id": "F1-inventory", "result": "pa')
        ad_core.append_line("regress/results.jsonl", '{"id": "F1-inventory", "result": "maybe", "model": "m", "ts": "x"}')
        ad_core.append_line("regress/results.jsonl", '{"id": 5}')
        report = ad_regress.regress_report()
        self.assertIn("| F1-inventory | pass (2030-10-10) |", report)
        self.assertIn("3 unreadable lines in results.jsonl were skipped.", report)

    def test_labels_cannot_break_the_table(self):
        ad_regress.regress_record("F1-inventory", "pass", "sonnet|web")
        report = ad_regress.regress_report()
        self.assertEqual(report.splitlines()[0], "| item | sonnet\\|web |")
        self.assertEqual(report.splitlines()[1], "|---|---|")


if __name__ == "__main__":
    unittest.main()
