"""Guards: approvals, the scope fence, the fetch guard and the retry rule.

The guards judge parsed commands (see `ad_shell`), never prose: text inside a
commit message, an `echo` argument or a grep pattern cannot trigger a rule.
The only unlock is an approval: a time-limited permission for one exact
command, recorded with `ad.py approve` after the user agrees. No ledger text
unlocks anything.
"""

import datetime
import json
import os
import re
import shlex
import sys
import tempfile

import ad_core
import ad_gates
import ad_shell
import ad_state

APPROVALS_FILE = "approvals.json"
SCOPE_FILE = "scope.json"
PROTECTED_STATE_FILES = ("approvals.json", "scope.json", "ledger.md")

APPROVAL_MINUTES_DEFAULT = 30
APPROVAL_MINUTES_MAX = 1440
PREVIEW_CHARS = 160
QUOTED_COMMAND_MAX_CHARS = 2000
FETCH_DUP_MB_DEFAULT = 5.0
RETRY_LIMIT_DEFAULT = 2
BYTES_PER_MB = 1024 * 1024
BIG_EXTENSIONS_DEFAULT = "cram,bam,fastq,fastq.gz,fq.gz,bcf,vcf.gz,iso,img,dmg,vmdk,qcow2,ova,gguf,safetensors"
PROTECTED_BRANCHES_DEFAULT = "main,master"

SHELL_TOOLS = ("Bash", "PowerShell")
FILE_TOOLS = ("Write", "Edit", "NotebookEdit")
MUTATING_TOOLS = SHELL_TOOLS + FILE_TOOLS

LABEL_RECURSIVE_DELETE = "recursive delete"
LABEL_FIND_DELETE = "find delete"
LABEL_FORCE_PUSH = "force push"
LABEL_PROTECTED_PUSH = "push to protected branch"
LABEL_DISCARD = "discards uncommitted work"
LABEL_HISTORY = "history rewrite"
LABEL_SQL = "destructive SQL"
LABEL_PRODUCTION = "production data"
LABEL_INFRA = "infrastructure delete"
LABEL_PUBLISH = "publish or deploy"
LABEL_SYSTEM = "system destructive"
LABEL_INLINE = "inline delete code"

UNPARSED_DETAIL = "matched as raw text because the command could not be parsed"

DEVICE_FILES = ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty")
DEVICE_PREFIXES = ("/dev/fd/", "/proc/self/fd/")
SYSTEM_TEMP_DIRS = ("/tmp", "/var/tmp")

_WIDE_TARGETS = ("/", "~", "$HOME", "${HOME}", ".", "..", "*")
_DELETE_PROGRAMS = ("rm", "shred", "unlink")
_GLOB_CHARS = "*?["

_DB_CLIENTS = ("psql", "mysql", "mariadb", "sqlite3", "sqlcmd", "mongosh", "mongo", "redis-cli",
               "clickhouse-client", "duckdb", "bq", "snowsql", "cockroach", "pg_restore")
_DB_DROP_PROGRAMS = ("dropdb", "dropuser")
_PRODUCTION_IGNORED_SUFFIXES = (".sql", ".md", ".txt")
_MIGRATION_RUNNERS = ("prisma", "drizzle-kit", "supabase", "alembic", "knex", "sequelize",
                      "sequelize-cli", "flyway", "liquibase")
_RUNNER_DESTRUCTIVE_RES = tuple(re.compile(pattern) for pattern in (
    r"^prisma (?:.* )?migrate reset\b",
    r"^prisma .*--force-reset\b",
    r"^(?:rails|rake) .*\bdb:(?:drop|reset|purge|migrate:reset)\b",
    r"^(?:manage\.py|django-admin) (?:.* )?(?:flush|sqlflush|reset_db)\b",
    r"^alembic (?:.* )?downgrade\b",
    r"^knex (?:.* )?migrate:rollback\b.*--all\b",
    r"^sequelize(?:-cli)? (?:.* )?db:(?:drop|migrate:undo:all|seed:undo:all)\b",
    r"^supabase (?:.* )?db reset\b",
    r"^drizzle-kit (?:.* )?drop\b",
    r"^flyway (?:.* )?clean\b",
    r"^liquibase (?:.* )?(?:drop-all|dropAll)\b",
))
_PACKAGE_RUNNERS = ("npx", "bunx", "pnpx")
_PACKAGE_MANAGERS = ("pnpm", "yarn", "bun", "npm")
_PACKAGE_MANAGER_EXEC = ("exec", "dlx", "x")
_ENVIRONMENT_RUNNERS = ("bundle", "poetry", "uv", "pipenv", "pdm", "hatch")
_PYTHON_RE = re.compile(r"^python(\d+(\.\d+)?)?$")
_INTERPRETER_RE = re.compile(r"^(python(\d+(\.\d+)?)?|perl|ruby|node|nodejs|bun|deno|php)$")
_INLINE_CODE_OPTION_RE = re.compile(r"^(-c|--eval|-r|-[a-zA-Z0-9.]*[eE])$")
_INLINE_DELETE_RE = re.compile(
    r"rmtree|os\.remove|os\.unlink|unlink\(|rmSync|rmdirSync|\brm\s+-[a-zA-Z]*[rR]"
    r"|File\.delete|FileUtils\.rm|git\s+push\s[^'\"]*(?:--force\b|\s-f\b)")

_SQL_COMMENT_RE = re.compile(r"(?:^|(?<=\s))--\s[^\n]*|/\*.*?\*/", re.S)
_SQL_DROP_RE = re.compile(r"\bDROP\s+(TABLE|DATABASE|SCHEMA|INDEX|VIEW|OWNED|COLUMN|ROLE|USER)\b", re.I)
_SQL_TRUNCATE_RE = re.compile(r"\bTRUNCATE\b", re.I)
_SQL_DELETE_RE = re.compile(r"\bDELETE\s+FROM\s+\S+", re.I)
_SQL_UPDATE_RE = re.compile(r"\bUPDATE\s+\S+\s+SET\b", re.I)
_SQL_WHERE_RE = re.compile(r"\bWHERE\b", re.I)
_SQL_TAUTOLOGY_RE = re.compile(r"\bWHERE\s+\(?\s*(?:1\s*=\s*1|true|'([^']*)'\s*=\s*'\1')\s*\)?\s*$", re.I)
_SQL_OTHER_RE = re.compile(r"\bFLUSHALL\b|\bFLUSHDB\b|dropDatabase|\.drop\(|deleteMany\(\s*\{\s*\}\s*\)", re.I)

_PROD_WORD_RE = re.compile(r"(?<![A-Za-z0-9])(?:prod|production)(?![A-Za-z0-9])", re.I)
_LIVE_OPTIONS = ("--env", "-e", "--environment")

_FORK_BOMB_RE = re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")
_BLOCK_DEVICE_RE = re.compile(r"^/dev/(sd|hd|vd|xvd|nvme|mmcblk|disk|rdisk|dm-|loop)")
_CHMOD_MODE_OPTION_RE = re.compile(r"^-[rwxXstugo]+$")
_AWS_DELETE_RE = re.compile(r"^(delete|terminate|deregister|purge)-")

_KUBECTL_SHORT_VALUES = "nflocs"
_KUBECTL_LONG_VALUES = ("--namespace", "--context", "--kubeconfig", "--filename", "--selector",
                        "--output", "--cluster", "--user", "--server", "--as", "--container", "--token")
_HELM_LONG_VALUES = ("--namespace", "--kube-context", "--kubeconfig")

