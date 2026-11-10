"""Shell command analysis: turn a Bash command string into analyzable segments.

The guards must inspect commands, not prose. This module tokenizes a command
line the way a POSIX shell would (quotes, escapes, operators, redirections,
here-documents), splits it into simple commands ("segments") and recurses into
text that the shell would run as a command (`$( )`, backticks, `sh -c`, `eval`,
`xargs`, `find -exec`). It never runs anything and never touches the file
system. It imports nothing from the other agent-discipline modules.
"""

import os
import re

MAX_NESTING_DEPTH = 6

_PIPE_OPERATORS = ("|", "|&")
_CONTROL_OPERATORS = ("&&", "||", ";;", "|&", ";", "|", "&", "(", ")")
_WORD_BREAK_CHARS = " \t\r\n;|&()<>"
_REDIRECT_RE = re.compile(r"(\d*)(&>>|&>|>>|>\||>&|<<<|<<-|<<|<&|<>|>|<)")
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
_VARIABLE_RE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
_WHOLE_VARIABLE_RE = re.compile(r"^\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))$")
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")
_REMOTE_PATH_RE = re.compile(r"^(?:[^/\s:@]+@)?[^/\s:@]+:(?!//)\S*$")
_ANSI_C_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"', "0": "\0"}

# Variables the guards resolve themselves; a literal assignment never overrides them here.
_RESERVED_VARIABLES = ("HOME", "PWD", "OLDPWD", "TMPDIR", "PATH", "IFS")

_SHELL_KEYWORDS = ("if", "then", "elif", "else", "do", "while", "until", "!")
_SHELL_PROGRAMS = ("sh", "bash", "zsh", "dash", "ksh", "ash", "su")
_SHELL_VALUE_OPTIONS = ("-o", "-O", "--rcfile", "--init-file")
_ECHO_PROGRAMS = ("echo", "printf")
_FIND_EXEC_OPTIONS = ("-exec", "-execdir", "-ok", "-okdir")
_XARGS_VALUE_OPTIONS = ("-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a", "--max-args", "--max-procs",
                        "--max-lines", "--max-chars", "--delimiter", "--arg-file", "--replace", "--eof")

# Wrappers: programs that run another program given as their remaining arguments.
_WRAPPER_VALUE_OPTIONS = {
    "sudo": ("-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U", "-r", "-t",
             "--user", "--group", "--host", "--prompt", "--chdir", "--role", "--type", "--other-user",
             "--close-from"),
    "doas": ("-u", "-C"),
    "env": ("-u", "--unset", "-C", "--chdir"),
    "nohup": (),
    "time": ("-f", "--format", "-o", "--output"),
    "nice": ("-n", "--adjustment"),
    "ionice": ("-c", "-n", "-p", "--class", "--classdata"),
    "timeout": ("-s", "--signal", "-k", "--kill-after"),
    "stdbuf": ("-i", "-o", "-e", "--input", "--output", "--error"),
    "command": (),
    "builtin": (),
    "exec": ("-a",),
    "setsid": (),
    "watch": ("-n", "--interval"),
}
_WRAPPERS_WITH_ASSIGNMENTS = ("sudo", "env")
_WRAPPERS_WITH_ONE_POSITIONAL = ("timeout",)
_COMMAND_LOOKUP_OPTIONS = ("-v", "-V")

# Option tables for the fetch programs: short letters and long names that take a value.
_CURL_SHORT_VALUES = "odHXuAebcDFKmrTxyYzwCEQtP"
_CURL_LONG_VALUES = (
    "--output", "--url", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii",
    "--header", "--request", "--user", "--user-agent", "--referer", "--cookie", "--cookie-jar",
    "--dump-header", "--form", "--form-string", "--config", "--max-time", "--connect-timeout",
    "--retry", "--retry-delay", "--retry-max-time", "--range", "--upload-file", "--proxy",
    "--write-out", "--output-dir", "--cacert", "--capath", "--cert", "--key", "--limit-rate",
    "--resolve", "--max-redirs", "--continue-at", "--oauth2-bearer", "--interface", "--max-filesize",
    "--speed-limit", "--speed-time", "--time-cond", "--etag-save", "--etag-compare", "--trace",
    "--trace-ascii", "--stderr", "--netrc-file", "--proto", "--json", "--proxy-user", "--noproxy",
    "--unix-socket", "--connect-to", "--ciphers", "--pubkey", "--pass", "--cert-type", "--key-type",
)
_WGET_SHORT_VALUES = "OPoatTwQUeiBADRIlX"
_WGET_LONG_VALUES = (
    "--output-document", "--directory-prefix", "--output-file", "--append-output", "--tries",
    "--timeout", "--wait", "--quota", "--user-agent", "--execute", "--input-file", "--base",
    "--accept", "--reject", "--domains", "--exclude-domains", "--header", "--user", "--password",
    "--post-data", "--post-file", "--limit-rate", "--level", "--cut-dirs", "--referer",
    "--load-cookies", "--save-cookies", "--ca-certificate", "--certificate", "--private-key",
    "--method", "--body-data", "--body-file", "--waitretry", "--dns-timeout", "--connect-timeout",
    "--read-timeout", "--bind-address", "--include-directories", "--exclude-directories",
)
_ARIA2_SHORT_VALUES = "odxsjkilT"
_ARIA2_LONG_VALUES = ("--out", "--dir", "--max-connection-per-server", "--split", "--input-file",
                      "--max-concurrent-downloads", "--min-split-size", "--log", "--header",
                      "--user-agent", "--referer", "--checksum", "--all-proxy")
