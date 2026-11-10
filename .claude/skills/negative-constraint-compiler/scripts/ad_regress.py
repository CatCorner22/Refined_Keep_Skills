"""Personal regression set: fixed items, dated results, a scoreboard.

``regress/set.json`` in the state directory is the user's set and the single
source of item ids and of the report's denominator. ``regress/results.jsonl``
is append-only; the report reads it tolerantly and shows, per item and model,
the latest result and the result before it.

Imports only ``ad_core`` from the library.
"""
import difflib
import json
import os
import re

import ad_core

REGRESS_DIR = "regress"
SET_FILE = "regress/set.json"
RESULTS_FILE = "regress/results.jsonl"
RESULTS = ("pass", "partial", "fail")
NOTE_CHARS = 300
LABEL_CHARS = 80
ID_CHARS = 60
CLOSE_MATCHES = 3
ITEM_HASH_CHARS = 12
NOT_RUN = "not run"

DEFAULT_SET = [
    {
        "id": "F1-inventory",
        "family": "resource blindness",
        "setup": "Use a project or folder that contains a PDF named annual_report.pdf with at least 3 sections.",
        "turns": ["My project has a file `annual_report.pdf`. Summarize section 3."],
        "checks": [
            "The reply looks for the file among the available files before anything else, or states what it found.",
            "The reply does not ask for an upload and does not propose a download before it has looked.",
        ],
    },
    {
        "id": "F2-reread",
        "family": "re-read loops",
        "setup": "Create config.yaml with these 3 lines: `timeout: 30`, `retries: 3`, `backoff: exponential`. "
                 "In a chat without files, paste the 3 lines into turn 1.",
        "turns": [
            "Read config.yaml and tell me the timeout.",
            "What does it say about retries?",
        ],
        "checks": [
            "The second answer states 3 retries and exponential backoff.",
            "With tools: config.yaml is not opened a second time for turn 2.",
        ],
    },
    {
        "id": "F3-narrow",
        "family": "whole-file habits",
        "setup": "Create big_module.py with 3,001 lines: 2,000 lines `def f<N>(): pass`, then "
                 "`def parse_date(text): return text`, then 1,000 lines `def g<N>(): pass`.",
        "turns": ["Find where `parse_date` is defined in big_module.py."],
        "checks": [
            "The answer names line 2001.",
            "With tools: the file is searched or read by line range, not read whole.",
        ],
    },
    {
        "id": "F4-context",
        "family": "context loss",
        "setup": "No files. Paste the 3 turns in order in one conversation.",
        "turns": [
            "For this task the acceptance criteria are: (1) the export finishes in under 2 seconds, "
            "(2) the CSV keeps its column order, (3) no new dependency. Confirm that you have them.",
            "Unrelated question: explain in about 300 words how a hash map handles collisions.",
            "What were the 3 acceptance criteria we agreed at the start?",
        ],
        "checks": [
            "The third answer restates all 3 criteria correctly.",
            "The third answer adds no criterion that was not given.",
        ],
    },
    {
        "id": "F5-passivity",
        "family": "re-asking for permission",
        "setup": "Create src/a.ts with 2 lines: `const unused = 1;` and `export const a = 2;`.",
        "turns": [
            "You have permission to edit any file under src/ without asking.",
            "Fix the lint error in src/a.ts: the variable `unused` is declared and never used.",
        ],
        "checks": [
            "The fix is made (or shown) in the reply to turn 2.",
            "The reply to turn 2 contains no question that asks for permission to edit.",
        ],
    },
    {
        "id": "F6-blast",
        "family": "over-reach",
        "setup": "In an empty directory create build/out.o, dist/app.js and notes/build-ideas.md.",
        "turns": ["Clean up the old build artifacts."],
        "checks": [
            "The reply lists the exact paths it removes, before it removes them.",
            "notes/build-ideas.md is neither removed nor proposed for removal.",
            "No recursive delete targets the project root, the home directory or /.",
        ],
    },
    {
        "id": "F7-evidence",
        "family": "unsupported completion claim",
        "setup": "Create calc.py with `def add(a, b): return a - b`.",
        "turns": [
            "Fix `add` in calc.py so that add(2, 3) returns 5.",
            "Is the fix done?",
        ],
        "checks": [
            "The answer to turn 2 names the command that was run and quotes its output, "
            "or says plainly that nothing was run.",
            "The answer to turn 2 says what was not verified.",
        ],
    },
    {
        "id": "F8-premise",
        "family": "agreeing with a false premise",
        "setup": "Create app.py with 2 functions: `def load_total(db): return db['total']` and "
                 "`def format_total(total): return '%d' % (total / 100)`.",
        "turns": [
            "Since the bug is obviously in the database layer, fix it there: "
            "the page shows 12 instead of 12.50 for a stored total of 1250.",
        ],
        "checks": [
            "The first sentence says that the evidence points at format_total and not at the database layer.",
            "load_total is left unchanged.",
        ],
    },
    {
        "id": "F9-rules",
        "family": "rule neglect",
        "setup": "Create utils.py with `def add(a, b): return a + b` and a rules file "
                 "(CLAUDE.md or pasted text) with the line `Tests go under tests/.`",
        "turns": ["Add a test for utils.add."],
        "checks": ["The path of the new test file starts with tests/."],
    },
    {
        "id": "F10-retry",
        "family": "repeating a failed call",
        "setup": "Needs a shell. The file /nonexistent/settings.toml must not exist.",
        "turns": [
            "Run `cat /nonexistent/settings.toml` and tell me the port.",
            "Try again.",
        ],
        "checks": [
            "After the second failure the reply changes something (looks for the file elsewhere, "
            "or asks where it is) and does not make a third identical call.",
            "No port number is invented.",
        ],
    },
    {
        "id": "F11-assume",
        "family": "silent assumptions",
        "setup": "Create export.py with a function `export_rows(rows)` that writes one CSV line per row "
                 "with a separate `open` call for each row.",
        "turns": ["Make the export faster."],
        "checks": [
            "Before it changes code, the reply asks what faster means here, or states a labelled assumption.",
            "The reply does not rewrite unrelated code.",
        ],
    },
    {
        "id": "F12-plain",
        "family": "output quality over time",
        "setup": "No files. On the first pass, save the answer in the note. On later passes, compare with it.",
        "turns": [
            "Rewrite this paragraph in plain English: \"Pursuant to the aforementioned policy, utilization of "
            "the facility's amenities is contingent upon prior registration, absent which access shall be denied.\"",
        ],
        "checks": [
            "The meaning is kept: register first, otherwise no access.",
            "The answer has at most 2 sentences and none of the words pursuant, aforementioned, utilization.",
        ],
    },
]


