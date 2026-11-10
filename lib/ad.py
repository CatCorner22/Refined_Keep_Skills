#!/usr/bin/env python3
"""agent-discipline command line and hook entry point. Standard library only.

Exit codes: 0 success or "allowed / pass / clean"; 1 a check said no;
2 usage error. ``ad.py hook NAME`` and ``ad.py deny-regex`` always exit 0,
because for a hook any other exit code is an error or a block.

Sub-commands:

  version
  manifest record PATH [--range A-B]... [--summary TEXT] [--url URL] | check PATH | show
  ledger add KIND TEXT... | check ACTION... | show | clear
  checkpoint write [TEXT...] | show            (write reads stdin when no TEXT)
  reinject [--full]
  scope set ROOT... [--allow REGEX]... | add ROOT | show
  approve [--minutes N] [--note TEXT] -- COMMAND...
  approvals show | clear
  fence-check COMMAND...                        exit 0 ALLOW, 1 BLOCK
  fetch-check COMMAND...                        exit 0 ALLOW, 1 BLOCK
  gate [TEXT...] [--file PATH] [--lenient]      exit 0 PASS, 1 blocked
  trim FILE|-
  provenance add SECTION SOURCE [--quote Q] [--confidence C] | show [SECTION] | audit FILE
  rules lint [ROOT] | rewrite FILE | compile [ROOT] [--script-path P]
  test-impact [--base REF] [--root DIR]
  regress init [--force] | show | record ID RESULT MODEL [--note N] [--force] | report
  deny-regex PATTERN...                         (hook form)
  hook NAME                                     (hook form; reads the hook input on stdin)
"""
import sys

# Keep byte-code out of skill folders: a __pycache__ directory there would show
# up as an untracked directory in the user's repository.
sys.dont_write_bytecode = True

import argparse
import importlib
import io
import json
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

EXIT_OK = 0
EXIT_NO = 1
EXIT_USAGE = 2

# Hook name -> (module, function). Modules are imported only when needed, so
# one broken module cannot take down the hooks of another.
HOOKS = {
    "session-start": ("ad_state", "hook_session_start"),
    "pre-bash": ("ad_guards", "hook_pre_bash"),
    "pre-write": ("ad_guards", "hook_pre_write"),
    "pre-fetch": ("ad_guards", "hook_pre_fetch"),
    "read-cache": ("ad_state", "hook_read_cache"),
    "record-read": ("ad_state", "hook_record_read"),
    "log": ("ad_guards", "hook_post_tool"),
    "log-failure": ("ad_gates", "hook_log_failure"),
    "completion-gate": ("ad_gates", "hook_completion_gate"),
}
# Version 1 hook names, kept so that an old hooks file keeps working.
LEGACY_HOOKS = {
    "reinject": "session-start",
    "validate-call": "pre-bash",
    "log-trim": "log",
}
FILE_TOOLS = ("Write", "Edit", "NotebookEdit")


def _module(name):
    """Import a sibling module on first use."""
    return importlib.import_module(name)


def _out(text):
    """Print text to stdout."""
    if text is not None:
        sys.stdout.write(str(text) + "\n")


# --------------------------------------------------------------------------
# Hook dispatch
# --------------------------------------------------------------------------

def _legacy_target(name, hook_input):
    """Map a version 1 hook name to its version 2 hook, using the tool name where needed."""
    tool = hook_input.get("tool_name")
    if name == "scope-fence":
        return "pre-write" if tool in FILE_TOOLS else "pre-bash"
    if name == "fetch-guard":
        return "pre-fetch" if tool == "WebFetch" else "pre-bash"
    return LEGACY_HOOKS.get(name)