# Conservative raw-text rules: used when a command cannot be parsed, for PowerShell, and to
# decide whether to fail closed after an internal error.
_COMMAND_START = r"(?:^|[;&|(`\n]\s*)(?:sudo\s+)?"
_RAW_RULES = tuple((label, re.compile(pattern, flags)) for label, pattern, flags in (
    (LABEL_RECURSIVE_DELETE, r"\brm\b[^|;&\n]*\s-(?:-recursive\b|[a-zA-Z]*[rR])", 0),
    (LABEL_RECURSIVE_DELETE,
     r"\b(?:remove-item|ri|rm|del|erase|rd|rmdir)\b[^|;\n]*\s-(?:r|rec|recurse)\b", re.I),
    (LABEL_FIND_DELETE, r"\bfind\b[^|;&\n]*\s-(?:delete\b|exec(?:dir)?\s+(?:\S*/)?(?:rm|shred|unlink)\b)", 0),
    (LABEL_FORCE_PUSH,
     r"\bgit\b[^|;&\n]*\bpush\b[^|;&\n]*\s(?:--force(?![-\w])|-[a-zA-Z]*f\b|--mirror\b|--delete\b|\+\S)", 0),
    (LABEL_PROTECTED_PUSH, r"\bgit\b[^|;&\n]*\bpush\b[^|;&\n]*[\s:/+](?:main|master)(?:\s|$)", 0),
    (LABEL_DISCARD, r"\bgit\b[^|;&\n]*\b(?:reset\s+--hard|clean\s[^|;&\n]*-[a-zA-Z]*f|checkout\s+(?:--\s|\.)"
                    r"|stash\s+(?:drop|clear))", 0),
    (LABEL_HISTORY, r"\bgit\b[^|;&\n]*\b(?:filter-branch|filter-repo|reflog\s+expire|update-ref\s+-d|branch\s+-D)", 0),
    (LABEL_SQL, r"\b(?:DROP\s+(?:TABLE|DATABASE|SCHEMA|INDEX)|TRUNCATE|FLUSHALL|FLUSHDB)\b", re.I),
    (LABEL_INFRA, r"\bterraform\b[^|;&\n]*\b(?:destroy|apply\b[^|;&\n]*-destroy)|\bkubectl\b[^|;&\n]*\bdelete\b"
                  r"|\bhelm\s+(?:uninstall|delete)\b|\bpulumi\s+destroy\b|\bdocker\s+system\s+prune\b"
                  r"|\baws\b[^|;&\n]*\s(?:delete|terminate)-", 0),
    (LABEL_PUBLISH, r"\b(?:npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b|\bcargo\s+publish\b|\bgem\s+push\b", 0),
    (LABEL_SYSTEM, r"\bmkfs|\bdd\b[^|;&\n]*\bof=|" + _COMMAND_START
                   + r"(?:shred|shutdown|reboot|halt|poweroff|killall|format-volume)\b", re.I),
))


# ---------------------------------------------------------------- small helpers


def _cli():
    """Return the command prefix that runs this copy of the CLI, for the next-step text of a denial."""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ad.py")
    return 'python3 "%s"' % script


def _preview(command):
    """Return a short, redacted, one-line preview of a command."""
    return ad_core.clean(ad_core.redact(command), PREVIEW_CHARS)


def _approve_step(command):
    """Return the exact next step that ends every denial."""
    if len(command) > QUOTED_COMMAND_MAX_CHARS:
        quoted = "'<the exact command>'"
    else:
        quoted = shlex.quote(command)
    return ("Next step: ask the user. After an explicit yes, run `%s approve -- %s`, "
            "then retry the identical command." % (_cli(), quoted))


def _tool_input(inp):
    """Return the hook input's `tool_input` object, or an empty dict."""
    value = inp.get("tool_input") if isinstance(inp, dict) else None
    return value if isinstance(value, dict) else {}


def _text(value):
    """Return `value` when it is a string, else an empty string."""
    return value if isinstance(value, str) else ""


def _hook_cwd(inp):
    """Return the working directory of the tool call: the hook input's `cwd`, else the start directory."""
    return _text(inp.get("cwd")) or ad_core.start_dir()


def _unique(items):
    """Return `items` without duplicates, first occurrence first."""
    seen = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def _short_flags(args):
    """Return the set of letters given as single-dash options (`-rf` gives r and f), up to `--`."""
    letters = set()
    for word in args:
        if word == "--":
            break
        if word.startswith("-") and not word.startswith("--"):
            letters.update(word[1:])
    return letters


def _long_flags(args):
    """Return the set of long option names (without `=value`), up to `--`."""
    names = set()
    for word in args:
        if word == "--":
            break
        if word.startswith("--"):
            names.add(word.split("=", 1)[0])
    return names


def _operands(args):
    """Return the words that are not options; everything after `--` is an operand."""
    found = []
    for index, word in enumerate(args):
        if word == "--":
            found.extend(args[index + 1:])
            break
        if not word.startswith("-") or word == "-":
            found.append(word)
    return found


def _is_wide_target(operand):
    """Return True for an operand that names the file-system root, the home directory, `.`, `..` or everything."""
    if operand.startswith("/*"):
        return True
    trimmed = operand.rstrip("/") or "/"
    return trimmed in _WIDE_TARGETS or operand in ("./*", "../*", "~/*", "$HOME/*", "${HOME}/*")


# ---------------------------------------------------------------- approvals


def normalize_command(cmd):
    """Strip a command and collapse every whitespace run to one space."""
    if not isinstance(cmd, str):
        return ""
    return " ".join(cmd.split())


def _command_hash(cmd):
    """Return the hash that identifies one exact (normalized) command."""
    return ad_core.sha256_text(normalize_command(cmd))


def _is_live(entry, moment):
    """Return True when an approval entry is well-formed and has not expired at `moment`."""
    if not isinstance(entry, dict):
        return False
    expires = ad_core.parse_ts(_text(entry.get("expires")))
    return expires is not None and expires > moment


def _live_approvals():
    """Return the approvals that have not expired. Never creates the state directory."""
    if not ad_core.state_exists():
        return []
    moment = ad_core.time_now()
    return [entry for entry in ad_core.load_json(APPROVALS_FILE, []) if _is_live(entry, moment)]


def _approval_minutes(minutes):
    """Return the lifetime of a new approval in minutes, between 1 and the maximum."""
    if minutes is None:
        return ad_core.env_int("AD_APPROVAL_MINUTES", APPROVAL_MINUTES_DEFAULT, 1, APPROVAL_MINUTES_MAX)
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        raise ValueError("minutes must be a whole number")
    if value < 1:
        raise ValueError("minutes must be at least 1")
    return min(value, APPROVAL_MINUTES_MAX)


def approve(cmd, minutes=None, note=""):
    """Record a time-limited approval for one exact command; return a confirmation line.

    The approval stores a hash of the normalized command, so it unlocks that command and
    no other. Expired approvals are pruned on every write.
    """
    normalized = normalize_command(cmd)
    if not normalized:
        raise ValueError("no command given")
    lifetime = _approval_minutes(minutes)
    created = ad_core.time_now().replace(microsecond=0)
    expires = created + datetime.timedelta(minutes=lifetime)
    digest = _command_hash(normalized)
    entry = {
        "sha256": digest,
        "preview": _preview(normalized),
        "created": created.isoformat(),
        "expires": expires.isoformat(),
        "note": ad_core.clean(_text(note), PREVIEW_CHARS),
    }

    def apply(current):
        kept = [item for item in current if _is_live(item, created) and item.get("sha256") != digest]
        kept.append(entry)
        return kept

    ad_core.update_json(APPROVALS_FILE, [], apply)
    return "approved for %d minutes (until %s): %s" % (lifetime, entry["expires"], entry["preview"])


def is_approved(cmd):
    """Return True when an unexpired approval exists for exactly this command."""
    normalized = normalize_command(cmd)
    if not normalized:
        return False
    digest = _command_hash(normalized)
    return any(entry.get("sha256") == digest for entry in _live_approvals())


def approvals_show():
    """Return the unexpired approvals as text."""
    live = _live_approvals()
    if not live:
        return "no approvals"
    lines = ["%d approval(s):" % len(live)]
    for entry in live:
        line = "- until %s: %s" % (entry.get("expires"), entry.get("preview"))
        if entry.get("note"):
            line += " (note: %s)" % entry.get("note")
        lines.append(line)
    return "\n".join(lines)


def approvals_clear():
    """Remove every approval; return a confirmation line."""
    if not ad_core.state_exists():
        return "no approvals"
    count = len(_live_approvals())
    ad_core.save_json(APPROVALS_FILE, [])
    return "approvals cleared (%d)" % count


# ---------------------------------------------------------------- destructive classification