_SCP_SHORT_VALUES = "cFiJlPoSXD"
_RSYNC_SHORT_VALUES = "efBMT"
_RSYNC_LONG_VALUES = (
    "--rsh", "--exclude", "--include", "--filter", "--files-from", "--exclude-from", "--include-from",
    "--max-size", "--min-size", "--bwlimit", "--chmod", "--chown", "--backup-dir", "--link-dest",
    "--compare-dest", "--copy-dest", "--log-file", "--temp-dir", "--partial-dir", "--password-file",
    "--port", "--timeout", "--contimeout", "--suffix", "--block-size", "--rsync-path", "--out-format",
    "--info", "--debug", "--usermap", "--groupmap", "--iconv", "--max-delete", "--modify-window",
)
_GIT_GLOBAL_VALUE_OPTIONS = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
                             "--super-prefix", "--config-env")
_GIT_CLONE_SHORT_VALUES = "bocjuL"
_GIT_CLONE_LONG_VALUES = ("--branch", "--depth", "--origin", "--config", "--reference",
                          "--reference-if-able", "--separate-git-dir", "--jobs", "--filter",
                          "--shallow-since", "--shallow-exclude", "--template", "--upload-pack",
                          "--server-option", "--bundle-uri")
_AWS_LONG_VALUES = ("--profile", "--region", "--endpoint-url", "--output", "--exclude", "--include",
                    "--acl", "--storage-class", "--sse", "--cache-control", "--content-type",
                    "--metadata", "--expected-size", "--page-size", "--request-payer", "--color",
                    "--cli-read-timeout", "--cli-connect-timeout", "--ca-bundle", "--query")
_GSUTIL_SHORT_VALUES = "ohiuz"
_GDOWN_SHORT_VALUES = "O"
_GDOWN_LONG_VALUES = ("--output", "--id", "--proxy", "--speed", "--format", "--user-agent")
_PIP_SHORT_VALUES = "dricefi"
_PIP_LONG_VALUES = ("--dest", "--requirement", "--constraint", "--index-url", "--extra-index-url",
                    "--find-links", "--platform", "--python-version", "--implementation", "--abi",
                    "--only-binary", "--no-binary", "--cache-dir", "--src", "--proxy", "--cert")
_HF_LONG_VALUES = ("--local-dir", "--repo-type", "--revision", "--cache-dir", "--token", "--include",
                   "--exclude", "--max-workers")
_STORAGE_SCHEMES = ("gs://", "s3://")
_PYTHON_PROGRAM_RE = re.compile(r"^python(\d+(\.\d+)?)?$")


class ShellSyntaxError(ValueError):
    """Raised by the scanner when the command cannot be tokenized (for example an unbalanced quote)."""


class Segment(object):
    """One simple command.

    argv: the words of the command, quotes removed, wrappers not yet stripped.
    redirects: (operator, target) pairs for redirections that write a file.
    raw: the source text of the segment.
    cwd_hint: the directory set by earlier `cd` segments, or None when no `cd` came before.
    heredoc: here-document body, here-string, or text echoed into this segment through a pipe.
    nested: True when the segment was found inside another one (substitution, `sh -c`, `xargs`, ...).
    """

    def __init__(self, argv, redirects=None, raw="", cwd_hint=None, heredoc="", nested=False):
        self.argv = list(argv)
        self.redirects = list(redirects or [])
        self.raw = raw
        self.cwd_hint = cwd_hint
        self.heredoc = heredoc
        self.nested = nested

    def __repr__(self):
        return "Segment(argv=%r, redirects=%r, cwd_hint=%r)" % (self.argv, self.redirects, self.cwd_hint)


class Parsed(object):
    """Result of `parse`: `ok` says whether tokenization succeeded; `segments` is empty when it did not."""

    def __init__(self, ok, segments, error=""):
        self.ok = ok
        self.segments = segments
        self.error = error


class _Token(object):
    """A lexical token: a word, a control operator, a redirection, or a here-string."""

    def __init__(self, kind, text, start, end):
        self.kind = kind
        self.text = text
        self.start = start
        self.end = end
        self.operator = ""
        self.nested = []
        self.quoted = False
        self.body = ""


# ---------------------------------------------------------------- scanner