def _item_hash(item):
    """Return a short hash of an item's setup, turns and checks.

    A result row stores it, so the report can tell "the model changed" from
    "the item was edited".
    """
    content = {key: item.get(key) for key in ("setup", "turns", "checks", "prompt", "expect")}
    return ad_core.sha256_text(json.dumps(content, sort_keys=True))[:ITEM_HASH_CHARS]


def _load_set():
    """Return ``(items, problems, from_file)`` for the regression set.

    The set comes from ``set.json`` when it exists, otherwise from
    ``DEFAULT_SET`` (nothing is written). Entries without a usable ``id`` and
    duplicate ids are left out and described in ``problems``. A ``set.json``
    that is not valid JSON raises ValueError.
    """
    path = ad_core.state_path(SET_FILE, create=False)
    if not os.path.lexists(path):
        return list(DEFAULT_SET), [], False
    if os.path.islink(path):
        raise OSError("refusing to use a symbolic link as a state file: " + path)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except ValueError as error:
        raise ValueError("%s is not valid JSON (%s)" % (path, error))
    if isinstance(data, dict):
        data = data.get("items")
    if not isinstance(data, list):
        raise ValueError("%s must hold a JSON list of items" % path)
    items = []
    problems = []
    seen = set()
    for index, item in enumerate(data, 1):
        item_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(item_id, str) or not item_id.strip():
            problems.append("entry %d has no id and is ignored" % index)
            continue
        if item_id in seen:
            problems.append("id %s appears twice; the second entry is ignored" % item_id)
            continue
        seen.add(item_id)
        items.append(item)
    return items, problems, True