def _effective_command(argv):
    """Return (program, args) after wrappers, package runners and `python -m` are stripped.

    `npx prisma migrate reset`, `bundle exec rails db:drop` and `python manage.py flush`
    are judged as `prisma`, `rails` and `manage.py`.
    """
    words = ad_shell.strip_wrappers(argv)
    for _ in range(4):
        if not words:
            return "", []
        name = os.path.basename(words[0])
        rest = words[1:]
        if name in _PACKAGE_RUNNERS:
            while rest and rest[0].startswith("-"):
                rest = rest[1:]
            words = rest
        elif name in _PACKAGE_MANAGERS and rest and rest[0] in _PACKAGE_MANAGER_EXEC:
            words = rest[1:]
        elif name in _PACKAGE_MANAGERS and rest and rest[0] in _MIGRATION_RUNNERS:
            words = rest
        elif name in _ENVIRONMENT_RUNNERS and rest and rest[0] in ("exec", "run"):
            words = rest[1:]
        elif _PYTHON_RE.match(name) and rest[:1] == ["-m"] and len(rest) > 1:
            words = rest[1:]
        elif _PYTHON_RE.match(name) and rest and rest[0].endswith(".py"):
            words = rest
        else:
            break
    if not words:
        return "", []
    return os.path.basename(words[0]), words[1:]


def _classify_rm(args):
    """Recursive delete: `rm` with recursive and force flags, or recursive `rm` of a wide target."""
    short = _short_flags(args)
    long_names = _long_flags(args)
    recursive = bool(short & {"r", "R"}) or "--recursive" in long_names
    if not recursive:
        return []
    if "f" in short or "--force" in long_names:
        return [(LABEL_RECURSIVE_DELETE, "rm with recursive and force flags")]
    for operand in _operands(args):
        if _is_wide_target(operand):
            return [(LABEL_RECURSIVE_DELETE, "recursive rm of %s" % operand)]
    return []


def _classify_find(args):
    """Find delete: `find -delete`, or `find -exec` running a delete program."""
    if "-delete" in args:
        return [(LABEL_FIND_DELETE, "find with -delete")]
    for command in ad_shell.find_exec_commands(args):
        if ad_shell.program(command) in _DELETE_PROGRAMS:
            return [(LABEL_FIND_DELETE, "find runs %s on every match" % ad_shell.program(command))]
    return []


def _classify_xargs(args):
    """Find delete: `xargs` running a delete program on every input line."""
    name = ad_shell.program(ad_shell.xargs_command(args))
    if name in _DELETE_PROGRAMS:
        return [(LABEL_FIND_DELETE, "xargs runs %s on every input line" % name)]
    return []


def protected_branches():
    """Return the branch names that count as protected (`AD_PROTECTED_BRANCHES`, default main and master)."""
    raw = os.environ.get("AD_PROTECTED_BRANCHES") or PROTECTED_BRANCHES_DEFAULT
    return [name for name in re.split(r"[,\s]+", raw) if name]


def _classify_git_push(rest):
    """Force push and push to a protected branch."""
    options, operands = ad_shell.scan_options(rest, "o", ("--push-option", "--repo", "--receive-pack", "--exec"))
    names = [name for name, _ in options]
    if "--dry-run" in names or "-n" in names:
        return []
    refspecs = operands[1:]
    labels = []
    for flag in ("--force", "-f", "--mirror", "--delete", "-d", "--prune"):
        if flag in names:
            labels.append((LABEL_FORCE_PUSH, "git push with %s" % flag))
            break
    else:
        for refspec in refspecs:
            if refspec.startswith("+"):
                labels.append((LABEL_FORCE_PUSH, "refspec %s starts with +" % refspec))
                break
            if refspec.startswith(":"):
                labels.append((LABEL_FORCE_PUSH, "refspec %s deletes a remote ref" % refspec))
                break
    protected = protected_branches()
    for refspec in refspecs:
        destination = refspec.lstrip("+").split(":")[-1]
        if destination.startswith("refs/heads/"):
            destination = destination[len("refs/heads/"):]
        if destination in protected:
            labels.append((LABEL_PROTECTED_PUSH, "git push targets %s" % destination))
            break
    return labels


def _classify_git_discard(subcommand, rest):
    """Discards uncommitted work: reset --hard, clean -f, checkout/restore of paths, stash drop."""
    short = _short_flags(rest)
    long_names = _long_flags(rest)
    operands = _operands(rest)
    if subcommand == "reset" and "--hard" in long_names:
        return "git reset --hard"
    if subcommand == "clean":
        forced = "f" in short or "--force" in long_names
        dry_run = "n" in short or "--dry-run" in long_names
        if forced and not dry_run:
            return "git clean with force"
    if subcommand == "checkout":
        if "--" in rest and rest.index("--") < len(rest) - 1:
            return "git checkout -- <path>"
        if "." in operands:
            return "git checkout ."
        if "f" in short or "--force" in long_names:
            return "git checkout --force"
    if subcommand == "restore":
        staged_only = ("--staged" in long_names or "S" in short) and not ("--worktree" in long_names or "W" in short)
        if operands and not staged_only:
            return "git restore of the worktree"
    if subcommand == "switch":
        if "--discard-changes" in long_names or "f" in short or "--force" in long_names:
            return "git switch that discards changes"
    if subcommand == "stash" and rest[:1] in (["drop"], ["clear"]):
        return "git stash %s" % rest[0]
    if subcommand == "worktree" and rest[:1] == ["remove"] and ("f" in short or "--force" in long_names):
        return "git worktree remove --force"
    return ""


def _classify_git_history(subcommand, rest):
    """History rewrite: filter-branch, filter-repo, reflog expire, update-ref -d, branch -D."""
    short = _short_flags(rest)
    long_names = _long_flags(rest)
    if subcommand in ("filter-branch", "filter-repo"):
        return "git %s" % subcommand
    if subcommand == "reflog" and rest[:1] in (["expire"], ["delete"]):
        return "git reflog %s" % rest[0]
    if subcommand == "update-ref" and ("d" in short or "--delete" in long_names):
        return "git update-ref -d"
    if subcommand == "branch":
        forced_delete = "d" in short and ("f" in short or "--force" in long_names)
        if "D" in short or forced_delete or ("--delete" in long_names and "--force" in long_names):
            return "git branch -D"
    if subcommand == "gc" and any(name.startswith("--prune") for name in long_names):
        return "git gc --prune"
    return ""


def _classify_git(args):
    """All git rules; global options such as `-C dir` are skipped before the subcommand is read."""
    _, subcommand, rest = ad_shell.git_subcommand(args)
    if subcommand == "push":
        return _classify_git_push(rest)
    labels = []
    discard = _classify_git_discard(subcommand, rest)
    if discard:
        labels.append((LABEL_DISCARD, discard))
    history = _classify_git_history(subcommand, rest)
    if history:
        labels.append((LABEL_HISTORY, history))
    return labels


def _destructive_sql(text):
    """Return a short description of the first destructive SQL statement in `text`, or ""."""
    without_comments = _SQL_COMMENT_RE.sub(" ", text)
    for statement in without_comments.split(";"):
        statement = " ".join(statement.split())
        drop = _SQL_DROP_RE.search(statement)
        if drop:
            return "DROP %s" % drop.group(1).upper()
        if _SQL_TRUNCATE_RE.search(statement):
            return "TRUNCATE"
        for name, pattern in (("DELETE FROM", _SQL_DELETE_RE), ("UPDATE ... SET", _SQL_UPDATE_RE)):
            if not pattern.search(statement):
                continue
            if not _SQL_WHERE_RE.search(statement):
                return "%s with no WHERE" % name
            if _SQL_TAUTOLOGY_RE.search(statement.rstrip("'\" ")) or _SQL_TAUTOLOGY_RE.search(statement):
                return "%s with a WHERE that is always true" % name
    other = _SQL_OTHER_RE.search(without_comments)
    if other:
        return other.group(0)
    return ""


def _classify_database(name, args, segment):
    """Destructive SQL in the arguments or standard input of a database client or migration runner."""
    if name in _DB_DROP_PROGRAMS:
        return [(LABEL_SQL, name)]
    if name == "pg_restore" and ("c" in _short_flags(args) or "--clean" in _long_flags(args)):
        return [(LABEL_SQL, "pg_restore --clean drops objects before restoring")]
    if name == "bq" and "rm" in _operands(args)[:1]:
        return [(LABEL_SQL, "bq rm")]
    if name == "mysqladmin" and "drop" in _operands(args):
        return [(LABEL_SQL, "mysqladmin drop")]
    if name in _DB_CLIENTS:
        found = _destructive_sql(" ".join(args) + "\n" + segment.heredoc)
        if found:
            return [(LABEL_SQL, "%s: %s" % (name, found))]
        return []
    command_line = " ".join([name] + args)
    for pattern in _RUNNER_DESTRUCTIVE_RES:
        if pattern.search(command_line):
            return [(LABEL_SQL, "%s %s" % (name, " ".join(args[:3])))]
    return []