def _skip_single_quote(text, index):
    """Return the index of the quote that closes the single quote opened at `index`."""
    close = text.find("'", index + 1)
    if close < 0:
        raise ShellSyntaxError("unbalanced single quote")
    return close


def _skip_double_quote(text, index):
    """Return the index of the quote that closes the double quote opened at `index`."""
    position = index + 1
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 2
            continue
        if char == '"':
            return position
        position += 1
    raise ShellSyntaxError("unbalanced double quote")


def _match_paren(text, index):
    """Return the index of the `)` that closes the `(` at `index`, skipping quoted text."""
    depth = 0
    position = index
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 2
            continue
        if char == "'":
            position = _skip_single_quote(text, position) + 1
            continue
        if char == '"':
            position = _skip_double_quote(text, position) + 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return position
        position += 1
    raise ShellSyntaxError("unbalanced parenthesis")


def _match_brace(text, index):
    """Return the index of the `}` that closes the `${` whose `{` is at `index`."""
    depth = 0
    position = index
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return position
        position += 1
    raise ShellSyntaxError("unbalanced brace")


def _match_backtick(text, index):
    """Return the index of the backtick that closes the one at `index`."""
    position = index + 1
    while position < len(text):
        char = text[position]
        if char == "\\":
            position += 2
            continue
        if char == "`":
            return position
        position += 1
    raise ShellSyntaxError("unbalanced backtick")


def _read_substitution(text, index, token, pieces):
    """Consume `$(...)`, `${...}` or a backtick span at `index`; return the next index, or -1 if none starts here.

    The literal text stays in the word (so callers can see the value is computed at run
    time) and the inner command text is remembered in `token.nested`.
    """
    char = text[index]
    following = text[index + 1:index + 2]
    if char == "$" and following == "(":
        close = _match_paren(text, index + 1)
        token.nested.append(text[index + 2:close])
        pieces.append(text[index:close + 1])
        return close + 1
    if char == "$" and following == "{":
        close = _match_brace(text, index + 1)
        pieces.append(text[index:close + 1])
        return close + 1
    if char == "`":
        close = _match_backtick(text, index)
        token.nested.append(text[index + 1:close].replace("\\`", "`"))
        pieces.append(text[index:close + 1])
        return close + 1
    return -1


def _read_double_quoted(text, index, token, pieces):
    """Consume a double-quoted span that opens at `index`; return the index after the closing quote."""
    position = index + 1
    while position < len(text):
        char = text[position]
        if char == '"':
            return position + 1
        if char == "\\":
            following = text[position + 1:position + 2]
            if following == "\n":
                position += 2
                continue
            if following in ('"', "\\", "$", "`"):
                pieces.append(following)
                position += 2
                continue
            pieces.append(char)
            position += 1
            continue
        after = _read_substitution(text, position, token, pieces)
        if after >= 0:
            position = after
            continue
        pieces.append(char)
        position += 1
    raise ShellSyntaxError("unbalanced double quote")


def _read_ansi_c_quoted(text, index, pieces):
    """Consume a `$'...'` span whose `$` is at `index`; return the index after the closing quote."""
    position = index + 2
    while position < len(text):
        char = text[position]
        if char == "'":
            return position + 1
        if char == "\\" and position + 1 < len(text):
            following = text[position + 1]
            pieces.append(_ANSI_C_ESCAPES.get(following, following))
            position += 2
            continue
        pieces.append(char)
        position += 1
    raise ShellSyntaxError("unbalanced $' quote")


def _read_word(text, index):
    """Read one shell word that starts at `index`; return a word token with quotes removed."""
    token = _Token("word", "", index, index)
    pieces = []
    position = index
    length = len(text)
    while position < length:
        char = text[position]
        following = text[position + 1:position + 2]
        if char in "<>" and following == "(":
            close = _match_paren(text, position + 1)
            token.nested.append(text[position + 2:close])
            pieces.append(text[position:close + 1])
            position = close + 1
            continue
        if char in _WORD_BREAK_CHARS:
            break
        if char == "\\":
            token.quoted = True
            if following != "\n":
                pieces.append(following)
            position += 2
            continue
        if char == "'":
            close = _skip_single_quote(text, position)
            pieces.append(text[position + 1:close])
            token.quoted = True
            position = close + 1
            continue
        if char == '"':
            token.quoted = True
            position = _read_double_quoted(text, position, token, pieces)
            continue
        if char == "$" and following == "'":
            token.quoted = True
            position = _read_ansi_c_quoted(text, position, pieces)
            continue
        after = _read_substitution(text, position, token, pieces)
        if after >= 0:
            position = after
            continue
        pieces.append(char)
        position += 1
    token.text = "".join(pieces)
    token.end = position
    return token


def _skip_blanks(text, index):
    """Return the index of the first character at or after `index` that is not a space or tab."""
    while index < len(text) and text[index] in " \t":
        index += 1
    return index