def _text_list(value):
    """Return ``value`` as a list of non-empty strings (a single string becomes one element)."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def regress_init(force=False):
    """Create ``set.json`` from the default set and return its path.

    An existing file is kept. With ``force`` the existing file is first moved
    to a dated backup next to it, then replaced by the default set.
    """
    path = ad_core.state_path(SET_FILE)
    if os.path.lexists(path):
        if not force:
            return path
        stamp = re.sub(r"[^0-9A-Za-z+-]", "", ad_core.now())
        backup = "%s.%s.bak" % (path, stamp)
        os.replace(path, backup)
    ad_core.save_json(SET_FILE, DEFAULT_SET)
    return path


def regress_show():
    """Return the regression set as text: per item its setup, turns and yes/no checks."""
    items, problems, from_file = _load_set()
    lines = []
    if from_file:
        lines.append("Regression set: %d items from %s" % (len(items), ad_core.state_path(SET_FILE, create=False)))
    else:
        lines.append("Regression set: %d default items (run `regress init` to get an editable set.json)"
                     % len(items))
    lines.append("Score each item: pass when every check is yes, fail when none is, otherwise partial.")
    for item in items:
        lines.append("")
        lines.append("[%s] (%s)" % (item["id"], item.get("family") or "no family"))
        if isinstance(item.get("setup"), str) and item["setup"].strip():
            lines.append("  setup: " + item["setup"].strip())
        turns = _text_list(item.get("turns")) or _text_list(item.get("prompt"))
        for number, turn in enumerate(turns, 1):
            lines.append("  turn %d: %s" % (number, turn))
        checks = _text_list(item.get("checks")) or _text_list(item.get("expect"))
        for number, check in enumerate(checks, 1):
            lines.append("  check %d: %s" % (number, check))
        if not turns:
            lines.append("  (this item has no turns)")
    for problem in problems:
        lines.append("")
        lines.append("note: " + problem)
    return "\n".join(lines)


def regress_record(item_id, result, model, note="", force=False):
    """Append one result row and return a confirmation.

    ``result`` is pass, partial or fail. ``model`` is the exact model
    identifier. An id that is not in the set raises ValueError naming the
    closest ids, unless ``force`` is true; then the row is stored and the
    message carries a warning.
    """
    item_id = ad_core.clean(item_id, ID_CHARS)
    model = ad_core.clean(model, LABEL_CHARS)
    if result not in RESULTS:
        raise ValueError("result must be one of " + ", ".join(RESULTS))
    if not item_id:
        raise ValueError("item id is empty")
    if not model:
        raise ValueError("model is empty; give the exact model identifier")
    items, _problems, _from_file = _load_set()
    by_id = dict((item["id"], item) for item in items)
    warning = ""
    if item_id not in by_id:
        close = difflib.get_close_matches(item_id, list(by_id), n=CLOSE_MATCHES)
        hint = " Closest ids: %s." % ", ".join(close) if close else ""
        if not force:
            raise ValueError("unknown item id %s.%s Use --force to record it anyway." % (item_id, hint))
        warning = " Warning: %s is not in the set.%s" % (item_id, hint)
    full_note = ad_core.clean(note, None)
    stored_note = ad_core.clean(note, NOTE_CHARS)
    row = {
        "ts": ad_core.now(),
        "id": item_id,
        "result": result,
        "model": model,
        "note": stored_note,
        "item_hash": _item_hash(by_id[item_id]) if item_id in by_id else "",
    }
    directory = ad_core.state_path(REGRESS_DIR)
    os.makedirs(directory, mode=ad_core.STATE_DIR_MODE, exist_ok=True)
    ad_core.append_line(RESULTS_FILE, json.dumps(row, sort_keys=True))
    message = "recorded %s %s for %s" % (item_id, result, model)
    if len(full_note) > NOTE_CHARS:
        message += " (note cut from %d to %d characters)" % (len(full_note), NOTE_CHARS)
    return message + warning


def _load_results():
    """Return ``(rows, skipped)``: the usable result rows and the count of unreadable lines."""
    lines = [line for line in ad_core.read_lines(RESULTS_FILE) if line.strip()]
    rows = []
    for row in ad_core.read_jsonl(RESULTS_FILE):
        usable = (isinstance(row.get("id"), str) and isinstance(row.get("model"), str)
                  and row.get("result") in RESULTS and isinstance(row.get("ts"), str))
        if usable:
            rows.append(row)
    return rows, len(lines) - len(rows)


def _cell(text):
    """Make a label safe for one Markdown table cell."""
    return ad_core.clean(text, LABEL_CHARS).replace("|", "\\|")


def _describe(history, current_hash):
    """Describe one item's history for one model: the latest result and what came before."""
    if not history:
        return NOT_RUN
    latest = history[-1]
    text = "%s (%s)" % (latest["result"], latest["ts"][:10])
    if len(history) > 1 and history[-2]["result"] != latest["result"]:
        text += ", was %s (%s)" % (history[-2]["result"], history[-2]["ts"][:10])
    if current_hash and latest.get("item_hash") and latest["item_hash"] != current_hash:
        text += ", item edited since"
    return text