def _touches_database(name, args):
    """Return True for a database client or a migration runner (the commands the production rule covers)."""
    if name in _DB_CLIENTS or name in _DB_DROP_PROGRAMS or name in _MIGRATION_RUNNERS:
        return True
    if name in ("rails", "rake"):
        return any(word.startswith("db:") for word in args)
    if name in ("manage.py", "django-admin"):
        return any(word in ("migrate", "flush") for word in args)
    return False


def _production_marker(words):
    """Return the first word that names production (`prod`, `PROD_DB`, `--env live`), or ""."""
    for index, word in enumerate(words):
        if word in _LIVE_OPTIONS and words[index + 1:index + 2] == ["live"]:
            return "%s live" % word
        if word in ("--env=live", "--environment=live"):
            return word
        if " " in word or "\n" in word or word.lower().endswith(_PRODUCTION_IGNORED_SUFFIXES):
            continue
        if _PROD_WORD_RE.search(word):
            return word
    return ""


def _classify_production(name, args, segment, assignments):
    """Production data: a database command in a command that names a production target."""
    if not _touches_database(name, args):
        return []
    marker = _production_marker(list(segment.argv) + assignments)
    if marker:
        return [(LABEL_PRODUCTION, "%s with production marker %s" % (name, ad_core.clean(marker, 60)))]
    return []


def _classify_infrastructure(name, args):
    """Infrastructure delete: terraform destroy, kubectl delete, cloud CLI deletes, docker prune."""
    positionals = _operands(args)
    first = positionals[:1]
    first_two = positionals[:2]
    found = ""
    if name in ("terraform", "tofu", "terragrunt"):
        destroy_apply = first == ["apply"] and ("-destroy" in args or "--destroy" in args)
        if first == ["destroy"] or destroy_apply or first_two in (["state", "rm"], ["workspace", "delete"]):
            found = " ".join(first_two)
    elif name in ("kubectl", "oc"):
        _, kube_operands = ad_shell.scan_options(args, _KUBECTL_SHORT_VALUES, _KUBECTL_LONG_VALUES)
        if kube_operands[:1] in (["delete"], ["drain"]):
            found = kube_operands[0]
    elif name == "helm":
        _, helm_operands = ad_shell.scan_options(args, "n", _HELM_LONG_VALUES)
        if helm_operands[:1] in (["uninstall"], ["delete"], ["del"], ["un"]):
            found = helm_operands[0]
    elif name == "aws":
        _, aws_operands = ad_shell.scan_options(args, "", ("--profile", "--region", "--endpoint-url", "--output"))
        operation = aws_operands[1] if len(aws_operands) > 1 else ""
        if _AWS_DELETE_RE.match(operation) or (aws_operands[:1] == ["s3"] and operation in ("rm", "rb")):
            found = " ".join(aws_operands[:2])
    elif name == "gcloud":
        if "delete" in positionals or first_two == ["storage", "rm"]:
            found = "delete"
    elif name == "az":
        if any(word in ("delete", "delete-batch", "purge") for word in positionals):
            found = "delete"
    elif name == "gsutil":
        _, gsutil_operands = ad_shell.scan_options(args, "ohiuz")
        if gsutil_operands[:1] in (["rm"], ["rb"]):
            found = gsutil_operands[0]
    elif name in ("docker", "podman", "nerdctl"):
        removes_volumes = "v" in _short_flags(args) or "--volumes" in _long_flags(args)
        prunes_images = first_two == ["image", "prune"] and ("a" in _short_flags(args) or "--all" in _long_flags(args))
        if prunes_images or first_two in (["system", "prune"], ["volume", "rm"], ["volume", "prune"],
                                          ["volume", "remove"]):
            found = " ".join(first_two)
        elif first_two == ["compose", "down"] and removes_volumes:
            found = "compose down --volumes"
    elif name == "docker-compose":
        if first == ["down"] and ("v" in _short_flags(args) or "--volumes" in _long_flags(args)):
            found = "down --volumes"
    elif name == "gh":
        if first_two == ["repo", "delete"]:
            found = "repo delete"
    elif name == "pulumi":
        if first == ["destroy"] or first_two == ["stack", "rm"]:
            found = " ".join(first_two[:1] if first == ["destroy"] else first_two)
    elif name in ("fly", "flyctl"):
        if first == ["destroy"] or first_two == ["apps", "destroy"]:
            found = "destroy"
    elif name == "vercel":
        if first in (["remove"], ["rm"]):
            found = first[0]
    elif name == "heroku":
        if first in (["apps:destroy"], ["pg:reset"]):
            found = first[0]
    if found:
        return [(LABEL_INFRA, "%s %s" % (name, found))]
    return []


def _classify_publish(name, args):
    """Publish or deploy: package publishing, production deploys, merges and releases."""
    positionals = _operands(args)
    first = positionals[:1]
    first_two = positionals[:2]
    long_names = _long_flags(args)
    found = ""
    if name in _PACKAGE_MANAGERS:
        publishes = first == ["publish"] or first_two == ["npm", "publish"]
        if publishes and "--dry-run" not in long_names:
            found = "publish"
        elif name == "npm" and first == ["unpublish"]:
            found = "unpublish"
    elif name == "twine" and first == ["upload"]:
        found = "upload"
    elif name == "cargo" and first in (["publish"], ["yank"]) and "--dry-run" not in long_names:
        found = first[0]
    elif name == "gem" and first == ["push"]:
        found = "push"
    elif name in ("poetry", "flit", "uv", "hatch") and first == ["publish"] and "--dry-run" not in long_names:
        found = "publish"
    elif name == "vercel" and "--prod" in long_names:
        found = "--prod"
    elif name == "netlify" and first == ["deploy"] and "--prod" in long_names:
        found = "deploy --prod"
    elif name == "firebase" and first == ["deploy"]:
        found = "deploy"
    elif name == "gh":
        if first_two == ["pr", "merge"] or first_two in (["release", "create"], ["release", "delete"],
                                                         ["release", "delete-asset"]):
            found = " ".join(first_two)
    elif name in ("docker", "podman") and first == ["push"]:
        found = "push"
    if found:
        return [(LABEL_PUBLISH, "%s %s" % (name, found))]
    return []


def _classify_system(name, args, segment):
    """System destructive: mkfs, dd of=, shred, shutdown, kill -9 -1, recursive chmod of a wide target."""
    short = _short_flags(args)
    long_names = _long_flags(args)
    found = ""
    if name.startswith("mkfs") or name in ("shred", "shutdown", "reboot", "halt", "poweroff", "killall",
                                           "wipefs", "blkdiscard"):
        found = name
    elif name == "dd":
        outputs = [word[3:] for word in args if word.startswith("of=")]
        if any(output != "/dev/null" for output in outputs):
            found = "dd with of="
    elif name == "kill" and "-1" in args[1:]:
        found = "kill of every process (-1)"
    elif name == "crontab" and "r" in short:
        found = "crontab -r"
    elif name == "systemctl" and _operands(args)[:1] in (["poweroff"], ["reboot"], ["halt"]):
        found = "systemctl %s" % _operands(args)[0]
    elif name in ("chmod", "chown", "chgrp") and ("R" in short or "--recursive" in long_names):
        wide = [operand for operand in _operands(args)[1:] if _is_wide_target(operand) and operand not in (".", "*")]
        if wide:
            found = "recursive %s of %s" % (name, wide[0])
    labels = [(LABEL_SYSTEM, found)] if found else []
    for _, target in segment.redirects:
        if _BLOCK_DEVICE_RE.match(target):
            labels.append((LABEL_SYSTEM, "redirect onto the block device %s" % target))
    return labels


def _inline_code(name, args, segment):
    """Return the code an interpreter runs from `-c`/`-e` arguments or from standard input."""
    pieces = []
    for index, word in enumerate(args[:-1]):
        if _INLINE_CODE_OPTION_RE.match(word):
            pieces.append(args[index + 1])
    reads_stdin = not _operands(args) or args[:1] == ["-"]
    if reads_stdin and segment.heredoc:
        pieces.append(segment.heredoc)
    return "\n".join(pieces)


def _classify_inline(name, args, segment):
    """Inline delete code: an interpreter one-liner that deletes files or force-pushes."""
    if not _INTERPRETER_RE.match(name):
        return []
    match = _INLINE_DELETE_RE.search(_inline_code(name, args, segment))
    if match:
        return [(LABEL_INLINE, "%s code contains %s" % (name, ad_core.clean(match.group(0), 40)))]
    return []