def _read_heredoc_bodies(text, index, pending):
    """Read the here-document bodies that start at `index` (the start of a line); return the index after them."""
    for token, delimiter, strip_tabs in pending:
        lines = []
        while index < len(text):
            line_end = text.find("\n", index)
            if line_end < 0:
                line_end = len(text)
            line = text[index:line_end]
            index = min(line_end + 1, len(text))
            candidate = line.lstrip("\t") if strip_tabs else line
            if candidate == delimiter:
                break
            lines.append(line)
        token.body = "\n".join(lines)
    del pending[:]
    return index


def _read_redirect(text, index, match, tokens, pending):
    """Consume the redirection matched at `index` together with its target word; return the next index."""
    operator = match.group(2)
    target_start = _skip_blanks(text, match.end())
    target = _read_word(text, target_start)
    if target.end == target_start:
        raise ShellSyntaxError("redirection without a target")
    token = _Token("redirect", target.text, index, target.end)
    token.operator = match.group(1) + operator
    token.nested = target.nested
    if operator in ("<<", "<<-"):
        token.kind = "heredoc"
        pending.append((token, target.text, operator == "<<-"))
    elif operator == "<<<":
        token.kind = "heredoc"
        token.body = target.text
    elif operator in (">&", "<&") and re.match(r"^(\d+|-)$", target.text):
        token.kind = "fd-duplicate"
    elif operator in ("<", "<&", "<>"):
        token.kind = "input"
    tokens.append(token)
    return target.end


def _match_operator(text, index):
    """Return the control operator that starts at `index`, or an empty string."""
    for operator in _CONTROL_OPERATORS:
        if text.startswith(operator, index):
            return operator
    return ""


def _lex(text):
    """Split a command string into word, operator and redirection tokens."""
    tokens = []
    pending = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\" and text[index + 1:index + 2] == "\n":
            index += 2
            continue
        if char in " \t\r":
            index += 1
            continue
        if char == "\n":
            tokens.append(_Token("operator", "\n", index, index + 1))
            index += 1
            if pending:
                index = _read_heredoc_bodies(text, index, pending)
            continue
        if char == "#":
            line_end = text.find("\n", index)
            index = length if line_end < 0 else line_end
            continue
        is_process_substitution = char in "<>" and text[index + 1:index + 2] == "("
        redirect = None if is_process_substitution else _REDIRECT_RE.match(text, index)
        if redirect:
            index = _read_redirect(text, index, redirect, tokens, pending)
            continue
        operator = _match_operator(text, index)
        if operator:
            tokens.append(_Token("operator", operator, index, index + len(operator)))
            index += len(operator)
            continue
        word = _read_word(text, index)
        if word.end == index:
            raise ShellSyntaxError("unexpected character %r" % char)
        if word.text in ("{", "}") and not word.quoted:
            word.kind = "operator"
        tokens.append(word)
        index = word.end
    return tokens


# ---------------------------------------------------------------- wrappers and options


def _strip_one_wrapper(name, rest):
    """Drop the options of wrapper `name` from `rest`; return the wrapped command."""
    value_options = _WRAPPER_VALUE_OPTIONS[name]
    if name == "command" and rest and rest[0] in _COMMAND_LOOKUP_OPTIONS:
        return []
    index = 0
    while index < len(rest):
        word = rest[index]
        if word == "--":
            index += 1
            break
        if not word.startswith("-"):
            break
        if word in value_options:
            index += 2
            continue
        index += 1
    if name in _WRAPPERS_WITH_ASSIGNMENTS:
        while index < len(rest) and _ASSIGNMENT_RE.match(rest[index]):
            index += 1
    if name in _WRAPPERS_WITH_ONE_POSITIONAL and index < len(rest):
        index += 1
    return rest[index:]


def strip_wrappers(argv):
    """Return `argv` without leading `VAR=value` assignments, shell keywords and wrapper programs.

    `sudo -u root env X=1 nice -n 5 /bin/rm -rf x` becomes `/bin/rm -rf x`, so guards judge
    the program that actually runs. `command -v NAME` is a lookup and yields an empty list.
    """
    words = list(argv)
    changed = True
    while words and changed:
        changed = False
        while words and _ASSIGNMENT_RE.match(words[0]):
            words = words[1:]
            changed = True
        if not words:
            break
        head = os.path.basename(words[0])
        if head in _SHELL_KEYWORDS:
            words = words[1:]
            changed = True
        elif head in _WRAPPER_VALUE_OPTIONS:
            words = _strip_one_wrapper(head, words[1:])
            changed = True
    return words


def program(argv):
    """Return the base name of the program a segment runs (`/bin/rm` gives `rm`), or "" if there is none."""
    words = strip_wrappers(argv)
    if not words:
        return ""
    return os.path.basename(words[0])