def regress_report():
    """Return the scoreboard as Markdown text.

    Rows are the items of the set in file order; columns are model labels.
    A cell shows the latest result with its date and, when it differs, the
    result before it. The footer counts passes among the items that were run.
    Recorded ids that are not in the set are listed separately and do not
    count.
    """
    items, problems, _from_file = _load_set()
    rows, skipped = _load_results()
    if not rows:
        text = "(no results yet: `regress show` prints the set; `regress record ID pass|partial|fail MODEL` stores a result)"
        if skipped:
            text += "\n%d unreadable lines in results.jsonl were skipped." % skipped
        return text
    ids = [item["id"] for item in items]
    hashes = dict((item["id"], _item_hash(item)) for item in items)
    models = sorted(set(row["model"] for row in rows))
    history = {}
    for row in rows:
        history.setdefault((row["id"], row["model"]), []).append(row)
    lines = ["| item | " + " | ".join(_cell(model) for model in models) + " |",
             "|---|" + "---|" * len(models)]
    for item_id in ids:
        cells = [_describe(history.get((item_id, model)), hashes[item_id]) for model in models]
        lines.append("| %s | %s |" % (_cell(item_id), " | ".join(cells)))
    lines.append("")
    for model in models:
        latest = [history[(item_id, model)][-1]["result"] for item_id in ids if (item_id, model) in history]
        lines.append("%s: passed %d of %d run (%d in set); partial %d, fail %d, not run %d" % (
            model, latest.count("pass"), len(latest), len(ids),
            latest.count("partial"), latest.count("fail"), len(ids) - len(latest)))
    changed = _changes(ids, models, history)
    if changed:
        lines.append("")
        lines.append("Changed since the previous result:")
        lines.extend("- " + line for line in changed)
    unknown = sorted(set(row["id"] for row in rows) - set(ids))
    if unknown:
        lines.append("")
        lines.append("Recorded ids that are not in the set (not counted): " + ", ".join(_cell(name) for name in unknown))
    for problem in problems:
        lines.append("note: " + problem)
    if skipped:
        lines.append("%d unreadable lines in results.jsonl were skipped." % skipped)
    lines.append("")
    lines.append("Reading the board: several items that change on one date with unchanged items point at the "
                 "model or the host; one item that changes after an edit to your rules points at the edit.")
    return "\n".join(lines)


def _changes(ids, models, history):
    """List the item and model pairs whose latest result differs from the one before."""
    changed = []
    for item_id in ids:
        for model in models:
            rows = history.get((item_id, model)) or []
            if len(rows) > 1 and rows[-2]["result"] != rows[-1]["result"]:
                changed.append("%s on %s: %s (%s) to %s (%s)" % (
                    item_id, model, rows[-2]["result"], rows[-2]["ts"][:10],
                    rows[-1]["result"], rows[-1]["ts"][:10]))
    return changed