def _classify_segment(segment, assignments):
    """Return the destructive labels of one segment."""
    stripped = ad_shell.strip_wrappers(segment.argv)
    if not stripped:
        return _classify_system("", [], segment)
    direct_name = os.path.basename(stripped[0])
    direct_args = stripped[1:]
    labels = []
    if direct_name == "rm":
        labels.extend(_classify_rm(direct_args))
    elif direct_name == "find":
        labels.extend(_classify_find(direct_args))
    elif direct_name == "xargs":
        labels.extend(_classify_xargs(direct_args))
    elif direct_name == "git":
        labels.extend(_classify_git(direct_args))
    labels.extend(_classify_system(direct_name, direct_args, segment))
    labels.extend(_classify_inline(direct_name, direct_args, segment))
    name, args = _effective_command(segment.argv)
    labels.extend(_classify_database(name, args, segment))
    labels.extend(_classify_production(name, args, segment, assignments))
    labels.extend(_classify_infrastructure(name, args))
    labels.extend(_classify_publish(name, args))
    return labels


def _raw_classify(raw):
    """Apply the conservative raw-text rules; used when a command cannot be parsed."""
    labels = []
    for label, pattern in _RAW_RULES:
        if pattern.search(raw) and label not in [found for found, _ in labels]:
            labels.append((label, UNPARSED_DETAIL))
    if _FORK_BOMB_RE.search(raw):
        labels.append((LABEL_SYSTEM, "fork bomb"))
    return labels


def looks_destructive(raw):
    """Return True when the raw command text matches the conservative destructive rules."""
    return bool(_raw_classify(_text(raw)))


