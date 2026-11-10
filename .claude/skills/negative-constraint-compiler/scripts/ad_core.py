"""Shared core of the agent-discipline library. Standard library only, Python 3.8+.

This module owns three things that every other module relies on:

1. The state directory (``.agent/``): where it is, how it is created, and how
   its files are read and written safely (atomic replace, advisory lock,
   no symbolic links, owner-only permissions).
2. The hook input and output formats of Claude Code.
3. Small text helpers: timestamps, cleaning untrusted text, redacting secrets.

Files in the state directory:

    manifest.json     read manifest
    ledger.md         ledger
    approvals.json    approvals
    scope.json        declared roots
    CHECKPOINT.md     checkpoint
    toollog.jsonl     tool log
    provenance.jsonl  provenance rows
    outputs/          full tool outputs that were trimmed
    regress/          regression set and results

This module imports nothing else from the library.
"""
import contextlib
import datetime
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import unicodedata

try:
    import fcntl
except ImportError:  # Windows: no advisory lock, proceed without one.
    fcntl = None

VERSION = "2.0.0"

STATE_DIR_NAME = ".agent"
MARKER_NAME = ".ad-state"
LOCK_NAME = ".lock"
STATE_DIR_MODE = 0o700
STATE_FILE_MODE = 0o600
LOCK_TIMEOUT_SECONDS = 2.0
LOCK_POLL_SECONDS = 0.02
MAX_CONTEXT_CHARS = 9000
ELLIPSIS = "…"
REDACTED = "[REDACTED]"

_start_dir = None
_lock_depth = 0
_prepared_dirs = set()


# --------------------------------------------------------------------------
# Environment variables
# --------------------------------------------------------------------------

def env_int(name, default, minimum=None, maximum=None):
    """Read an integer environment variable; a missing or bad value gives ``default``.

    A bad value never raises, because hooks must not fail on a typo in the
    user's environment.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return _clamp(value, minimum, maximum)


def env_float(name, default, minimum=None, maximum=None):
    """Read a float environment variable; a missing, bad or non-finite value gives ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        return default
    if value != value or value in (float("inf"), float("-inf")):
        return default
    return _clamp(value, minimum, maximum)


def _clamp(value, minimum, maximum):
    """Limit ``value`` to the closed interval [minimum, maximum]; ``None`` means no bound."""
    if minimum is not None and value < minimum:
        return minimum
    if maximum is not None and value > maximum:
        return maximum
    return value


# --------------------------------------------------------------------------
# State directory
# --------------------------------------------------------------------------

def set_start_dir(path):
    """Set the directory from which the state directory is searched.

    The hook dispatcher calls this with the hook input's ``cwd`` so that a
    hook started from a subdirectory finds the same state directory as the
    CLI started from the repository root. ``None`` or an empty value restores
    the default (the process working directory).
    """
    global _start_dir
    if path and isinstance(path, str):
        _start_dir = os.path.abspath(path)
    else:
        _start_dir = None


def start_dir():
    """Return the directory from which the state directory is searched."""
    if _start_dir:
        return _start_dir
    return os.getcwd()


def _resolve_state_dir():
    """Find the state directory without creating anything.

    Order: ``AGENT_STATE_DIR``; else the nearest ancestor that already holds a
    marked state directory or a ``.git`` entry; else the start directory.
    """
    start = start_dir()
    override = os.environ.get("AGENT_STATE_DIR")
    if override:
        return os.path.abspath(os.path.join(start, os.path.expanduser(override)))
    current = start
    while True:
        candidate = os.path.join(current, STATE_DIR_NAME)
        if os.path.exists(os.path.join(candidate, MARKER_NAME)):
            return candidate
        if os.path.exists(os.path.join(current, ".git")):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return os.path.join(start, STATE_DIR_NAME)


