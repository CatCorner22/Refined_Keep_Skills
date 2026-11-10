"""Gates and observability: tool log, output trimmer, completion gate, provenance.

Imports only ``ad_core`` from the library.
"""
import json
import os
import re
import sys

import ad_core

# --------------------------------------------------------------------------
# Tool log
# --------------------------------------------------------------------------

TOOL_LOG_FILE = "toollog.jsonl"
TOOL_LOG_MAX_BYTES = 1024 * 1024
TOOL_LOG_KEEP_LINES = 2000
LOGGED_COMMAND_CHARS = 500
SHELL_TOOLS = ("Bash", "PowerShell")
EXIT_CODE_RE = re.compile(r"^Exit code (\d+)\s*$")
# Which tool_input field identifies the call, per tool.
TOOL_INPUT_FIELD = {
    "Bash": "command",
    "PowerShell": "command",
    "Write": "file_path",
    "Edit": "file_path",
    "Read": "file_path",
    "NotebookEdit": "notebook_path",
    "WebFetch": "url",
    "WebSearch": "query",
    "Grep": "pattern",
    "Glob": "pattern",
}


def normalize_command(command):
    """Collapse every whitespace run of ``command`` to one space and strip the ends."""
    if not isinstance(command, str):
        return ""
    return " ".join(command.split())


def _logged_command(tool, tool_input):
    """Return the text that identifies a tool call in the tool log.

    Only the one field that names the action is read (the command, the file
    path, the URL). Content fields and descriptions are never logged.
    """
    if not isinstance(tool_input, dict):
        return ""
    value = tool_input.get(TOOL_INPUT_FIELD.get(tool, ""))
    if not isinstance(value, str):
        return ""
    if tool in SHELL_TOOLS:
        value = normalize_command(value)
    return ad_core.redact(value)[:LOGGED_COMMAND_CHARS]


def _failure_exit_code(inp):
    """Return the exit code from the first line of the failure text, or None.

    The host documents ``Exit code N`` as the stable first line of a failed
    shell command. The rest of the text is display text and is not searched,
    so output that merely contains the words "exit 1" is not read as a failure.
    """
    error = inp.get("error")
    if not isinstance(error, str) or not error:
        return None
    match = EXIT_CODE_RE.match(error.split("\n", 1)[0])
    if match:
        return int(match.group(1))
    return None


def _text_field(inp, name):
    """Return the string field ``name`` of the hook input, or empty text."""
    value = inp.get(name)
    if isinstance(value, str):
        return value
    return ""


def log_tool(inp, failed=False):
    """Append one record for a tool call to the tool log; return the record.

    Returns None, and never raises, when the record cannot be written: the
    log is an aid, and a hook must not fail because of it.
    """
    try:
        tool = _text_field(inp, "tool_name")
        record = {
            "ts": ad_core.now(),
            "session": _text_field(inp, "session_id"),
            "prompt": _text_field(inp, "prompt_id"),
            "tool": tool,
            "cmd": _logged_command(tool, inp.get("tool_input")),
            "ok": not failed,
            "exit": None,
        }
        if failed:
            record["exit"] = _failure_exit_code(inp)
            if inp.get("is_interrupt") is True:
                record["interrupt"] = True
        elif tool in SHELL_TOOLS:
            record["exit"] = 0
        if _text_field(inp, "tool_use_id"):
            record["id"] = _text_field(inp, "tool_use_id")
        if _text_field(inp, "agent_id"):
            record["agent"] = _text_field(inp, "agent_id")
        ad_core.append_line(TOOL_LOG_FILE, json.dumps(record, sort_keys=True))
        ad_core.rotate(TOOL_LOG_FILE, TOOL_LOG_MAX_BYTES, TOOL_LOG_KEEP_LINES)
        return record
    except (OSError, ValueError, TypeError):
        return None


def tool_log(session=None):
    """Return the tool-log records, oldest first, optionally for one session.

    When the same hook is registered twice, one call is logged twice; records
    that share a tool-use id are collapsed to the last one.
    """
    records = []
    position_by_id = {}
    for record in ad_core.read_jsonl(TOOL_LOG_FILE):
        if session is not None and record.get("session") != session:
            continue
        call_id = record.get("id")
        if isinstance(call_id, str) and call_id:
            if call_id in position_by_id:
                records[position_by_id[call_id]] = record
                continue
            position_by_id[call_id] = len(records)
        records.append(record)
    return records