def _exported_assignments(parsed):
    """Return the `NAME=value` words of assignment-only and `export` segments of a command."""
    found = []
    for segment in parsed.segments:
        words = segment.argv[1:] if segment.argv[:1] == ["export"] else segment.argv
        if words and all(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", word) for word in words):
            found.extend(words)
    return found


def classify(parsed, raw):
    """Return the destructive labels of a command as a list of (label, detail).

    Each segment is judged by the program it runs after wrapper stripping, so quoted text
    in the arguments of `echo`, `git commit -m`, `grep` and the like never triggers a
    label. When the command could not be parsed, conservative raw-text rules apply and
    the detail says so.
    """
    raw = _text(raw)
    if not parsed.ok:
        return _raw_classify(raw)
    assignments = _exported_assignments(parsed)
    labels = []
    for segment in parsed.segments:
        labels.extend(_classify_segment(segment, assignments))
    if _FORK_BOMB_RE.search(raw):
        labels.append((LABEL_SYSTEM, "fork bomb"))
    return _unique(labels)


# ---------------------------------------------------------------- write targets


def _all_operands(short_values="", long_values=()):
    """Build an extractor for programs whose every operand is written (rm, touch, mkdir, tee, mv)."""
    def extract(args):
        options, operands = ad_shell.scan_options(args, short_values, long_values)
        target_directory = ad_shell.option_value(options, "-t", "--target-directory")
        return operands + ([target_directory] if target_directory else [])
    return extract


def _last_operand(short_values="", long_values=(), remote_aware=False):
    """Build an extractor for copy-style programs: the last operand, or the `-t DIR` operand, is written."""
    def extract(args):
        options, operands = ad_shell.scan_options(args, short_values, long_values)
        target_directory = ad_shell.option_value(options, "-t", "--target-directory")
        if target_directory:
            return [target_directory]
        if len(operands) < 2:
            return []
        destination = operands[-1]
        if remote_aware and (ad_shell.is_remote_path(destination) or ad_shell.is_url(destination)):
            return []
        return [destination]
    return extract


def _install_targets(args):
    """`install -d DIR...` creates every operand; otherwise the last operand is written."""
    options, operands = ad_shell.scan_options(args, "mogtS", ("--mode", "--owner", "--group", "--suffix"))
    if ad_shell.has_option(options, "-d", "--directory"):
        return operands
    return _last_operand("mogtS", ("--mode", "--owner", "--group", "--suffix"))(args)


def _sed_targets(args):
    """`sed -i`: the file operands after the script are edited in place."""
    options, operands = ad_shell.scan_options(args, "efl", ("--expression", "--file", "--line-length"))
    if not ad_shell.has_option(options, "-i", "--in-place"):
        return []
    if ad_shell.has_option(options, "-e", "-f", "--expression", "--file"):
        return operands
    return operands[1:]


def _perl_targets(args):
    """`perl -i`: the file operands after the code are edited in place."""
    if not any(re.match(r"^-[a-zA-Z0-9]*i", word) for word in args):
        return []
    options, operands = ad_shell.scan_options(args, "eEIMmF")
    if ad_shell.has_option(options, "-e", "-E"):
        return operands
    return operands[1:]


def _awk_targets(args):
    """`awk -i inplace`: the file operands after the program are edited in place."""
    options, operands = ad_shell.scan_options(args, "fvFi", ("--include", "--file", "--assign"))
    if ad_shell.option_value(options, "-i", "--include") != "inplace":
        return []
    if ad_shell.has_option(options, "-f", "--file"):
        return operands
    return operands[1:]


def _mode_targets(args):
    """`chmod`, `chown`, `chgrp`: the operands after the mode or owner are changed."""
    options, operands = ad_shell.scan_options(args, "", ("--reference",))
    mode_is_option = any(_CHMOD_MODE_OPTION_RE.match(word) for word in args)
    if mode_is_option or ad_shell.option_value(options, "--reference"):
        return operands
    return operands[1:]


def _dd_targets(args):
    """`dd of=PATH` writes PATH."""
    return [word[3:] for word in args if word.startswith("of=") and len(word) > 3]


def _tar_targets(args):
    """`tar`: extraction writes into `-C DIR` (default: the working directory); creation writes the archive."""
    if not args:
        return []
    first = args[0]
    words = list(args)
    if not first.startswith("-"):
        words[0] = "-" + first
    options, _ = ad_shell.scan_options(words, "fCbTXIgHK", ("--file", "--directory", "--exclude", "--transform",
                                                               "--files-from", "--exclude-from", "--use-compress-program"))
    extracts = ad_shell.has_option(options, "-x", "--extract", "--get")
    creates = ad_shell.has_option(options, "-c", "-r", "-u", "--create", "--append", "--update")
    if extracts:
        return [ad_shell.option_value(options, "-C", "--directory") or "."]
    archive = ad_shell.option_value(options, "-f", "--file")
    if creates and archive and archive != "-":
        return [archive]
    return []


def _unzip_targets(args):
    """`unzip` writes into `-d DIR` (default: the working directory); `-l`, `-t`, `-p` and `-Z` only read."""
    options, _ = ad_shell.scan_options(args, "dPx")
    if ad_shell.has_option(options, "-l", "-t", "-p", "-Z", "-v", "-z"):
        return []
    return [ad_shell.option_value(options, "-d") or "."]


def _patch_targets(args):
    """`patch -d DIR` changes files in DIR; `-o FILE` writes FILE."""
    options, _ = ad_shell.scan_options(args, "dopiBDFgrVYz", ("--directory", "--output", "--input"))
    found = [ad_shell.option_value(options, "-d", "--directory"), ad_shell.option_value(options, "-o", "--output")]
    return [value for value in found if value]


def _curl_extra_targets(args):
    """`curl -D FILE` and `-c FILE` write files besides the download itself."""
    options, _ = ad_shell.scan_options(args, "odHXuAebcDFKmrTxyYzwCEQtP", ("--dump-header", "--cookie-jar", "--output"))
    found = [ad_shell.option_value(options, "-D", "--dump-header"), ad_shell.option_value(options, "-c", "--cookie-jar")]
    return [value for value in found if value and value != "-"]


_GIT_MUTATING_SUBCOMMANDS = ("checkout", "reset", "clean", "commit", "pull", "merge", "rebase", "apply", "stash",
                             "restore", "switch", "am", "cherry-pick", "revert", "rm", "mv", "add", "init")


def _git_targets(args):
    """`git -C DIR <mutating subcommand>` changes DIR; `git init DIR` creates DIR."""
    global_options, subcommand, rest = ad_shell.git_subcommand(args)
    found = []
    if subcommand in _GIT_MUTATING_SUBCOMMANDS:
        found.extend(value for name, value in global_options if name == "-C" and value)
    if subcommand == "init":
        found.extend(_operands(rest)[:1])
    return found


_WRITE_EXTRACTORS = {
    "rm": _all_operands(),
    "rmdir": _all_operands(),
    "unlink": _all_operands(),
    "shred": _all_operands("ns", ("--iterations", "--size", "--random-source")),
    "truncate": _all_operands("sr", ("--size", "--reference")),
    "touch": _all_operands("dtr", ("--date", "--reference", "--time")),
    "mkdir": _all_operands("mZ", ("--mode", "--context")),
    "tee": _all_operands(),
    "mv": _all_operands("tS", ("--target-directory", "--suffix")),
    "gzip": _all_operands("S", ("--suffix",)),
    "gunzip": _all_operands("S", ("--suffix",)),
    "bzip2": _all_operands(),
    "xz": _all_operands(),
    "cp": _last_operand("tS", ("--target-directory", "--suffix")),
    "ln": _last_operand("tS", ("--target-directory", "--suffix")),
    "rsync": _last_operand("efBMT", ("--rsh", "--exclude", "--include", "--filter", "--files-from",
                                     "--exclude-from", "--include-from", "--max-size", "--min-size",
                                     "--bwlimit", "--chmod", "--chown", "--backup-dir", "--link-dest",
                                     "--compare-dest", "--log-file", "--temp-dir", "--partial-dir"),
                           remote_aware=True),
    "scp": _last_operand("cFiJlPoSXD", (), remote_aware=True),
    "install": _install_targets,
    "sed": _sed_targets,
    "gsed": _sed_targets,
    "perl": _perl_targets,
    "awk": _awk_targets,
    "gawk": _awk_targets,
    "chmod": _mode_targets,
    "chown": _mode_targets,
    "chgrp": _mode_targets,
    "dd": _dd_targets,
    "tar": _tar_targets,
    "unzip": _unzip_targets,
    "patch": _patch_targets,
    "curl": _curl_extra_targets,
    "git": _git_targets,
}
_DOWNLOAD_PROGRAMS = ("curl", "wget", "aria2c", "gdown", "git")


def _segment_write_operands(segment):
    """Return the operands of one segment that name files or directories the command writes."""
    operands = [target for _, target in segment.redirects]
    stripped = ad_shell.strip_wrappers(segment.argv)
    if not stripped:
        return operands
    name = os.path.basename(stripped[0])
    extractor = _WRITE_EXTRACTORS.get(name)
    if extractor is not None:
        operands.extend(extractor(stripped[1:]))
    if name in _DOWNLOAD_PROGRAMS:
        single = ad_shell.Parsed(True, [ad_shell.Segment(stripped, [], segment.raw, segment.cwd_hint)])
        operands.extend(fetch["output"] for fetch in ad_shell.fetches(single) if fetch["output"])
    return [operand for operand in operands if operand and operand != "-"]


def _home():
    """Return the home directory used to expand `~` and `$HOME`."""
    return os.environ.get("HOME") or os.path.expanduser("~")


def _expand(text):
    """Expand `~`, `$HOME`, `$PWD`-free forms and `$TMPDIR`; other variables stay in place."""
    home = _home()
    if text == "~" or text.startswith("~/"):
        text = home + text[1:]
    elif text.startswith("~"):
        text = os.path.expanduser(text)
    text = re.sub(r"\$\{HOME\}|\$HOME(?![A-Za-z0-9_])", lambda _: home, text)
    temp = tempfile.gettempdir()
    text = re.sub(r"\$\{TMPDIR\}|\$TMPDIR(?![A-Za-z0-9_])", lambda _: temp, text)
    return text


def _is_device(path):
    """Return True for the device files that are always safe to write (`/dev/null`, `/dev/fd/N`, ...)."""
    return path in DEVICE_FILES or path.startswith(DEVICE_PREFIXES)


def resolve_target(raw, cwd_hint, cwd):
    """Resolve a write operand to an absolute real path; None when it cannot be known from the text.

    `~`, `$HOME`, `${HOME}`, `$PWD` and `$TMPDIR` are expanded. A relative path resolves
    against the directory set by earlier `cd` segments, else against `cwd`. For a glob the
    directory before the first glob character is checked. A target that still contains
    `$` or a backtick is unresolved.
    """
    text = _expand(raw)
    base = cwd
    if cwd_hint:
        base = resolve_target(cwd_hint, None, cwd)
    if base:
        text = re.sub(r"\$\{PWD\}|\$PWD(?![A-Za-z0-9_])", lambda _: base, text)
    for index, char in enumerate(text):
        if char in _GLOB_CHARS:
            text = os.path.dirname(text[:index] + "x")
            break
    if "$" in text or "`" in text:
        return None
    if not os.path.isabs(text):
        if not base:
            return None
        text = os.path.join(base, text)
    lexical = os.path.normpath(text)
    if _is_device(lexical):
        return lexical
    return os.path.realpath(lexical)


def _write_operands(parsed, cwd):
    """Return (raw operand, resolved path or None) for every write operand of a parsed command."""
    found = []
    for segment in parsed.segments:
        for operand in _segment_write_operands(segment):
            found.append((operand, resolve_target(operand, segment.cwd_hint, cwd)))
    return found


def write_targets(parsed, cwd):
    """Return the resolved paths a command writes: redirection targets and the write operands of known programs.

    Read operands, URLs and option values are never write targets. Operands that cannot be
    resolved from the text (they contain `$` or a backtick) are left out.
    """
    return _unique(resolved for _, resolved in _write_operands(parsed, cwd) if resolved)


# ---------------------------------------------------------------- declared roots and containment


def _inside(root, path):
    """Return True when `path` is `root` or lies under it (component-wise, so `/tmpfoo` is not in `/tmp`)."""
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:
        return False


def _temp_roots():
    """Return the real paths of the system temp directories, which are always allowed."""
    candidates = [tempfile.gettempdir()]
    candidates.extend(SYSTEM_TEMP_DIRS)
    if os.environ.get("TMPDIR"):
        candidates.append(os.environ["TMPDIR"])
    return _unique(os.path.realpath(candidate) for candidate in candidates)


def _git_root(start):
    """Return the nearest directory at or above `start` that contains `.git`, or None."""
    current = os.path.realpath(start)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _default_root(cwd):
    """Return the default declared root: the git root, else the project directory, else `cwd`."""
    git_root = _git_root(cwd)
    if git_root:
        return git_root
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    if project and _inside(os.path.realpath(project), os.path.realpath(cwd)):
        return os.path.realpath(project)
    return os.path.realpath(cwd)


def _load_scope():
    """Return the validated content of scope.json: string roots and string allow patterns only."""
    data = ad_core.load_json(SCOPE_FILE, {}) if ad_core.state_exists() else {}
    roots = data.get("roots")
    allow = data.get("allow")
    return {
        "roots": [item for item in roots if isinstance(item, str) and item] if isinstance(roots, list) else [],
        "allow": [item for item in allow if isinstance(item, str) and item] if isinstance(allow, list) else [],
    }


def declared_roots(cwd=None):
    """Return (roots, cfg): the real paths write operations may touch, and the scope configuration.

    With no scope.json (or one without usable roots) the single default root is the git
    root of `cwd`, else the project directory, else `cwd`. `cfg["default"]` says which case applies.
    """
    cfg = _load_scope()
    roots = _unique(os.path.realpath(root) for root in cfg["roots"])
    cfg["default"] = not roots
    if not roots:
        roots = [_default_root(cwd or ad_core.start_dir())]
    return roots, cfg


def _allowed_by_pattern(path, cfg):
    """Return True when a scope.json `allow` regex matches the path; invalid regexes are ignored with a warning."""
    for pattern in cfg.get("allow", []):
        try:
            if re.search(pattern, path):
                return True
        except re.error:
            sys.stderr.write("scope fence: ignoring invalid allow regex %r\n" % pattern)
    return False


def _is_contained(path, roots, cfg, scratchpad):
    """Return True when a resolved write target is inside a declared root or an always-allowed place."""
    if _is_device(path):
        return True
    allowed_roots = list(roots) + _temp_roots()
    if scratchpad:
        allowed_roots.append(os.path.realpath(scratchpad))
    if any(_inside(root, path) for root in allowed_roots):
        return True
    return _allowed_by_pattern(path, cfg)


def _is_protected_state_file(path):
    """Return True for approvals.json, scope.json, ledger.md in the state directory, and the directory itself."""
    state = os.path.realpath(ad_core.state_dir(create=False))
    if path == state:
        return True
    return os.path.dirname(path) == state and os.path.basename(path) in PROTECTED_STATE_FILES


def _protected_reason(path):
    """Denial text for a write to a protected state file."""
    return ("scope fence: blocked, %s is a protected state file. approvals.json, scope.json and ledger.md "
            "change only through the CLI. Next step: use `%s ledger add`, `%s scope add` or `%s approve`; "
            "the last two need the user's explicit yes first." % (path, _cli(), _cli(), _cli()))


def _outside_reason(raw, path, roots, command):
    """Denial text for a write target outside the declared roots."""
    directory = path if os.path.isdir(path) else os.path.dirname(path)
    shown = raw if raw == path else "%s (resolves to %s)" % (raw, path)
    text = ("scope fence: blocked, write target %s is outside the declared roots (%s). "
            "Next step: fix the path if it is a mistake. Otherwise ask the user; after an explicit yes, "
            "run `%s scope add %s`" % (shown, ", ".join(roots), _cli(), shlex.quote(directory)))
    if command:
        text += " (or, for this one command, `%s approve -- %s`)" % (_cli(), shlex.quote(command))
    return text + ", then retry the identical call."


def scope_set(roots, allow=None):
    """Replace the declared roots (and the optional allow regexes); return the new scope as text."""
    if not roots:
        raise ValueError("at least one root is required")
    resolved = []
    for root in roots:
        if not isinstance(root, str) or not root.strip():
            raise ValueError("empty root")
        resolved.append(os.path.realpath(os.path.join(ad_core.start_dir(), os.path.expanduser(root))))
    patterns = list(allow or [])
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError("invalid --allow regex %r: %s" % (pattern, error))
    ad_core.save_json(SCOPE_FILE, {"roots": _unique(resolved), "allow": patterns, "ts": ad_core.now()})
    return scope_show()


def scope_add(root):
    """Add one declared root, keeping the current roots and allow regexes; return the new scope as text."""
    current, cfg = declared_roots()
    return scope_set(current + [root], cfg.get("allow"))


def scope_show():
    """Return the declared roots, the allow regexes and the always-allowed places as text."""
    roots, cfg = declared_roots()
    source = "default: git root or working directory" if cfg["default"] else "scope.json"
    lines = ["declared roots (%s):" % source]
    lines.extend("- %s" % root for root in roots)
    if cfg["allow"]:
        lines.append("allow regexes:")
        lines.extend("- %s" % pattern for pattern in cfg["allow"])
    lines.append("always allowed: %s, the session scratchpad, /dev/null and the standard streams"
                 % ", ".join(_temp_roots()))
    return "\n".join(lines)


# ---------------------------------------------------------------- scope fence


def _label_reason(labels, command, unparsed):
    """Denial text for a destructive command."""
    described = "; ".join("%s (%s)" % (label, detail) for label, detail in labels)
    text = "scope fence: blocked, %s: `%s`. " % (described, _preview(command))
    if unparsed:
        text += "The command could not be parsed, so conservative text rules were applied. "
    return text + _approve_step(command)


def _fence_shell(command, tool, cwd, scratchpad):
    """Scope fence decision for a Bash or PowerShell command."""
    if not command.strip():
        return None
    parsed = ad_shell.parse(command)
    labels = classify(parsed, command)
    if tool == "PowerShell":
        labels = _unique(labels + _raw_classify(command))
    operands = [] if tool == "PowerShell" else _write_operands(parsed, cwd)
    for _, path in operands:
        if path and _is_protected_state_file(path):
            return _protected_reason(path)
    if is_approved(command):
        return None
    if labels:
        return _label_reason(labels, command, not parsed.ok)
    roots, cfg = declared_roots(cwd)
    for raw, path in operands:
        if path and not _is_contained(path, roots, cfg, scratchpad):
            return _outside_reason(raw, path, roots, command)
    return None


def _fence_file(path, cwd, scratchpad):
    """Scope fence decision for the one path a file tool writes."""
    if not path:
        return None
    resolved = resolve_target(path, None, cwd)
    if resolved is None:
        return None
    if _is_protected_state_file(resolved):
        return _protected_reason(resolved)
    roots, cfg = declared_roots(cwd)
    if _is_contained(resolved, roots, cfg, scratchpad):
        return None
    return _outside_reason(path, resolved, roots, "")


def scope_fence_decide(inp):
    """Return a denial reason for a tool call, or None to let it proceed.

    Bash and PowerShell: a destructive label denies unless the exact command is approved;
    then the first write target outside the declared roots denies. Write, Edit and
    NotebookEdit: only `file_path` / `notebook_path` is checked; content fields and the
    `description` field are never read.
    """
    if not isinstance(inp, dict):
        return None
    tool = _text(inp.get("tool_name")) or "Bash"
    tool_input = _tool_input(inp)
    cwd = _hook_cwd(inp)
    scratchpad = _text(inp.get("scratchpad_dir"))
    if tool in SHELL_TOOLS:
        return _fence_shell(_text(tool_input.get("command")), tool, cwd, scratchpad)
    if tool in FILE_TOOLS:
        path = _text(tool_input.get("file_path")) or _text(tool_input.get("notebook_path"))
        return _fence_file(path, cwd, scratchpad)
    return None


# ---------------------------------------------------------------- fetch guard


def _dup_bytes():
    """Return the size from which an existing copy blocks a duplicate fetch."""
    megabytes = ad_core.env_float("AD_FETCH_DUP_MB", FETCH_DUP_MB_DEFAULT, 0)
    return int(megabytes * BYTES_PER_MB)


def big_extensions():
    """Return the file extensions the large-type rule covers (`AD_BIG_EXT`, comma-separated)."""
    raw = os.environ.get("AD_BIG_EXT") or BIG_EXTENSIONS_DEFAULT
    return [item.strip().lstrip(".").lower() for item in raw.split(",") if item.strip().strip(".")]


def _existing_size(key):
    """Return the size of the recorded file when it still exists, else None."""
    try:
        if os.path.isfile(key):
            return os.path.getsize(key)
    except OSError:
        return None
    return None


def _strip_fragment(url):
    """Return a URL without its fragment."""
    return url.split("#", 1)[0]


def _lookup_url(url):
    """Return (key, entry) for a read-manifest entry recorded with this URL, else (None, None)."""
    for candidate in _unique([url, _strip_fragment(url)]):
        key, entry, how = ad_state.manifest_lookup(candidate)
        if entry is not None and how == "url":
            return key, entry
    return None, None


def _fetch_output_path(fetch, cwd):
    """Return the resolved file a fetch writes, or None when the command does not say."""
    output = fetch.get("output")
    if not output:
        return None
    resolved = resolve_target(output, fetch.get("cwd_hint"), cwd)
    if resolved is None:
        return None
    lands_in_directory = output.endswith("/") or os.path.isdir(resolved)
    if lands_in_directory and fetch.get("urls"):
        name = ad_shell.url_basename(fetch["urls"][0])
        if name:
            return os.path.join(resolved, name)
    return resolved


def _manifest_match(fetch, cwd):
    """Return (key, entry, how) for the read-manifest entry a fetch would duplicate, else None.

    Order: recorded URL; resolved output path; file name when exactly one entry has it.
    """
    for url in fetch.get("urls", []):
        key, entry = _lookup_url(url)
        if entry is not None:
            return key, entry, "the same URL"
    output_path = _fetch_output_path(fetch, cwd)
    if output_path:
        key, entry, how = ad_state.manifest_lookup(output_path)
        if entry is not None and how == "path":
            return key, entry, "the same output path"
    name = os.path.basename(output_path) if output_path else ""
    if not name and fetch.get("urls"):
        name = ad_shell.url_basename(fetch["urls"][0])
    if name:
        key, entry, how = ad_state.manifest_lookup(name)
        if entry is not None and how in ("basename", "path"):
            return key, entry, "the same file name"
    return None


def _describe_copy(key, entry, size):
    """Return a factual description of an existing copy."""
    return "%s (%s, recorded %s)" % (ad_core.clean(key, 300), ad_core.human_size(size), entry.get("ts") or "earlier")


def _big_extension(fetch):
    """Return the large-type extension of a fetch's URL path or output name, or ""."""
    names = [_strip_fragment(url).split("?", 1)[0].lower() for url in fetch.get("urls", [])]
    if fetch.get("output"):
        names.append(fetch["output"].lower())
    for name in names:
        for extension in big_extensions():
            if name.endswith("." + extension):
                return extension
    return ""


def _fetch_duplicate(target, match, command):
    """Return (deny reason, context note) for a fetch that matches a read-manifest entry."""
    key, entry, how = match
    size = _existing_size(key)
    if size is None:
        return None, None
    copy = _describe_copy(key, entry, size)
    if size >= _dup_bytes():
        reason = ("fetch guard: blocked, %s is already available as %s; matched by %s. Use the existing copy. "
                  "To fetch it again anyway: %s" % (ad_core.clean(target, 200), copy, how, _approve_step(command)))
        return reason, None
    return None, "A copy of %s already exists: %s; matched by %s." % (ad_core.clean(target, 200), copy, how)


def _fetch_guard_web(url):
    """Fetch guard for WebFetch: the duplicate rule by URL only."""
    if not url or is_approved(url):
        return None, None
    key, entry = _lookup_url(url)
    if entry is None:
        return None, None
    return _fetch_duplicate(url, (key, entry, "the same URL"), url)


def fetch_guard_decide(command, tool_name="Bash", tool_input=None, cwd=None):
    """Return (deny_reason, context) for a call that may download something.

    Duplicate rule: deny when the fetch matches a read-manifest entry whose file still
    exists and is at least `AD_FETCH_DUP_MB` (default 5 MB); for a smaller file allow and
    return a context note naming the existing copy. Large-type rule: deny an unapproved
    fetch whose URL path or output name ends with an extension in `AD_BIG_EXT`.
    WebFetch gets the duplicate rule by URL only. An approved command passes both rules.
    """
    if tool_name == "WebFetch":
        url = _text((tool_input or {}).get("url")) if isinstance(tool_input, dict) else ""
        return _fetch_guard_web(url or _text(command))
    command = _text(command)
    if tool_name not in SHELL_TOOLS or not command.strip():
        return None, None
    parsed = ad_shell.parse(command)
    found = ad_shell.fetches(parsed) if parsed.ok else []
    if not found or is_approved(command):
        return None, None
    cwd = cwd or ad_core.start_dir()
    notes = []
    for fetch in found:
        match = _manifest_match(fetch, cwd) if ad_core.state_exists() else None
        if match is None:
            continue
        target = (fetch.get("urls") or [fetch.get("output") or fetch["program"]])[0]
        reason, note = _fetch_duplicate(target, match, command)
        if reason:
            return reason, None
        if note:
            notes.append(note)
    for fetch in found:
        extension = _big_extension(fetch)
        if extension:
            target = (fetch.get("urls") or [fetch.get("output")])[0]
            reason = ("fetch guard: blocked, %s has the large-file type .%s. Produce the inventory line first: "
                      "what was searched and what was found. %s"
                      % (ad_core.clean(target, 200), extension, _approve_step(command)))
            return reason, None
    return None, (" ".join(notes) or None)


# ---------------------------------------------------------------- retry rule


def _logged_form(command):
    """Return a command in the form the tool log stores it (normalized, redacted, truncated)."""
    return ad_core.redact(normalize_command(command))[:ad_gates.LOGGED_COMMAND_CHARS]


def _retry_denial(inp, command):
    """Return a denial when the last N mutating calls of this session are failures of this exact command."""
    limit = ad_core.env_int("AD_RETRY_LIMIT", RETRY_LIMIT_DEFAULT, 0)
    session = _text(inp.get("session_id"))
    if limit <= 0 or not session or not ad_core.state_exists():
        return None
    records = [record for record in ad_gates.tool_log(session) if record.get("tool") in MUTATING_TOOLS]
    recent = records[-limit:]
    if len(recent) < limit:
        return None
    logged = _logged_form(command)
    for record in recent:
        same_call = record.get("tool") in SHELL_TOOLS and record.get("cmd") == logged
        if record.get("ok") is not False or not same_call:
            return None
    if is_approved(command):
        return None
    return ("retry rule: blocked, the same call failed %d times in a row with nothing changed in between: `%s`. "
            "Read the error output and change the command or its inputs before running it again. "
            "To run it unchanged anyway: %s" % (limit, _preview(command), _approve_step(command)))


def validate_call_decide(inp):
    """Return (deny_reason, context) for a shell call: the retry rule, plus factual context notes.

    The retry rule reads the tool log of the current session. Context notes never deny:
    an empty command, and a working directory outside every declared root.
    """
    if not isinstance(inp, dict):
        return None, None
    tool = _text(inp.get("tool_name")) or "Bash"
    if tool not in SHELL_TOOLS:
        return None, None
    command = _text(_tool_input(inp).get("command"))
    if not command.strip():
        return None, "The command is empty."
    reason = _retry_denial(inp, command)
    if reason:
        return reason, None
    cwd = _text(inp.get("cwd"))
    if cwd:
        roots, _ = declared_roots(cwd)
        resolved = os.path.realpath(cwd)
        if not any(_inside(root, resolved) for root in roots):
            return None, "The working directory %s is outside the declared roots (%s)." % (resolved, ", ".join(roots))
    return None, None


# ---------------------------------------------------------------- hook entrypoints


def _guard_note(name, error):
    """Report a guard that failed open."""
    sys.stderr.write("agent-discipline: %s skipped after an internal error (%s)\n" % (name, error))


def _fence_or_fail_closed(inp, command):
    """Run the scope fence; after an internal error deny only when the command looks destructive."""
    try:
        return scope_fence_decide(inp)
    except Exception as error:  # fail closed only for destructive-looking commands
        if looks_destructive(command):
            return "scope fence: internal error; blocking because the command looks destructive. " + _approve_step(command)
        _guard_note("scope fence", error)
        return None


def hook_pre_bash():
    """PreToolUse hook for Bash and PowerShell: fetch guard, scope fence, retry rule; the first denial wins."""
    inp = ad_core.read_hook_input()
    tool = _text(inp.get("tool_name")) or "Bash"
    command = _text(_tool_input(inp).get("command"))
    notes = []
    try:
        reason, note = fetch_guard_decide(command, tool, _tool_input(inp), _hook_cwd(inp))
    except Exception as error:  # the fetch guard fails open
        _guard_note("fetch guard", error)
        reason, note = None, None
    if reason:
        ad_core.deny(reason)
    if note:
        notes.append(note)
    reason = _fence_or_fail_closed(inp, command)
    if reason:
        ad_core.deny(reason)
    try:
        reason, note = validate_call_decide(inp)
    except Exception as error:  # the retry rule fails open
        _guard_note("retry rule", error)
        reason, note = None, None
    if reason:
        ad_core.deny(reason)
    if note:
        notes.append(note)
    ad_core.allow(" ".join(notes) or None)


def hook_pre_write():
    """PreToolUse hook for Write, Edit and NotebookEdit: the scope fence on the file path only."""
    inp = ad_core.read_hook_input()
    reason = scope_fence_decide(inp)
    if reason:
        ad_core.deny(reason)
    ad_core.allow()


def hook_pre_fetch():
    """PreToolUse hook for WebFetch: the fetch guard by URL."""
    inp = ad_core.read_hook_input()
    reason, note = fetch_guard_decide("", "WebFetch", _tool_input(inp), _hook_cwd(inp))
    if reason:
        ad_core.deny(reason)
    ad_core.allow(note)


def _record_fetched_files(inp):
    """Record in the read manifest every file a finished Bash fetch left on disk."""
    command = _text(_tool_input(inp).get("command"))
    parsed = ad_shell.parse(command)
    if not parsed.ok:
        return
    cwd = _hook_cwd(inp)
    for fetch in ad_shell.fetches(parsed):
        path = _fetch_output_path(fetch, cwd)
        if not path or not os.path.isfile(path):
            continue
        url = fetch["urls"][0] if fetch.get("urls") else None
        try:
            ad_state.manifest_record(path, source="fetch", url=url, session=_text(inp.get("session_id")),
                                     agent=_text(inp.get("agent_id")))
        except (OSError, ValueError) as error:
            _guard_note("fetch record", error)


def hook_post_tool():
    """PostToolUse hook (name `log`): log the call, record fetched files, optionally trim long output."""
    inp = ad_core.read_hook_input()
    ad_gates.log_tool(inp)
    if _text(inp.get("tool_name")) in SHELL_TOOLS:
        _record_fetched_files(inp)
    replacement = ad_gates.trimmed_tool_output(inp)
    if replacement is not None:
        payload = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": replacement}}
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()