def _prepare_state_dir(path):
    """Create the state directory with its marker and its ``.gitignore``.

    The ``.gitignore`` holds ``*`` so that nothing in the state directory is
    ever committed. Work is done once per directory per process.
    """
    if path in _prepared_dirs and os.path.isdir(path):
        return
    os.makedirs(path, mode=STATE_DIR_MODE, exist_ok=True)
    _write_if_absent(os.path.join(path, MARKER_NAME), VERSION + "\n")
    _write_if_absent(os.path.join(path, ".gitignore"), "*\n")
    _prepared_dirs.add(path)


def _write_if_absent(path, text):
    """Create ``path`` with ``text`` unless something already exists there."""
    if os.path.lexists(path):
        return
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, STATE_FILE_MODE)
    except FileExistsError:
        return
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def state_dir(create=True):
    """Return the state directory path; create it when ``create`` is true.

    Read-only commands pass ``create=False`` (or call ``state_exists()``)
    so that looking at state never leaves a directory behind.
    """
    path = _resolve_state_dir()
    if create:
        _prepare_state_dir(path)
    return path


def state_exists():
    """Return True when the state directory already exists."""
    return os.path.isdir(_resolve_state_dir())


def state_path(name, create=True):
    """Return the path of the state file ``name``.

    ``create`` has the same meaning as in ``state_dir``. Pass ``create=False``
    from read-only code.
    """
    return os.path.join(state_dir(create=create), name)


def _refuse_symlink(path):
    """Raise OSError when ``path`` is a symbolic link.

    A repository could plant a link inside its state directory that points at
    a file elsewhere; following it would read or overwrite that file.
    """
    if os.path.islink(path):
        raise OSError("refusing to use a symbolic link as a state file: " + path)


@contextlib.contextmanager
def state_lock():
    """Hold the advisory lock of the state directory for a read-modify-write.

    Re-entrant within one process. When the lock cannot be taken within
    ``LOCK_TIMEOUT_SECONDS`` the caller proceeds without it: losing one update
    in a rare race is better than hanging a hook.
    """
    global _lock_depth
    if fcntl is None or _lock_depth > 0:
        _lock_depth += 1
        try:
            yield
        finally:
            _lock_depth -= 1
        return
    handle = _open_lock_file()
    locked = _acquire(handle)
    _lock_depth += 1
    try:
        yield
    finally:
        _lock_depth -= 1
        if handle is not None:
            if locked:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            handle.close()


def _open_lock_file():
    """Open the lock file; return None when that is impossible (fail-open)."""
    try:
        path = state_path(LOCK_NAME)
        _refuse_symlink(path)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, STATE_FILE_MODE)
        return os.fdopen(fd, "r+")
    except OSError:
        return None


def _acquire(handle):
    """Try to take the exclusive lock until the timeout; return True on success."""
    if handle is None:
        return False
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(LOCK_POLL_SECONDS)


# --------------------------------------------------------------------------
# File helpers
# --------------------------------------------------------------------------

def read_text(name, default=""):
    """Return the text of state file ``name``; ``default`` on any problem."""
    try:
        path = state_path(name, create=False)
        _refuse_symlink(path)
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except (OSError, ValueError):
        return default


def write_text(name, text):
    """Replace state file ``name`` with ``text`` atomically.

    The text goes to a unique temporary file in the same directory first, so
    a crash or a concurrent writer never leaves a half-written file.
    """
    path = state_path(name)
    _refuse_symlink(path)
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=STATE_DIR_MODE, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="replace") as handle:
            handle.write(text)
        os.replace(temp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_path)
        raise


def load_json(name, default):
    """Return the parsed JSON of state file ``name``; ``default`` on any error.

    A value whose type differs from the type of ``default`` also gives
    ``default``, so callers can index the result without checking it.
    """
    try:
        path = state_path(name, create=False)
        _refuse_symlink(path)
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, RecursionError):
        return default
    if default is not None and not isinstance(data, type(default)):
        return default
    return data


def save_json(name, data):
    """Write ``data`` as JSON to state file ``name`` atomically."""
    write_text(name, json.dumps(data, indent=1, sort_keys=True) + "\n")