def scan_options(args, short_values="", long_values=()):
    """Split `args` into options and operands.

    Returns `(options, operands)`; `options` is a list of `(name, value)` with `value` None
    for flags. `short_values` lists the short option letters that take a value (`-o FILE`,
    `-oFILE`, and the last letter of a cluster such as `-sSLo FILE`); `long_values` lists the
    long options that take a value (`--output FILE` or `--output=FILE`). Everything after
    `--` is an operand. A lone `-` is an operand.
    """
    options = []
    operands = []
    index = 0
    while index < len(args):
        word = args[index]
        index += 1
        if word == "--":
            operands.extend(args[index:])
            break
        if word.startswith("--"):
            name, equals, value = word.partition("=")
            if equals:
                options.append((name, value))
            elif name in long_values and index < len(args):
                options.append((name, args[index]))
                index += 1
            else:
                options.append((name, None))
            continue
        if word.startswith("-") and len(word) > 1:
            position = 1
            while position < len(word):
                letter = word[position]
                position += 1
                if letter not in short_values:
                    options.append(("-" + letter, None))
                    continue
                attached = word[position:]
                if attached:
                    options.append(("-" + letter, attached))
                elif index < len(args):
                    options.append(("-" + letter, args[index]))
                    index += 1
                else:
                    options.append(("-" + letter, None))
                break
            continue
        operands.append(word)
    return options, operands


def option_value(options, *names):
    """Return the value of the last option in `options` whose name is in `names`, or None."""
    found = None
    for name, value in options:
        if name in names and value is not None:
            found = value
    return found


def has_option(options, *names):
    """Return True when `options` contains an option named in `names`."""
    return any(name in names for name, _ in options)


def git_subcommand(args):
    """Split git arguments into (global options, subcommand, rest); the subcommand is "" when absent."""
    index = 0
    global_options = []
    while index < len(args):
        word = args[index]
        if not word.startswith("-"):
            break
        if word in _GIT_GLOBAL_VALUE_OPTIONS and index + 1 < len(args):
            global_options.append((word, args[index + 1]))
            index += 2
            continue
        name, equals, value = word.partition("=")
        global_options.append((name, value if equals else None))
        index += 1
    if index >= len(args):
        return global_options, "", []
    return global_options, args[index], args[index + 1:]


# ---------------------------------------------------------------- segments


def _join_cwd(current, target):
    """Combine the tracked directory with a new `cd` target."""
    if not current:
        return target
    if target.startswith(("/", "~", "$")):
        return target
    return os.path.join(current, target)


def _cd_target(stripped):
    """Return the directory a `cd`/`pushd`/`popd` segment moves to, or None for other commands.

    A target that cannot be known from the text is returned as `$OLDPWD`, which later
    resolution treats as an unresolved path.
    """
    name = stripped[0]
    if name == "popd":
        return "$OLDPWD"
    if name not in ("cd", "pushd"):
        return None
    operands = [word for word in stripped[1:] if word == "-" or not word.startswith("-")]
    if not operands:
        return "~"
    if operands[0] == "-":
        return "$OLDPWD"
    return operands[0]


def _substitute_variables(token, variables):
    """Return the words a token expands to, using literal assignments seen earlier in the command."""
    text = token.text
    if not variables or "$" not in text:
        return [text]
    whole = _WHOLE_VARIABLE_RE.match(text)
    if whole and not token.quoted:
        name = whole.group(1) or whole.group(2)
        if name in variables:
            return variables[name].split() or [""]
        return [text]

    def replace(match):
        name = match.group(1) or match.group(2)
        return variables.get(name, match.group(0))

    return [_VARIABLE_RE.sub(replace, text)]


def _record_assignments(argv, variables):
    """Remember literal `NAME=value` assignments from a segment that consists only of assignments."""
    words = argv[1:] if argv and argv[0] in ("export", "declare", "local", "readonly") else argv
    if not words or not all(_ASSIGNMENT_RE.match(word) for word in words):
        return
    for word in words:
        name, _, value = word.partition("=")
        name = name.rstrip("+")
        if name in _RESERVED_VARIABLES:
            continue
        if "$" in value or "`" in value:
            variables.pop(name, None)
            continue
        variables[name] = value