def _hook_start_dir(hook_input):
    """Return the directory from which a hook looks for the state directory.

    The hook input's ``cwd`` follows Claude; ``CLAUDE_PROJECT_DIR`` is the
    fallback, then the process working directory.
    """
    for candidate in (hook_input.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR")):
        if isinstance(candidate, str) and candidate and os.path.isdir(candidate):
            return candidate
    return os.getcwd()


def run_hook(args):
    """Run the hook ``args[0]``; always return 0.

    The hook input is read once here to set the start directory, then handed
    to the hook function through a fresh stdin. Any unexpected exception is
    reported in one line on stderr and the tool call proceeds (fail-open).
    """
    name = args[0] if args else ""
    try:
        ad_core = _module("ad_core")
        ad_core.setup_stdio()
        raw = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read().encode("utf-8")
        sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", errors="replace")
        hook_input = ad_core.read_hook_input()
        sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", errors="replace")
        ad_core.set_start_dir(_hook_start_dir(hook_input))
        target = name if name in HOOKS else _legacy_target(name, hook_input)
        if target not in HOOKS:
            message = "agent-discipline: unknown hook name %r; nothing was checked" % name
            sys.stderr.write(message + "\n")
            _out(json.dumps({"systemMessage": message}))
            return EXIT_OK
        module_name, function_name = HOOKS[target]
        getattr(_module(module_name), function_name)()
    except SystemExit:
        pass
    except BaseException as error:  # fail-open: a hook must never break the session
        if isinstance(error, KeyboardInterrupt):
            raise
        sys.stderr.write("agent-discipline hook %s: internal error, call not checked (%s: %s)\n"
                         % (name, type(error).__name__, error))
    return EXIT_OK


def run_deny_regex(patterns):
    """Run the compiled-rule hook; always return 0 (the decision travels as JSON)."""
    try:
        _module("ad_core").setup_stdio()
        _module("ad_rules").deny_regex_hook(patterns)
    except SystemExit:
        pass
    except BaseException as error:  # fail-open
        if isinstance(error, KeyboardInterrupt):
            raise
        sys.stderr.write("agent-discipline deny-regex: internal error, call not checked (%s: %s)\n"
                         % (type(error).__name__, error))
    return EXIT_OK


# --------------------------------------------------------------------------
# Sub-command handlers. Each returns an exit code.
# --------------------------------------------------------------------------

def cmd_version(args):
    """Print the version."""
    _out("agent-discipline " + _module("ad_core").VERSION)
    return EXIT_OK


def cmd_manifest(args):
    """Read manifest: record a file, check a file, or show the manifest."""
    ad_state = _module("ad_state")
    if args.action == "record":
        ranges = [ad_state.parse_range(text) for text in args.range]
        source = "fetch" if args.url else "read"
        key, entry = ad_state.manifest_record(args.path, ranges=ranges, summary=args.summary,
                                              source=source, url=args.url)
        _out("recorded %s (%s, read %dx)" % (
            key, _module("ad_core").human_size(entry.get("size")), entry.get("reads", 1)))
        return EXIT_OK
    if args.action == "check":
        text, code = ad_state.manifest_check(args.path)
        _out(text)
        return code
    _out(ad_state.manifest_summary() or "(read manifest empty)")
    return EXIT_OK


def cmd_ledger(args):
    """Ledger: add an entry, check an action, show or archive the ledger."""
    ad_state = _module("ad_state")
    if args.action == "add":
        _out(ad_state.ledger_add(args.kind, " ".join(args.text)))
        return EXIT_OK
    if args.action == "check":
        text, code = ad_state.ledger_check(" ".join(args.text))
        _out(text)
        return code
    if args.action == "show":
        _out(ad_state.ledger_show())
        return EXIT_OK
    _out(ad_state.ledger_clear())
    return EXIT_OK


def cmd_checkpoint(args):
    """Checkpoint: write it from the arguments or from stdin, or show it."""
    ad_state = _module("ad_state")
    if args.action == "write":
        text = " ".join(args.text) if args.text else _module("ad_core").read_stdin_text()
        _out(ad_state.checkpoint_write(text))
        return EXIT_OK
    _out(ad_state.checkpoint_show())
    return EXIT_OK


def cmd_reinject(args):
    """Print the reinjection text."""
    _out(_module("ad_state").reinject(full=args.full) or "(no state recorded)")
    return EXIT_OK


def cmd_scope(args):
    """Declared roots: set them, add one, or show them."""
    ad_guards = _module("ad_guards")
    if args.action == "set":
        _out(ad_guards.scope_set(args.roots, args.allow or None))
    elif args.action == "add":
        _out(ad_guards.scope_add(args.root))
    else:
        _out(ad_guards.scope_show())
    return EXIT_OK


def _joined_command(words):
    """Return the command text from CLI words: one quoted command, or words joined by spaces."""
    words = list(words)
    if words and words[0] == "--":
        words = words[1:]
    return " ".join(words).strip()


def cmd_approve(args):
    """Store an approval for one exact command."""
    command = _joined_command(args.command)
    if not command:
        raise ValueError("no command given; usage: approve [--minutes N] [--note TEXT] -- COMMAND")
    _out(_module("ad_guards").approve(command, minutes=args.minutes, note=args.note))
    return EXIT_OK


def cmd_approvals(args):
    """Show or clear the approvals."""
    ad_guards = _module("ad_guards")
    _out(ad_guards.approvals_show() if args.action == "show" else ad_guards.approvals_clear())
    return EXIT_OK


def cmd_fence_check(args):
    """Ask the scope fence about one command; exit 0 ALLOW, 1 BLOCK."""
    command = _joined_command(args.command)
    if not command:
        raise ValueError("no command given")
    hook_input = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": os.getcwd()}
    reason = _module("ad_guards").scope_fence_decide(hook_input)
    if reason:
        _out("BLOCK " + reason)
        return EXIT_NO
    _out("ALLOW")
    return EXIT_OK


def cmd_fetch_check(args):
    """Ask the fetch guard about one command; exit 0 ALLOW, 1 BLOCK."""
    command = _joined_command(args.command)
    if not command:
        raise ValueError("no command given")
    reason, context = _module("ad_guards").fetch_guard_decide(command, cwd=os.getcwd())
    if reason:
        _out("BLOCK " + reason)
        return EXIT_NO
    _out("ALLOW")
    if context:
        _out(context)
    return EXIT_OK


def cmd_gate(args):
    """Run the completion gate on a message; exit 0 PASS, 1 blocked."""
    ad_core = _module("ad_core")
    ad_gates = _module("ad_gates")
    if args.file:
        with open(args.file, encoding="utf-8", errors="replace") as handle:
            message = handle.read()
    elif args.text:
        message = " ".join(args.text)
    else:
        message = ad_core.read_stdin_text()
    if not message.strip():
        raise ValueError("no message given: pass TEXT, --file PATH, or pipe the message on stdin")
    strict = not args.lenient and os.environ.get("AD_GATE_STRICT", "1").strip() != "0"
    reason = ad_gates.completion_gate_decide(message, session=None, strict=strict)
    if reason:
        _out(reason)
        return EXIT_NO
    _out("PASS")
    if strict and ad_gates.claims_completion(message) and not ad_gates.shell_commands_logged():
        _out("note: the tool log has no shell commands, so the Command line was not checked against it.")
    return EXIT_OK


def cmd_trim(args):
    """Print a trimmed view of a file or of stdin. Stores nothing."""
    ad_gates = _module("ad_gates")
    if args.file == "-":
        text = _module("ad_core").read_stdin_text()
        source = "stdin"
    else:
        with open(args.file, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        source = args.file
    view, kind = ad_gates.trim_output(text)
    _out("[%s] source: %s, %d characters, %d lines; nothing was stored" % (
        kind, source, len(text), len(text.splitlines())))
    _out(view)
    return EXIT_OK


def cmd_provenance(args):
    """Provenance: add a row, show rows, or audit a Markdown file."""
    ad_gates = _module("ad_gates")
    if args.action == "add":
        _out(ad_gates.provenance_add(args.section, args.source, args.quote, args.confidence))
        return EXIT_OK
    if args.action == "show":
        _out(ad_gates.provenance_show(args.section))
        return EXIT_OK
    text, code = ad_gates.provenance_audit(args.file)
    _out(text)
    return code


def _finding_text(finding):
    """Render one lint finding, whatever shape the rules module gives it."""
    if isinstance(finding, dict):
        line = finding.get("line")
        label = finding.get("kind") or finding.get("label") or finding.get("code") or ""
        message = finding.get("message") or finding.get("text") or finding.get("rule") or ""
        prefix = "L%s " % line if line else ""
        middle = "[%s] " % label if label else ""
        return (prefix + middle + str(message)).strip()
    return str(finding)


def cmd_rules(args):
    """Rules files: lint them, print rewrite templates, or compile blockable rules."""
    ad_rules = _module("ad_rules")
    if args.action == "rewrite":
        with open(args.file, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
        printed = 0
        for number, line in enumerate(lines, 1):
            template = ad_rules.rewrite_template(line)
            if template:
                _out("L%d: %s" % (number, template))
                printed += 1
        if not printed:
            _out("(no negative rules found)")
        return EXIT_OK
    files = ad_rules.find_rule_files(args.root)
    results = [ad_rules.lint_rules(path) for path in files]
    if args.action == "compile":
        _out(json.dumps(ad_rules.compile_rules(results, script_path=args.script_path), indent=1))
        return EXIT_OK
    if not results:
        _out("(no rules files found under %s)" % args.root)
        return EXIT_OK
    total = 0
    for result in results:
        findings = result.get("findings") or []
        total += len(findings)
        _out("%s (%s lines): %d findings" % (result.get("file"), result.get("lines", "?"), len(findings)))
        for finding in findings:
            _out("- " + _finding_text(finding))
    return EXIT_NO if total else EXIT_OK


def cmd_test_impact(args):
    """Map changed files to tests and print the result as JSON."""
    ad_rules = _module("ad_rules")
    changed, deleted = ad_rules.changed_files(base=args.base, root=args.root)
    _out(json.dumps(ad_rules.test_impact(changed, root=args.root, deleted=deleted), indent=1))
    return EXIT_OK


def cmd_regress(args):
    """Regression set: create it, show it, record a result, or print the scoreboard."""
    ad_regress = _module("ad_regress")
    if args.action == "init":
        _out(ad_regress.regress_init(force=args.force))
    elif args.action == "show":
        _out(ad_regress.regress_show())
    elif args.action == "record":
        _out(ad_regress.regress_record(args.id, args.result, args.model, note=args.note, force=args.force))
    else:
        _out(ad_regress.regress_report())
    return EXIT_OK


# --------------------------------------------------------------------------
# Argument parser
# --------------------------------------------------------------------------

def _actions(parser, name):
    """Add a required set of action sub-parsers to ``parser`` and return it."""
    actions = parser.add_subparsers(dest="action", metavar="ACTION")
    actions.required = True
    return actions


def build_parser():
    """Build the argument parser for every sub-command except ``hook`` and ``deny-regex``."""
    parser = argparse.ArgumentParser(
        prog="ad.py", description="agent-discipline command line. State lives in .agent/ "
        "at the repository root (override with AGENT_STATE_DIR).")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    commands.required = True

    commands.add_parser("version", help="print the version").set_defaults(handler=cmd_version)

    manifest = commands.add_parser("manifest", help="read manifest")
    manifest.set_defaults(handler=cmd_manifest)
    actions = _actions(manifest, "manifest")
    record = actions.add_parser("record", help="record a file that was read or fetched")
    record.add_argument("path")
    record.add_argument("--range", action="append", default=[], metavar="A-B",
                        help="line range that was read; repeatable")
    record.add_argument("--summary", default=None, help="what the file says, in a sentence or two")
    record.add_argument("--url", default=None, help="where the file was fetched from")
    actions.add_parser("check", help="status of one file; exit 0 when UNCHANGED").add_argument("path")
    actions.add_parser("show", help="list the recorded files")

    ledger = commands.add_parser("ledger", help="ledger of the user's permissions and limits")
    ledger.set_defaults(handler=cmd_ledger)
    actions = _actions(ledger, "ledger")
    add = actions.add_parser("add", help="add an entry")
    add.add_argument("kind", metavar="KIND", help="GRANT, FORBID, STOP, ACCEPT, SCOPE or NOTE")
    add.add_argument("text", nargs="+", metavar="TEXT")
    check = actions.add_parser("check", help="find an entry for an action; exit 0 GRANT, 1 FORBID, 3 no match")
    check.add_argument("text", nargs="+", metavar="ACTION")
    actions.add_parser("show", help="print the ledger")
    actions.add_parser("clear", help="archive the ledger and start a new one")

    checkpoint = commands.add_parser("checkpoint", help="checkpoint of the current task")
    checkpoint.set_defaults(handler=cmd_checkpoint)
    actions = _actions(checkpoint, "checkpoint")
    write = actions.add_parser("write", help="replace the checkpoint (reads stdin when no TEXT)")
    write.add_argument("text", nargs="*", metavar="TEXT")
    actions.add_parser("show", help="print the checkpoint")

    reinject = commands.add_parser("reinject", help="print ledger, checkpoint and read manifest")
    reinject.add_argument("--full", action="store_true", help="no character budget")
    reinject.set_defaults(handler=cmd_reinject)

    scope = commands.add_parser("scope", help="declared roots of the scope fence")
    scope.set_defaults(handler=cmd_scope)
    actions = _actions(scope, "scope")
    scope_set = actions.add_parser("set", help="replace the declared roots")
    scope_set.add_argument("roots", nargs="+", metavar="ROOT")
    scope_set.add_argument("--allow", action="append", default=[], metavar="REGEX",
                           help="also allow paths that match; repeatable")
    actions.add_parser("add", help="add one declared root").add_argument("root", metavar="ROOT")
    actions.add_parser("show", help="print the declared roots")

    approve = commands.add_parser("approve", help="approve one exact command for a limited time")
    approve.add_argument("--minutes", type=int, default=None, help="lifetime of the approval")
    approve.add_argument("--note", default="", help="why the user approved it")
    approve.add_argument("command", nargs=argparse.REMAINDER, metavar="-- COMMAND")
    approve.set_defaults(handler=cmd_approve)

    approvals = commands.add_parser("approvals", help="stored approvals")
    approvals.set_defaults(handler=cmd_approvals)
    actions = _actions(approvals, "approvals")
    actions.add_parser("show", help="list the approvals")
    actions.add_parser("clear", help="remove every approval")

    fence = commands.add_parser("fence-check", help="ask the scope fence about a command")
    fence.add_argument("command", nargs=argparse.REMAINDER, metavar="COMMAND")
    fence.set_defaults(handler=cmd_fence_check)

    fetch = commands.add_parser("fetch-check", help="ask the fetch guard about a command")
    fetch.add_argument("command", nargs=argparse.REMAINDER, metavar="COMMAND")
    fetch.set_defaults(handler=cmd_fetch_check)

    gate = commands.add_parser("gate", help="run the completion gate on a message")
    gate.add_argument("text", nargs="*", metavar="TEXT")
    gate.add_argument("--file", default=None, metavar="PATH", help="read the message from a file")
    gate.add_argument("--lenient", action="store_true", help="skip the tool-log check of the Command line")
    gate.set_defaults(handler=cmd_gate)

    trim = commands.add_parser("trim", help="print a trimmed view of long output")
    trim.add_argument("file", metavar="FILE", help="a file, or - for stdin")
    trim.set_defaults(handler=cmd_trim)

    provenance = commands.add_parser("provenance", help="which source supports which section")
    provenance.set_defaults(handler=cmd_provenance)
    actions = _actions(provenance, "provenance")
    add = actions.add_parser("add", help="add a row")
    add.add_argument("section")
    add.add_argument("source")
    add.add_argument("--quote", default="")
    add.add_argument("--confidence", default="probable",
                     help="established, probable, contested, single-source or unknown")
    show = actions.add_parser("show", help="print the rows")
    show.add_argument("section", nargs="?", default=None)
    actions.add_parser("audit", help="list headings without a row; exit 1 when some are missing"
                       ).add_argument("file", metavar="FILE")

    rules = commands.add_parser("rules", help="lint, rewrite and compile rules files")
    rules.set_defaults(handler=cmd_rules)
    actions = _actions(rules, "rules")
    actions.add_parser("lint", help="lint the rules files under ROOT; exit 1 when there are findings"
                       ).add_argument("root", nargs="?", default=".", metavar="ROOT")
    actions.add_parser("rewrite", help="print a fill-in template for each negative rule"
                       ).add_argument("file", metavar="FILE")
    compile_parser = actions.add_parser("compile", help="print deny rules and a hook fragment")
    compile_parser.add_argument("root", nargs="?", default=".", metavar="ROOT")
    compile_parser.add_argument("--script-path", default=None, metavar="P",
                                help="path of ad.py to put in the hook fragment")

    impact = commands.add_parser("test-impact", help="map changed files to tests")
    impact.add_argument("--base", default=None, metavar="REF")
    impact.add_argument("--root", default=".", metavar="DIR")
    impact.set_defaults(handler=cmd_test_impact)

    regress = commands.add_parser("regress", help="personal regression set")
    regress.set_defaults(handler=cmd_regress)
    actions = _actions(regress, "regress")
    actions.add_parser("init", help="create set.json").add_argument(
        "--force", action="store_true", help="back up the existing set.json and write the default set")
    actions.add_parser("show", help="print the set")
    record = actions.add_parser("record", help="store one result")
    record.add_argument("id", metavar="ID")
    record.add_argument("result", metavar="RESULT", help="pass, partial or fail")
    record.add_argument("model", metavar="MODEL", help="exact model identifier")
    record.add_argument("--note", default="")
    record.add_argument("--force", action="store_true", help="accept an id that is not in the set")
    actions.add_parser("report", help="print the scoreboard")

    commands.add_parser("hook", help="run as a hook: ad.py hook NAME (reads the hook input on stdin)")
    commands.add_parser("deny-regex", help="hook form: deny a shell command that matches a PATTERN")
    return parser


def main(argv=None):
    """Run the command line; return the exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "hook":
        return run_hook(argv[1:])
    if argv and argv[0] == "deny-regex":
        return run_deny_regex(argv[1:])
    try:
        _module("ad_core").setup_stdio()
        args = build_parser().parse_args(argv)
        return args.handler(args)
    except (OSError, ValueError) as error:
        sys.stderr.write("error: %s\n" % error)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