def update_json(name, default, fn):
    """Read, modify and write state file ``name`` under the state lock.

    ``fn`` receives the current value and returns the new one. When ``fn``
    returns None the value it was given (possibly modified in place) is saved.
    Returns the saved value.
    """
    with state_lock():
        current = load_json(name, default)
        updated = fn(current)
        if updated is None:
            updated = current
        save_json(name, updated)
        return updated


def append_line(name, line):
    """Append one line to state file ``name`` with a single ``os.write``.

    One write on a file opened with ``O_APPEND`` keeps lines from concurrent
    hooks whole. Embedded newlines are replaced so one call is one line.
    """
    path = state_path(name)
    _refuse_symlink(path)
    text = line.replace("\r", " ").replace("\n", " ") + "\n"
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, STATE_FILE_MODE)
    try:
        os.write(fd, text.encode("utf-8", "replace"))
    finally:
        os.close(fd)


def read_lines(name):
    """Return the lines of state file ``name`` without line ends; never raises."""
    return read_text(name).splitlines()


def read_jsonl(name):
    """Return the JSON objects of a JSON-lines state file.

    Lines that do not parse, and values that are not objects, are skipped:
    a line cut short by a crash must not make the whole file unreadable.
    """
    records = []
    for line in read_lines(name):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def rotate(name, max_bytes, keep_lines):
    """Shrink state file ``name`` to its last ``keep_lines`` lines once it exceeds ``max_bytes``.

    Returns True when the file was rewritten. Never raises.
    """
    try:
        path = state_path(name, create=False)
        if os.path.islink(path) or os.path.getsize(path) <= max_bytes:
            return False
        with state_lock():
            lines = read_lines(name)
            kept = lines[-keep_lines:] if keep_lines > 0 else []
            write_text(name, "".join(line + "\n" for line in kept))
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------

def time_now():
    """Return the current local time as an aware datetime.

    This is the single clock of the library; tests replace it.
    """
    return datetime.datetime.now().astimezone()


def now():
    """Return the current local time as ISO 8601 text with UTC offset, to the second."""
    return time_now().replace(microsecond=0).isoformat()


def parse_ts(text):
    """Parse a timestamp written by ``now()``; return an aware datetime or None.

    A timestamp without an offset (written by version 1) is read as local time.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    value = text.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        try:
            parsed = parsed.astimezone()
        except (OverflowError, OSError, ValueError):
            return None
    return parsed


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------

def clean(text, limit=200):
    """Make untrusted text safe for one line of injected context or a table cell.

    Control and format characters are removed (they can hide or reorder text),
    every whitespace run becomes one space, and the result is cut to ``limit``
    characters, ending in an ellipsis when something was cut.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    kept = []
    for char in text:
        if char.isspace():
            kept.append(" ")
        elif unicodedata.category(char) in ("Cc", "Cf", "Cs", "Co", "Cn"):
            continue
        else:
            kept.append(char)
    result = " ".join("".join(kept).split())
    if limit is not None and limit > 0 and len(result) > limit:
        result = result[:limit - 1].rstrip() + ELLIPSIS
    return result