class _Builder(object):
    """Turn a token list into segments, tracking `cd`, pipes, groups and nested command text."""

    def __init__(self, text, cwd, depth, variables, nested):
        self.text = text
        self.cwd = cwd
        self.depth = depth
        self.variables = variables
        self.nested = nested
        self.segments = []
        self.cwd_stack = []
        self.words = []
        self.redirects = []
        self.heredocs = []
        self.nested_texts = []
        self.start = None
        self.end = None
        self.previous_operator = ""
        self.previous_segment = None

    def add(self, token):
        """Add a non-operator token to the segment being built."""
        if self.start is None:
            self.start = token.start
        self.end = token.end
        self.nested_texts.extend(token.nested)
        if token.kind == "word":
            self.words.extend(_substitute_variables(token, self.variables))
        elif token.kind == "redirect":
            self.redirects.append((token.operator, token.text))
        elif token.kind == "heredoc":
            self.heredocs.append(token.body)

    def _stdin_text(self):
        """Return here-document text plus text an `echo` or `printf` pipes into this segment."""
        parts = list(self.heredocs)
        piped = self.previous_operator in _PIPE_OPERATORS and self.previous_segment is not None
        if piped and program(self.previous_segment.argv) in _ECHO_PROGRAMS:
            echoed = strip_wrappers(self.previous_segment.argv)[1:]
            parts.append(" ".join(word for word in echoed if not re.match(r"^-[neE]+$", word)))
        return "\n".join(part for part in parts if part)

    def flush(self, next_operator):
        """Finish the current segment (if any) at the control operator `next_operator`."""
        if self.start is not None:
            segment = Segment(self.words, self.redirects, self.text[self.start:self.end].strip(),
                              self.cwd, self._stdin_text(), self.nested)
            self.segments.append(segment)
            for inner in self.nested_texts:
                self.segments.extend(_parse_text(inner, self.cwd, self.depth + 1, self.variables))
            self.segments.extend(_carried_segments(segment, self.depth, self.variables))
            _record_assignments(segment.argv, self.variables)
            self._track_cd(segment, next_operator)
            self.previous_segment = segment
        elif next_operator not in ("(", "{"):
            self.previous_segment = None
        self.words = []
        self.redirects = []
        self.heredocs = []
        self.nested_texts = []
        self.start = None
        self.end = None
        self.previous_operator = next_operator
        if next_operator == "(":
            self.cwd_stack.append(self.cwd)
        elif next_operator == ")" and self.cwd_stack:
            self.cwd = self.cwd_stack.pop()

    def _track_cd(self, segment, next_operator):
        """Update the tracked directory after a `cd` that affects the following segments."""
        stripped = strip_wrappers(segment.argv)
        if not stripped:
            return
        target = _cd_target(stripped)
        if target is None:
            return
        in_pipeline = self.previous_operator in _PIPE_OPERATORS or next_operator in _PIPE_OPERATORS
        if in_pipeline or next_operator == "&":
            return
        self.cwd = _join_cwd(self.cwd, target)


def _parse_text(text, cwd, depth, variables, nested=True):
    """Parse nested command text into segments; raises ShellSyntaxError when it cannot be tokenized."""
    if depth > MAX_NESTING_DEPTH:
        return []
    builder = _Builder(text, cwd, depth, variables, nested)
    for token in _lex(text):
        if token.kind == "operator":
            builder.flush(token.text)
        else:
            builder.add(token)
    builder.flush("")
    return builder.segments


def _argv_segments(argv, parent, depth, variables):
    """Build a nested segment directly from an argument list (for `xargs CMD` and `find -exec CMD`)."""
    if not argv or depth > MAX_NESTING_DEPTH:
        return []
    segment = Segment(argv, [], " ".join(argv), parent.cwd_hint, parent.heredoc, True)
    return [segment] + _carried_segments(segment, depth + 1, variables)


def _shell_command_string(args):
    """Return (command string, has script operand) for the arguments of `sh`, `bash -lc`, `su -c` and the like."""
    index = 0
    while index < len(args):
        word = args[index]
        if word in _SHELL_VALUE_OPTIONS:
            index += 2
            continue
        if word.startswith("-") and not word.startswith("--") and "c" in word[1:]:
            remaining = [item for item in args[index + 1:] if not item.startswith("-")]
            return (remaining[0] if remaining else ""), True
        if word.startswith("-") and word != "-":
            index += 1
            continue
        return "", word != "-"
    return "", False


def find_exec_commands(args):
    """Return the argument lists that `find` would run through -exec, -execdir, -ok and -okdir."""
    commands = []
    index = 0
    while index < len(args):
        if args[index] not in _FIND_EXEC_OPTIONS:
            index += 1
            continue
        index += 1
        command = []
        while index < len(args) and args[index] not in (";", "+"):
            command.append(args[index])
            index += 1
        commands.append(command)
    return commands


def xargs_command(args):
    """Return the command `xargs` runs: everything after its own leading options."""
    index = 0
    while index < len(args):
        word = args[index]
        if word == "--":
            return args[index + 1:]
        if not word.startswith("-"):
            break
        if word in _XARGS_VALUE_OPTIONS:
            index += 2
            continue
        index += 1
    return args[index:]


def _carried_segments(segment, depth, variables):
    """Return the segments for command text that `segment` carries as arguments or standard input."""
    stripped = strip_wrappers(segment.argv)
    if not stripped:
        return []
    name = os.path.basename(stripped[0])
    args = stripped[1:]
    cwd = segment.cwd_hint
    if name in _SHELL_PROGRAMS:
        command, has_script = _shell_command_string(args)
        if command:
            return _parse_text(command, cwd, depth + 1, variables)
        if not has_script and segment.heredoc:
            return _parse_text(segment.heredoc, cwd, depth + 1, variables)
        return []
    if name == "eval":
        return _parse_text(" ".join(args), cwd, depth + 1, variables)
    if name == "trap" and args:
        return _parse_text(args[0], cwd, depth + 1, variables)
    if name == "xargs":
        return _argv_segments(xargs_command(args), segment, depth, variables)
    if name == "find":
        carried = []
        for command in find_exec_commands(args):
            carried.extend(_argv_segments(command, segment, depth, variables))
        return carried
    wrapped_in_one_word = len(stripped) == 1 and " " in stripped[0] and stripped[0] != segment.argv[0]
    if wrapped_in_one_word:
        return _parse_text(stripped[0], cwd, depth + 1, variables)
    return []