def hook_log_failure():
    """PostToolUseFailure: log the failed call with ``ok`` false and its exit code."""
    inp = ad_core.read_hook_input()
    log_tool(inp, failed=True)
    sys.exit(0)


# --------------------------------------------------------------------------
# Trimmer
# --------------------------------------------------------------------------

TRIM_CHARS_DEFAULT = 6000
TRIM_CHARS_MIN = 400
TRIM_LINE_CHARS = 300
OUTPUTS_DIR = "outputs"
MAX_STORED_OUTPUTS = 200
HEAD_SHARE = 0.4
TAIL_SHARE = 0.35
GAP_MARKER_RESERVE = 120
GREP_SAMPLE_LINES = 50
GREP_MIN_SHARE = 0.6
JSON_SAMPLE_STEPS = ((5, 200, 6), (3, 120, 5), (3, 60, 4), (2, 40, 3), (1, 20, 3), (1, 10, 2))
JSON_MAX_KEYS = 40

TEST_SUMMARY_RE = re.compile(
    r"(?i)\b\d+\s+(?:passed|failed|errors?|failures?|skipped|tests?)\b|^(?:FAILED|PASSED|OK)\b|^Ran \d+ tests?"
    r"|^(?:not )?ok \d+|^Tests?:\s|^--- (?:FAIL|PASS)")
TEST_FAILURE_RE = re.compile(
    r"^(?:FAILED|FAIL|ERROR|E  |--- FAIL|not ok)\b|\bAssertionError\b|\bTraceback \(most recent call last\)"
    r"|\bError:|\bpanic:|^\s*[\u2715\u00d7\u2717]\s")
TEST_KEEP_RE = re.compile(
    r"FAIL|ERROR|Error|[Ee]xception|assert|Traceback|^\s+File \"|^E\s|panic|not ok|[\u2715\u00d7\u2717]"
    r"|\b\d+\s+(?:passed|failed|errors?|failures?|skipped)\b|^Ran \d+ tests?|short test summary|^=+ .* =+$")
GREP_LINE_RE = re.compile(r"^([^\s:][^:]*):(\d+)[:-]")
TIME_PREFIX_RE = re.compile(r"^\d{1,2}$|^\d{4}-\d{2}-\d{2}[T ]\d{1,2}$")
IMPORTANT_LINE_RE = re.compile(r"ERROR|CRITICAL|FATAL|WARN|Traceback|panic|Exception|\bfailed\b", re.I)


def trim_limit():
    """Return the trimmer's character limit from ``AD_TRIM_CHARS`` (default 6000)."""
    return ad_core.env_int("AD_TRIM_CHARS", TRIM_CHARS_DEFAULT, minimum=TRIM_CHARS_MIN)


def _cut_line(line, width):
    """Cut ``line`` to ``width`` characters and say how many were removed."""
    if len(line) <= width:
        return line
    return "%s%s[+%d chars]" % (line[:width], ad_core.ELLIPSIS, len(line) - width)


def _take(lines, budget, width):
    """Take lines from the front, each cut to ``width``, while they fit ``budget`` characters."""
    taken = []
    used = 0
    for line in lines:
        piece = _cut_line(line, width)
        if used + len(piece) + 1 > budget:
            break
        taken.append(piece)
        used += len(piece) + 1
    return taken