_REDACT_RULES = (
    # Authorization headers: keep the scheme word, mask the credential.
    (re.compile(r"(?i)(authorization\s*[:=]\s*[\"']?(?:bearer|basic|token|digest)?\s*)[^\s\"']+"),
     r"\1" + REDACTED),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1" + REDACTED),
    # name=value and name: value pairs whose name says it is a secret.
    (re.compile(
        r"(?i)\b([A-Za-z0-9_.-]*(?:token|secret|password|passwd|pwd|api[_-]?key|access[_-]?key)"
        r"[A-Za-z0-9_-]*\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s&;|\"']+)"),
     r"\1" + REDACTED),
    # Command-line options that carry a secret as the next word.
    (re.compile(r"(?i)(--(?:password|passwd|token|secret|api-key)\s+)(\"[^\"]*\"|'[^']*'|\S+)"),
     r"\1" + REDACTED),
    # Credentials inside URLs: scheme://user:pass@host
    (re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://[^/\s:@]*:)[^@\s/]+@"), r"\1" + REDACTED + "@"),
    # Well-known key shapes.
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"), REDACTED),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), REDACTED),
)


def redact(text):
    """Mask obvious secrets before text is logged or stored.

    Covers Authorization and Bearer values, ``token|secret|password|api_key``
    pairs, credentials in URLs and a few well-known key shapes. It is a
    best-effort filter, not a guarantee.
    """
    if not isinstance(text, str):
        return ""
    for pattern, replacement in _REDACT_RULES:
        text = pattern.sub(replacement, text)
    return text


def human_size(n):
    """Format a byte count for people, for example ``1.5 MB``; ``?`` when unknown."""
    try:
        value = float(n)
    except (TypeError, ValueError):
        return "?"
    if value < 0:
        return "?"
    if value < 1024:
        return "%d B" % int(value)
    for unit in ("KB", "MB", "GB"):
        value /= 1024.0
        if value < 1024:
            return "%.1f %s" % (value, unit)
    return "%.1f TB" % (value / 1024.0)


def sha256_text(text):
    """Return the SHA-256 hex digest of ``text`` encoded as UTF-8."""
    if not isinstance(text, str):
        text = str(text)
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


# --------------------------------------------------------------------------
# Standard streams
# --------------------------------------------------------------------------

def setup_stdio():
    """Make stdout and stderr UTF-8 with replacement, whatever the locale says.

    Without this a path with a non-ASCII name makes ``print`` raise under a
    C locale, and a hook would end in a traceback.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def read_stdin_text():
    """Read all of stdin as UTF-8 with replacement, whatever the locale says."""
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        return buffer.read().decode("utf-8", "replace")
    return sys.stdin.read()


# --------------------------------------------------------------------------
# Hook input and output
# --------------------------------------------------------------------------

def read_hook_input():
    """Parse the JSON object the host writes to stdin; ``{}`` on any problem."""
    try:
        raw = read_stdin_text()
        if not raw.strip():
            return {}
        data = json.loads(raw)
    except (OSError, ValueError, RecursionError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _emit(payload):
    """Write one JSON object to stdout. ASCII-only output is safe in every locale."""
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def fit_context(text):
    """Keep injected context under ``MAX_CONTEXT_CHARS`` by dropping whole trailing lines.

    The host replaces context over 10,000 characters with a file path, so
    longer text would not reach the model as written.
    """
    if len(text) <= MAX_CONTEXT_CHARS:
        return text
    marker = "(shortened: the full text did not fit)"
    budget = MAX_CONTEXT_CHARS - len(marker) - 1
    kept = []
    used = 0
    for line in text.splitlines():
        if used + len(line) + 1 > budget:
            break
        kept.append(line)
        used += len(line) + 1
    kept.append(marker)
    return "\n".join(kept)


def deny(reason):
    """PreToolUse: deny the tool call with ``reason`` and exit 0.

    The decision travels in the JSON on stdout. The exit code stays 0 because
    the host reads JSON only on exit 0; exit 2 would discard it.
    """
    _emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }})
    sys.stderr.write(reason + "\n")
    sys.exit(0)


def allow(context=None, event="PreToolUse"):
    """Let the tool call proceed; optionally add factual context for the model. Exits 0."""
    if context:
        _emit({"hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": fit_context(context),
        }})
    sys.exit(0)


def stop_block(reason):
    """Stop hook: prevent the stop once and give the model ``reason``. Exits 0."""
    _emit({"decision": "block", "reason": reason})
    sys.exit(0)


def emit_session_context(text):
    """SessionStart hook: add ``text`` to the model's context. Exits 0."""
    if text:
        _emit({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": fit_context(text),
        }})
    sys.exit(0)