def parse(command):
    """Parse a Bash command string.

    Returns `Parsed`. `Parsed.segments` lists every simple command, including the ones
    nested in substitutions, `sh -c` strings, `eval`, `xargs` and `find -exec`. When the
    text cannot be tokenized (for example an unbalanced quote) `Parsed.ok` is False and
    `segments` is empty, so callers fall back to conservative raw-text rules.
    """
    if not isinstance(command, str):
        return Parsed(False, [], "command is not text")
    try:
        segments = _parse_text(command, None, 0, {}, nested=False)
    except ShellSyntaxError as error:
        return Parsed(False, [], str(error))
    except (IndexError, RecursionError) as error:
        return Parsed(False, [], "scanner error: %s" % error)
    return Parsed(True, segments)


# ---------------------------------------------------------------- fetches


def is_url(word):
    """Return True when `word` starts with a URL scheme such as `https://`."""
    return bool(_URL_RE.match(word))


def is_remote_path(word):
    """Return True for an `scp`/`rsync` remote operand such as `user@host:path` or `rsync://host/x`."""
    if word.startswith("rsync://"):
        return True
    return bool(_REMOTE_PATH_RE.match(word)) and not is_url(word)


def url_basename(url):
    """Return the last path component of a URL, without query string or fragment."""
    path = url.split("#", 1)[0].split("?", 1)[0]
    if "://" in path:
        path = path.split("://", 1)[1]
        if "/" not in path:
            return ""
        path = path.split("/", 1)[1]
    elif ":" in path and not path.startswith("/"):
        path = path.split(":", 1)[1]
    return os.path.basename(path.rstrip("/"))


def _stdout_redirect(segment):
    """Return the file that receives the segment's standard output, or None."""
    for operator, target in segment.redirects:
        if operator in (">", ">>", ">|", "1>", "1>>", "&>", "&>>"):
            return target
    return None


def _fetch(name, url, output, segment):
    """Build one fetch record."""
    return {"program": name, "urls": [url] if url else [], "output": output, "cwd_hint": segment.cwd_hint}


def _in_directory(directory, name):
    """Join an optional download directory and a file name."""
    if directory and name:
        return os.path.join(directory, name)
    return name or directory


def _curl_fetches(args, segment):
    """Fetch records for `curl`: `-o` values pair with URLs in order; `-O` uses the URL base name."""
    options, operands = scan_options(args, _CURL_SHORT_VALUES, _CURL_LONG_VALUES)
    urls = [value for name, value in options if name == "--url" and value]
    urls.extend(word for word in operands if is_url(word) or "." in word)
    outputs = [value for name, value in options if name in ("-o", "--output") and value]
    remote_name = has_option(options, "-O", "--remote-name", "--remote-name-all")
    directory = option_value(options, "--output-dir")
    fetches = []
    for index, url in enumerate(urls):
        if index < len(outputs):
            output = None if outputs[index] == "-" else _in_directory(directory, outputs[index])
        elif remote_name:
            output = _in_directory(directory, url_basename(url)) or None
        else:
            output = _stdout_redirect(segment)
        fetches.append(_fetch("curl", url, output, segment))
    return fetches


def _wget_fetches(args, segment):
    """Fetch records for `wget`: `-O FILE`, else the URL base name inside `-P DIR` or the working directory."""
    options, operands = scan_options(args, _WGET_SHORT_VALUES, _WGET_LONG_VALUES)
    document = option_value(options, "-O", "--output-document")
    directory = option_value(options, "-P", "--directory-prefix")
    fetches = []
    for url in operands:
        if document == "-":
            output = _stdout_redirect(segment)
        elif document:
            output = document
        else:
            output = _in_directory(directory, url_basename(url) or "index.html")
        fetches.append(_fetch("wget", url, output, segment))
    return fetches


def _aria2_fetches(args, segment):
    """Fetch records for `aria2c`: `-o NAME` inside `-d DIR`."""
    options, operands = scan_options(args, _ARIA2_SHORT_VALUES, _ARIA2_LONG_VALUES)
    name = option_value(options, "-o", "--out")
    directory = option_value(options, "-d", "--dir")
    fetches = []
    for url in operands:
        output = _in_directory(directory, name or url_basename(url)) or None
        fetches.append(_fetch("aria2c", url, output, segment))
    return fetches