def _line_width(limit):
    """Return the maximum line length for a given total limit."""
    return max(40, min(TRIM_LINE_CHARS, limit // 6))


def _looks_like_test_output(lines):
    """Return True when the text has a test summary and at least one failure line."""
    has_summary = any(TEST_SUMMARY_RE.search(line) for line in lines)
    has_failure = any(TEST_FAILURE_RE.search(line) for line in lines)
    return has_summary and has_failure


def _is_grep_line(line):
    """Return True for a ``path:line:`` search hit; time stamps do not count as paths."""
    match = GREP_LINE_RE.match(line)
    if not match:
        return False
    prefix = match.group(1)
    if TIME_PREFIX_RE.match(prefix):
        return False
    return "/" in prefix or "\\" in prefix or "." in prefix


def _looks_like_grep_output(lines):
    """Return True when most of the first non-empty lines are search hits."""
    sample = [line for line in lines if line.strip()][:GREP_SAMPLE_LINES]
    if len(sample) < 5:
        return False
    hits = sum(1 for line in sample if _is_grep_line(line))
    return hits >= GREP_MIN_SHARE * len(sample)


def _trim_test_failures(lines, limit):
    """Keep failure lines and summary lines of test output."""
    wanted = [line for line in lines if TEST_KEEP_RE.search(line)]
    kept = _take(wanted, limit, _line_width(limit))
    marker = "[trimmed test-failures: kept %d failure and summary lines of %d lines; %d lines dropped]" % (
        len(kept), len(lines), len(lines) - len(kept))
    return "\n".join(kept + [marker])


def _trim_grep(lines, limit):
    """Keep the first search hits whole (path, line number and text)."""
    kept = _take(lines, limit, _line_width(limit))
    files = set()
    for line in lines:
        match = GREP_LINE_RE.match(line)
        if match:
            files.add(match.group(1))
    marker = "[trimmed grep: kept the first %d of %d lines; %d lines dropped; %d files have hits]" % (
        len(kept), len(lines), len(lines) - len(kept), len(files))
    return "\n".join(kept + [marker])


def _json_sample(value, items, text_chars, depth):
    """Return a reduced copy of a JSON value: first ``items`` of each list, short strings."""
    if isinstance(value, dict):
        if depth <= 0:
            return "{%d keys}" % len(value)
        sample = {}
        for index, key in enumerate(value):
            if index >= JSON_MAX_KEYS:
                sample[ad_core.ELLIPSIS] = "%d more keys" % (len(value) - JSON_MAX_KEYS)
                break
            sample[key] = _json_sample(value[key], items, text_chars, depth - 1)
        return sample
    if isinstance(value, list):
        if depth <= 0:
            return "[%d items]" % len(value)
        sample = [_json_sample(item, items, text_chars, depth - 1) for item in value[:items]]
        if len(value) > items:
            sample.append("%s %d more items" % (ad_core.ELLIPSIS, len(value) - items))
        return sample
    if isinstance(value, str) and len(value) > text_chars:
        return value[:text_chars] + ad_core.ELLIPSIS
    return value


def _trim_json(text, limit):
    """Return a structural sample of JSON text that fits ``limit``; None when not possible."""
    stripped = text.strip()
    if stripped[:1] not in ("{", "["):
        return None
    try:
        data = json.loads(stripped)
    except (ValueError, RecursionError):
        return None
    line_count = text.count("\n") + 1
    for items, text_chars, depth in JSON_SAMPLE_STEPS:
        body = json.dumps(_json_sample(data, items, text_chars, depth), indent=1, ensure_ascii=False)
        if len(body) <= limit:
            marker = ("[trimmed json: structure kept; each list shows its first %d items, strings are cut at "
                      "%d characters, depth %d; original %d characters in %d lines]"
                      % (items, text_chars, depth, len(text), line_count))
            return body + "\n" + marker
    return None


def _trim_head_tail(lines, limit):
    """Keep the head, the tail and the error-like lines in between; cut long lines."""
    width = _line_width(limit)
    budget = max(limit - GAP_MARKER_RESERVE, 0)
    head = _take(lines, int(budget * HEAD_SHARE), width)
    rest = lines[len(head):]
    tail = _take(list(reversed(rest)), int(budget * TAIL_SHARE), width)
    tail.reverse()
    middle_lines = rest[:len(rest) - len(tail)]
    middle_budget = budget - sum(len(line) + 1 for line in head) - sum(len(line) + 1 for line in tail)
    important = _take([line for line in middle_lines if IMPORTANT_LINE_RE.search(line)],
                      middle_budget, width)
    omitted = len(middle_lines) - len(important)
    cut = sum(1 for line in lines if len(line) > width)
    parts = list(head)
    if omitted > 0:
        parts.append("%s [%d lines omitted here] %s" % (ad_core.ELLIPSIS, omitted, ad_core.ELLIPSIS))
    parts.extend(important)
    parts.extend(tail)
    kept = len(head) + len(important) + len(tail)
    marker = "[trimmed head-tail: kept %d of %d lines; %d lines omitted; long lines cut at %d characters (%d cut)]" % (
        kept, len(lines), omitted, width, cut)
    return "\n".join(parts + [marker])


def trim_output(text, limit=None):
    """Shorten long tool output; return ``(text, kind)``.

    ``kind`` is ``passthrough`` (already within ``limit``), ``test-failures``,
    ``grep``, ``json`` or ``head-tail``. The result is never longer than
    ``limit`` characters plus one final marker line, and the marker says what
    was dropped.
    """
    if limit is None:
        limit = trim_limit()
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= limit:
        return text, "passthrough"
    lines = text.splitlines()
    if _looks_like_test_output(lines):
        return _trim_test_failures(lines, limit), "test-failures"
    if _looks_like_grep_output(lines):
        return _trim_grep(lines, limit), "grep"
    as_json = _trim_json(text, limit)
    if as_json is not None:
        return as_json, "json"
    return _trim_head_tail(lines, limit), "head-tail"


def store_full_output(text):
    """Save ``text`` under ``outputs/`` in the state directory and return its path.

    The file name is a content hash, so the same output is stored once. The
    directory keeps at most ``MAX_STORED_OUTPUTS`` files; the oldest go first.
    """
    directory = ad_core.state_path(OUTPUTS_DIR)
    if os.path.islink(directory):
        raise OSError("refusing to use a symbolic link as the outputs directory: " + directory)
    os.makedirs(directory, mode=ad_core.STATE_DIR_MODE, exist_ok=True)
    path = os.path.join(directory, ad_core.sha256_text(text)[:16] + ".txt")
    if os.path.islink(path):
        raise OSError("refusing to use a symbolic link as a state file: " + path)
    if not os.path.exists(path):
        ad_core.write_text(os.path.join(OUTPUTS_DIR, os.path.basename(path)), text)
    _prune_outputs(directory)
    return path


def _prune_outputs(directory):
    """Delete the oldest stored outputs beyond ``MAX_STORED_OUTPUTS``."""
    try:
        names = [name for name in os.listdir(directory) if name.endswith(".txt")]
        if len(names) <= MAX_STORED_OUTPUTS:
            return
        paths = [os.path.join(directory, name) for name in names]
        paths.sort(key=lambda path: (os.lstat(path).st_mtime_ns, path))
        for path in paths[:len(paths) - MAX_STORED_OUTPUTS]:
            os.unlink(path)
    except OSError:
        return


def trimmed_tool_output(inp):
    """Return a replacement ``tool_response`` for a long Bash result, or None.

    Active only when ``AD_TRIM_HOOK=1``, because the host already pages large
    outputs. The replacement has the shape of the original object: ``stdout``
    is the trimmed view plus the path of the full copy; every other field is
    copied unchanged. Nothing is returned unless the view is shorter.
    """
    if os.environ.get("AD_TRIM_HOOK") != "1":
        return None
    if inp.get("tool_name") != "Bash":
        return None
    response = inp.get("tool_response")
    if not isinstance(response, dict):
        return None
    stdout = response.get("stdout")
    limit = trim_limit()
    if not isinstance(stdout, str) or len(stdout) <= limit:
        return None
    view, kind = trim_output(stdout, limit)
    if kind == "passthrough":
        return None
    path = store_full_output(stdout)
    view = "%s\n[full output, %d characters: %s]" % (view, len(stdout), path)
    if len(view) >= len(stdout):
        return None
    replacement = dict(response)
    replacement["stdout"] = view
    return replacement


# --------------------------------------------------------------------------
# Completion gate
# --------------------------------------------------------------------------

FENCE_RE = re.compile(r"(?ms)^[ \t]*(```|~~~).*?^[ \t]*\1[ \t]*$")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
QUOTE_LINE_RE = re.compile(r"(?m)^[ \t]*>.*$")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+")
LEADING_MARKUP_RE = re.compile(r"^[\s>*_#\-\u2022\u2705\u2714\ufe0f\d.)\]\[xX]*")

_STATE_WORDS = r"(?:done|complete|completed|finished|fixed|resolved|implemented|working|passing|green|merged|deployed)"
_DID_WORDS = r"(?:fixed|implemented|completed|finished|resolved|addressed|shipped|merged|deployed)"
_ADVERBS = r"(?:(?:now|all|fully|finally|already|also|successfully|completely)\s+)*"
CLAIM_PATTERNS = tuple(re.compile(pattern, re.I) for pattern in (
    r"\ball(?: of)?(?: the)?(?: \w+)? tests?(?: are)?(?: now)? (?:pass|passed|passing|green)\b",
    r"\b(?:the |all |every )?tests? (?:are |is )?(?:now |all )?(?:passing|green)\b",
    r"\b(?:the )?tests? (?:now |all )?pass(?:ed)?\b",
    r"\b(?:is|are|was|were|been|now)\s+" + _ADVERBS + _STATE_WORDS + r"\b",
    r"\b(?:it|that|this|everything|there)(?:'s|\u2019s)\s+" + _ADVERBS + _STATE_WORDS + r"\b",
    r"\b(?:works|working|passes|builds|compiles|runs) (?:now|again|correctly now|as expected now)\b",
    r"\bnow (?:works|passes|builds|compiles|runs)\b",
    r"\beverything (?:works|passes|is working)\b",
    r"\bready (?:for|to) (?:review|merge|merging|ship|release|deploy|use)\b",
    r"\b(?:I|we)(?: have|'ve|\u2019ve)\s+" + _ADVERBS + _DID_WORDS + r"\b",
    r"\b(?:I|we)\s+" + _ADVERBS + _DID_WORDS + r"\b",
    r"\bsuccessfully\s+\w+(?:ed|t|ne)\b",
    r"\btask (?:is )?(?:complete|completed|done|finished)\b",
    r"\ball (?:done|set|fixed|finished)\b",
))
LINE_START_CLAIM_RE = re.compile(
    r"^(?:done|fixed|completed|complete|implemented|finished|resolved)"
    r"(?:\s*(?:[.!:;,]|$)|\s+[-\u2013\u2014]\s|\s+(?:the|a|an|it|this|that|all|both|with|and|now|everything)\b)",
    re.I)
HEDGE_RE = re.compile(
    r"\b(?:not|never|no|none|nothing|neither|nor|cannot|without|once|until|unless|if|when|whenever|whether|"
    r"will|would|should|could|might|may|must|shall|won|"
    r"to be|needs? to|needed to|wants? to|going to|about to|plan(?:s|ning)? to|try(?:ing)? to|tried to|"
    r"todo|before|so that|in order to|make sure|ensure|verify|check|confirm|can you|did you|"
    r"unsure|assume|assuming|hope|hopefully|expect|expected|almost|nearly|partially|partly|"
    r"let me|let's|i'll|we'll|next|remaining|still|claim(?:s|ed)?|said|says?|reported|"
    r"definition of|criteria|means?)\b|\w+n['\u2019]t\b",
    re.I)

EVIDENCE_LABELS = (
    ("acceptance", r"acceptance(?:[ \t]+criteri(?:a|on))?"),
    ("command", r"commands?(?:[ \t]+(?:run|ran))?"),
    ("output", r"output"),
    ("diff", r"diff"),
    ("not_verified", r"not[ \t-]+verified|unverified"),
)
EVIDENCE_DISPLAY = {
    "acceptance": "Acceptance",
    "command": "Command",
    "output": "Output",
    "diff": "Diff",
    "not_verified": "Not verified",
}
ANY_LABEL_RE = re.compile(
    r"(?i)^[^\w\n]*(?:%s|status)[^\w\n:\uff1a]*[:\uff1a]" % "|".join(pattern for _, pattern in EVIDENCE_LABELS))
EVIDENCE_CONTINUATION_LINES = 12
EVIDENCE_VALUE_CHARS = 2000
PLACEHOLDER_RE = re.compile(r"^(?:<[^>]*>|\[[^\]]*\]|\.{3}|\u2026|todo|tbd|\?+)$", re.I)
PARAPHRASES = frozenset((
    "passed", "pass", "passes", "ok", "okay", "success", "successful", "succeeded", "works", "worked",
    "fine", "good", "it worked", "it works", "all good", "all passed", "done", "green", "looks good",
))
NO_COMMAND_VALUES = frozenset(("none", "n/a", "na", "not run", "not applicable", "-", "\u2014"))
SHORT_COMMAND_CHARS = 4
EVIDENCE_TEMPLATE = (
    "Acceptance: <what counts as done>\n"
    "Command: <the exact command that was run, or none>\n"
    "Output: <quoted output of that command>\n"
    "Diff: <files changed>\n"
    "Not verified: <what was not checked>"
)
GATE_ONCE_NOTE = "This check prompts once per stop attempt."
TRANSCRIPT_TAIL_BYTES = 1024 * 1024


def _prose_of(message):
    """Return the message without fenced code, inline code and quoted lines.

    Those parts quote other text (tool output, the user's words); a completion
    claim is something the author states in their own prose.
    """
    text = FENCE_RE.sub("\n", message)
    text = QUOTE_LINE_RE.sub("", text)
    return INLINE_CODE_RE.sub(" ", text)


def _sentence_claims(sentence):
    """Return True when one sentence states completion as a fact."""
    body = LEADING_MARKUP_RE.sub("", sentence).strip()
    if not body or body.endswith("?"):
        return False
    if LINE_START_CLAIM_RE.match(body):
        return True
    for pattern in CLAIM_PATTERNS:
        for match in pattern.finditer(body):
            if not HEDGE_RE.search(body[:match.start()]):
                return True
    return False


def claims_completion(message):
    """Return True only when ``message`` declares that work is complete.

    The test is per sentence: a completion phrase counts unless the sentence
    is a question or a negation, condition, plan or report of someone else's
    words comes before the phrase. Ordinary uses of the same words ("the
    complete list", "once this is done", "not done yet") are not claims.
    """
    if not isinstance(message, str) or not message.strip():
        return False
    for sentence in SENTENCE_SPLIT_RE.split(_prose_of(message)):
        if _sentence_claims(sentence):
            return True
    return False


def _clean_value(text):
    """Strip Markdown emphasis and surrounding space from an evidence value."""
    return text.strip().strip("*_").strip()


def _continuation(lines, start):
    """Collect the value that follows a label on later lines (for example a fenced block)."""
    collected = []
    in_fence = False
    for line in lines[start:start + EVIDENCE_CONTINUATION_LINES]:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if in_fence:
                break
            in_fence = True
            continue
        if not in_fence:
            if ANY_LABEL_RE.match(line):
                break
            if not stripped and collected:
                break
        if stripped:
            collected.append(stripped)
    return "\n".join(collected)


def find_evidence_block(message):
    """Find the evidence block in ``message``; return its five values or None.

    The five labels may appear in any order and any letter case, behind
    bullets, bold markers or backticks. A value may follow its label on the
    same line or on the lines below it. The result has the keys
    ``acceptance``, ``command``, ``output``, ``diff`` and ``not_verified``;
    None when a label is missing.
    """
    if not isinstance(message, str):
        return None
    lines = message.splitlines()
    found = {}
    for index, line in enumerate(lines):
        for key, pattern in EVIDENCE_LABELS:
            if key in found:
                continue
            match = re.match(r"(?i)^[^\w\n]*(?:%s)[^\w\n:\uff1a]*[:\uff1a](.*)$" % pattern, line)
            if not match:
                continue
            value = _clean_value(match.group(1))
            if not value:
                value = _continuation(lines, index + 1)
            found[key] = value[:EVIDENCE_VALUE_CHARS]
            break
    if len(found) != len(EVIDENCE_LABELS):
        return None
    return found


def _unquoted(value):
    """Return ``(text, was_quoted)``: the value without surrounding quote marks or backticks."""
    text = value.strip()
    for opener, closer in (("`", "`"), ('"', '"'), ("'", "'"), ("\u201c", "\u201d")):
        if len(text) >= 2 and text.startswith(opener) and text.endswith(closer):
            return text.strip(opener + closer).strip(), True
    return text, False


def _is_paraphrase(output_value):
    """Return True when the Output value is a bare verdict instead of quoted output."""
    text, was_quoted = _unquoted(output_value)
    if was_quoted or "\n" in text:
        return False
    return text.lower().rstrip(".! ") in PARAPHRASES


def _cited_commands(command_value):
    """Return the commands an evidence block cites, normalized and redacted.

    Backticked spans are the commands when there are any; otherwise the whole
    value is one command. A leading shell prompt (``$``) is removed.
    """
    spans = re.findall(r"`([^`\n]+)`", command_value)
    candidates = spans if spans else [command_value]
    cited = []
    for candidate in candidates:
        text = normalize_command(candidate)
        text = re.sub(r"^\$\s+", "", text)
        if text:
            cited.append(ad_core.redact(text))
    return cited


def _command_was_logged(cited, logged_commands):
    """Return True when ``cited`` equals, or is contained in, a logged command.

    A cited command shorter than ``SHORT_COMMAND_CHARS`` must match exactly,
    because a 2-letter string is contained in almost every command. Logged
    commands are cut at ``LOGGED_COMMAND_CHARS``, so a longer cited command is
    compared on that prefix.
    """
    for logged in logged_commands:
        if cited == logged:
            return True
        if len(cited) >= SHORT_COMMAND_CHARS and cited in logged:
            return True
        if len(logged) == LOGGED_COMMAND_CHARS and cited.startswith(logged):
            return True
    return False


def shell_commands_logged(session=None):
    """Return the shell commands in the tool log, for one session or for all."""
    return [record.get("cmd") for record in tool_log(session)
            if record.get("tool") in SHELL_TOOLS and isinstance(record.get("cmd"), str) and record.get("cmd")]


def completion_gate_decide(message, session=None, strict=True):
    """Decide whether a final message may stand; return a block reason or None.

    1. No completion claim: pass.
    2. A claim without the five-label evidence block, or with an empty or
       placeholder value: block.
    3. An ``Output:`` value that is a bare verdict such as "passed": block.
    4. ``strict`` and the tool log has shell records (of ``session``, or of
       every session when ``session`` is None): a cited command must appear in
       the log. ``Command: none`` skips this step, and so does an empty log.

    A ``Status: partial`` line needs no special handling: a valid block passes
    whatever the status says. ``AD_GATE=off`` turns the gate off.
    """
    if os.environ.get("AD_GATE", "").strip().lower() == "off":
        return None
    if not claims_completion(message):
        return None
    block = find_evidence_block(message)
    if block is None:
        return ("Completion claim without an evidence block. Add these 5 labelled lines, "
                "or reword the message as a status report:\n%s\n%s" % (EVIDENCE_TEMPLATE, GATE_ONCE_NOTE))
    for key, _ in EVIDENCE_LABELS:
        value, _quoted = _unquoted(block[key])
        if not value or PLACEHOLDER_RE.match(value):
            return ("The evidence block has no value for `%s:`. Fill in all 5 lines:\n%s\n%s"
                    % (EVIDENCE_DISPLAY[key], EVIDENCE_TEMPLATE, GATE_ONCE_NOTE))
    if _is_paraphrase(block["output"]):
        return ("`Output:` holds a verdict (%s), not output. Quote the lines the command printed. %s"
                % (ad_core.clean(block["output"], 40), GATE_ONCE_NOTE))
    if not strict:
        return None
    command_value = block["command"].strip()
    if _unquoted(command_value)[0].lower().rstrip(".") in NO_COMMAND_VALUES:
        return None
    logged = shell_commands_logged(session)
    if not logged:
        return None
    cited = _cited_commands(command_value)
    if not cited or any(_command_was_logged(command, logged) for command in cited):
        return None
    return ("The evidence block cites `%s`, and the tool log (%d shell commands) has no such command. "
            "Run it and quote its output, or cite the command that was run. %s"
            % (ad_core.clean(cited[0], 160), len(logged), GATE_ONCE_NOTE))


def _transcript_last_assistant_text(path):
    """Return the text of the last assistant message in a transcript file, or empty text."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(size - TRANSCRIPT_TAIL_BYTES, 0))
            tail = handle.read().decode("utf-8", "replace")
    except OSError:
        return ""
    for line in reversed(tail.splitlines()):
        try:
            record = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(record, dict):
            continue
        message = record.get("message") if isinstance(record.get("message"), dict) else record
        if record.get("type") != "assistant" and message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "\n".join(part.get("text", "") for part in content
                             if isinstance(part, dict) and isinstance(part.get("text"), str))
        else:
            text = ""
        if text.strip():
            return text
    return ""


def last_assistant_text(inp):
    """Return the final assistant message of a Stop hook input.

    ``last_assistant_message`` is the documented field. ``last_message`` and
    the transcript file are fallbacks for hosts that do not send it.
    """
    for name in ("last_assistant_message", "last_message"):
        if _text_field(inp, name).strip():
            return _text_field(inp, name)
    path = _text_field(inp, "transcript_path")
    if path and os.path.isfile(path):
        return _transcript_last_assistant_text(path)
    return ""


def hook_completion_gate():
    """Stop hook: prompt once for an evidence block when the final message claims completion.

    When ``stop_hook_active`` is true the model is already continuing because
    of a stop hook, so the hook exits silently and the stop goes through.
    """
    inp = ad_core.read_hook_input()
    if inp.get("stop_hook_active"):
        sys.exit(0)
    strict = os.environ.get("AD_GATE_STRICT", "1").strip() != "0"
    session = _text_field(inp, "session_id") or None
    reason = completion_gate_decide(last_assistant_text(inp), session=session, strict=strict)
    if reason:
        ad_core.stop_block(reason)
    sys.exit(0)


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------

PROVENANCE_FILE = "provenance.jsonl"
CONFIDENCE_LEVELS = ("established", "probable", "contested", "single-source", "unknown")
SECTION_CHARS = 200
SOURCE_CHARS = 300
QUOTE_CHARS = 400
QUOTE_SHOWN_CHARS = 80
HEADING_RE = re.compile(r"^ {0,3}(#{1,4})[ \t]+(.+?)[ \t]*$")
FENCE_LINE_RE = re.compile(r"^ {0,3}(```|~~~)")


def _section_key(title):
    """Normalize a heading or a recorded section name for comparison.

    Removes ``#`` marks, a leading ``[ID]`` and surrounding space, then folds case.
    """
    text = title.strip().strip("#").strip()
    text = re.sub(r"^\[[^\]]*\]\s*", "", text)
    return " ".join(text.split()).casefold()


def _cell(text, limit):
    """Make text safe for one Markdown table cell."""
    return ad_core.clean(text, limit).replace("|", "\\|")


def provenance_add(section, source, quote="", confidence="probable"):
    """Record which source supports a section of a deliverable; return a confirmation."""
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError("confidence must be one of " + ", ".join(CONFIDENCE_LEVELS))
    row = {
        "ts": ad_core.now(),
        "section": ad_core.clean(section, SECTION_CHARS),
        "source": ad_core.clean(source, SOURCE_CHARS),
        "quote": ad_core.clean(quote, QUOTE_CHARS),
        "confidence": confidence,
    }
    if not row["section"] or not row["source"]:
        raise ValueError("section and source must not be empty")
    ad_core.append_line(PROVENANCE_FILE, json.dumps(row, sort_keys=True))
    return "provenance recorded: %s <- %s (%s)" % (row["section"], row["source"], confidence)


def _provenance_rows():
    """Return the provenance rows that have a section name."""
    return [row for row in ad_core.read_jsonl(PROVENANCE_FILE) if isinstance(row.get("section"), str)]


def provenance_show(section=None):
    """Return the provenance rows as a Markdown table, optionally for one section."""
    rows = _provenance_rows()
    if section is not None:
        wanted = _section_key(section)
        rows = [row for row in rows if _section_key(row["section"]) == wanted]
    if not rows:
        return "(no provenance recorded)"
    lines = ["| section | source | confidence | quote |", "|---|---|---|---|"]
    for row in rows:
        lines.append("| %s | %s | %s | %s |" % (
            _cell(row["section"], SECTION_CHARS),
            _cell(row.get("source", ""), SOURCE_CHARS),
            _cell(row.get("confidence", ""), 20),
            _cell(row.get("quote", ""), QUOTE_SHOWN_CHARS),
        ))
    return "\n".join(lines)


def _headings(text):
    """Return the level 1 to 4 headings of Markdown text that are outside fenced code."""
    titles = []
    fence = None
    for line in text.splitlines():
        fence_match = FENCE_LINE_RE.match(line)
        if fence_match:
            if fence is None:
                fence = fence_match.group(1)
            elif fence == fence_match.group(1):
                fence = None
            continue
        if fence is not None:
            continue
        match = HEADING_RE.match(line)
        if match:
            titles.append(match.group(2).rstrip("#").strip())
    return titles


def provenance_audit(path):
    """List the headings of the Markdown file ``path`` that have no provenance row.

    Returns ``(text, exit code)``; the exit code is 1 when a heading has no row.
    """
    with open(path, encoding="utf-8", errors="replace") as handle:
        titles = _headings(handle.read())
    if not titles:
        return "no headings (levels 1 to 4) found in %s" % path, 0
    recorded = set(_section_key(row["section"]) for row in _provenance_rows())
    missing = [title for title in titles if _section_key(title) not in recorded]
    if not missing:
        return "all %d sections have a provenance row" % len(titles), 0
    lines = ["%d of %d sections have no provenance row:" % (len(missing), len(titles))]
    lines.extend("- " + ad_core.clean(title, SECTION_CHARS) for title in missing)
    return "\n".join(lines), 1