def _copy_fetches(name, operands, is_source_remote, segment):
    """Fetch records for copy-style programs: every remote source copied to a local last operand."""
    if len(operands) < 2:
        return []
    destination = operands[-1]
    if is_source_remote(destination):
        return []
    return [_fetch(name, source, destination, segment) for source in operands[:-1] if is_source_remote(source)]


def _is_storage_url(word):
    """Return True for an object-storage URL (`gs://`, `s3://`)."""
    return word.startswith(_STORAGE_SCHEMES)


def _git_clone_fetches(args, segment):
    """Fetch record for `git clone URL [DEST]`."""
    _, subcommand, rest = git_subcommand(args)
    if subcommand != "clone":
        return []
    _, operands = scan_options(rest, _GIT_CLONE_SHORT_VALUES, _GIT_CLONE_LONG_VALUES)
    if not operands:
        return []
    url = operands[0]
    if len(operands) > 1:
        destination = operands[1]
    else:
        destination = re.sub(r"\.git$", "", url_basename(url)) or None
    return [_fetch("git clone", url, destination, segment)]


def _pip_fetches(args, segment):
    """Fetch records for `pip download`."""
    if not args or args[0] != "download":
        return []
    options, operands = scan_options(args[1:], _PIP_SHORT_VALUES, _PIP_LONG_VALUES)
    directory = option_value(options, "-d", "--dest")
    if not operands:
        return [_fetch("pip download", "", directory, segment)]
    return [_fetch("pip download", requirement, directory, segment) for requirement in operands]


def _hugging_face_fetches(name, args, segment):
    """Fetch records for `huggingface-cli download` and `hf download` (REPO [FILE...])."""
    if not args or args[0] != "download":
        return []
    options, operands = scan_options(args[1:], "", _HF_LONG_VALUES)
    if not operands:
        return []
    repository = operands[0]
    directory = option_value(options, "--local-dir")
    label = name + " download"
    if len(operands) == 1:
        return [_fetch(label, "hf://" + repository, directory, segment)]
    fetches = []
    for file_name in operands[1:]:
        output = _in_directory(directory, file_name) if directory else None
        fetches.append(_fetch(label, "hf://%s/%s" % (repository, file_name), output, segment))
    return fetches


def _segment_fetches(segment):
    """Return the fetch records of one segment (empty for a segment that downloads nothing)."""
    stripped = strip_wrappers(segment.argv)
    if not stripped:
        return []
    name = os.path.basename(stripped[0])
    args = stripped[1:]
    if _PYTHON_PROGRAM_RE.match(name) and args[:2] == ["-m", "pip"]:
        name = "pip"
        args = args[2:]
    if name == "curl":
        return _curl_fetches(args, segment)
    if name == "wget":
        return _wget_fetches(args, segment)
    if name == "aria2c":
        return _aria2_fetches(args, segment)
    if name == "scp":
        _, operands = scan_options(args, _SCP_SHORT_VALUES)
        return _copy_fetches("scp", operands, is_remote_path, segment)
    if name == "rsync":
        _, operands = scan_options(args, _RSYNC_SHORT_VALUES, _RSYNC_LONG_VALUES)
        return _copy_fetches("rsync", operands, is_remote_path, segment)
    if name == "gsutil":
        _, operands = scan_options(args, _GSUTIL_SHORT_VALUES)
        if operands[:1] == ["cp"] or operands[:1] == ["rsync"]:
            _, copy_operands = scan_options(operands[1:], "")
            return _copy_fetches("gsutil cp", copy_operands, _is_storage_url, segment)
        return []
    if name == "aws":
        _, operands = scan_options(args, "", _AWS_LONG_VALUES)
        if operands[:1] == ["s3"] and operands[1:2] in (["cp"], ["sync"]):
            return _copy_fetches("aws s3 " + operands[1], operands[2:], _is_storage_url, segment)
        return []
    if name == "gcloud":
        _, operands = scan_options(args, "")
        if operands[:2] == ["storage", "cp"]:
            return _copy_fetches("gcloud storage cp", operands[2:], _is_storage_url, segment)
        return []
    if name == "gdown":
        options, operands = scan_options(args, _GDOWN_SHORT_VALUES, _GDOWN_LONG_VALUES)
        source = option_value(options, "--id") or (operands[0] if operands else "")
        return [_fetch("gdown", source, option_value(options, "-O", "--output"), segment)]
    if name == "git":
        return _git_clone_fetches(args, segment)
    if name in ("pip", "pip3"):
        return _pip_fetches(args, segment)
    if name in ("huggingface-cli", "hf"):
        return _hugging_face_fetches(name, args, segment)
    return []


def fetches(parsed):
    """List the downloads a parsed command would perform.

    Each record is `{"program", "urls": [...], "output": path or None, "cwd_hint"}`. `output`
    is the path as written in the command (a file, or a directory the file lands in);
    uploads and local copies are not fetches.
    """
    found = []
    for segment in parsed.segments:
        found.extend(_segment_fetches(segment))
    return found
