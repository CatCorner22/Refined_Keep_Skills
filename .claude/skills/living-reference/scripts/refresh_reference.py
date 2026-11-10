#!/usr/bin/env python3
"""Regenerate the four generated blocks of a living-reference Markdown file.

Usage:
    refresh_reference.py FILE.md [FILE.md ...] [--check] [--warnings-ok]
                         [--stale-days N] [--today YYYY-MM-DD] [--allow-missing-blocks]

The script rewrites only the lines between these marker pairs:
    <!-- toc:start -->          <!-- toc:end -->            contents, from the headings
    <!-- authorities:start -->  <!-- authorities:end -->    cite index, from the source list
    <!-- index:start -->        <!-- index:end -->          subject index, from the index tags
    <!-- health:start -->       <!-- health:end -->         stamp line and findings

Exit status:
    0  the file is refreshed (or, with --check, it is clean and up to date)
    1  --check only: findings exist, or a generated block is out of date
    2  usage error, unreadable file, or a structure error (nothing is written)

The script uses the standard library only and runs on Python 3.8 or later.
The file format is described in references/format.md of the skill.
"""
import argparse
import collections
import datetime
import os
import re
import shutil
import sys
import tempfile
import unicodedata

DEFAULT_STALE_DAYS = 90
MAX_LOCATORS = 7
MAX_CITE_RANGE = 50
SHORT_CITE_LIMIT = 110
SOURCES_ID = '90'
RULE_TOPIC_FIRST = 10
RULE_TOPIC_LAST = 79
BLOCK_NAMES = ('toc', 'authorities', 'index', 'health')
TOC_SKIPPED_TITLES = ('contents', 'table of contents')
UTF8_BOM = b'\xef\xbb\xbf'

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

TEXT = 'text'
CODE = 'code'
COMMENT = 'comment'

ROLE_CONTENT = 'content'
ROLE_FENCE = 'fence'
ROLE_MARKER = 'marker'
ROLE_GENERATED = 'generated'

# Every pattern below is linear: no pattern lets two adjacent parts match the same characters.
FENCE = re.compile(r'^[ \t]*(`{3,}|~{3,})(.*)$')
INLINE_TOKEN = re.compile(r'(`+)|(<!--)')
BACKTICK_RUN = re.compile(r'`+')
MARKER_BODY = re.compile(r'^(\w+):(start|end)$')
ATX_HEADING = re.compile(r'^ {0,3}(#{1,6})([ \t].*)?$')
HEADING_ID = re.compile(r'^\[([^\[\]]*)\](.*)$')
ID_SHAPE = re.compile(r'^\d{2}(\.\d{2,3})?$')
SOURCE_LINE = re.compile(r'^ {0,3}[-*+][ \t]+\[(S\d+)\][ \t]+(\S.*)$')
SOURCE_LIKE = re.compile(r'^ {0,3}(?:[-*+]|\d+[.)])[ \t]+[*_]*\[')
LIST_ITEM = re.compile(r'^[ \t]*(?:[-*+]|\d+[.)])[ \t]')
RETIRED = re.compile(r'^\(retired\b', re.IGNORECASE)
SUPERSEDED = re.compile(r'superseded by \[(S\d+)\]', re.IGNORECASE)
BRACKET = re.compile(r'\[([^\[\]\n]*)\]')
CITE_START = re.compile(r'^[Ss]\d')
CITE_ITEM = re.compile(r'^S(\d+)(?:\s*[-–]\s*S(\d+))?(?:\s+at\s+\S.*)?$')
CITE_COMMA = re.compile(r',(?=\s*[Ss]\d)')
BRACE_TAG = re.compile(r'\{\{([^{}\n]*)\}\}')
OPEN_BRACE_TAG = re.compile(r'\{\{\s*index\s*:', re.IGNORECASE)
INDEX_PREFIX = re.compile(r'^\s*index\s*:', re.IGNORECASE)
SEE_ALSO_PREFIX = re.compile(r'^see also\s*:', re.IGNORECASE)
VERIFIED_LINE = re.compile(r'^(?:[-*+][ \t]+)?\**Last verified[:.]\**[ \t]*(\S*)', re.IGNORECASE)
STALE_LINE = re.compile(r'^[>*_ \t]*Stale-after:[ \t]*(\S*)', re.IGNORECASE)
RULE_LABEL = re.compile(r'^(?:[-*+][ \t]+)?\*\*Rule\.\*\*')
FIELD_LABEL = re.compile(r'^(?:[-*+][ \t]+)?\*\*')
CITE_NEEDED = '[cite needed]'
URL = re.compile(r'https?://\S+')
XREF = re.compile(r'§{1,2}(\d+(?:\.\d+)*)')
XREF_RANGE = re.compile(r'\s?[-–]\s?(\d+(?:\.\d+)*)')
XREF_LIST = re.compile(r',\s?§?(\d+\.\d+)')
MARKDOWN_LINK = re.compile(r'\[([^\[\]]*)\]\([^()]*\)')
SLUG_DROPPED = re.compile(r'[^\w\- ]')
STAMP_DATE = re.compile(r'Generated content last changed (\d{4}-\d{2}-\d{2})\._$')
SHORT_CITE_CUT = re.compile(r'\.? (?=https?://)|\. (?=Accessed \d)|\. (?=Grade: )')
INDEX_ESCAPED = re.compile(r'([\\`*_\[\]<])')

Line = collections.namedtuple('Line', 'is_fence segments')
Source = collections.namedtuple('Source', 'lines eols bom eol')
Result = collections.namedtuple(
    'Result', 'lines eols changed errors warnings summary stale_days stale_origin')


class StructureError(Exception):
    """The file cannot be refreshed safely. The messages say why; nothing is written."""

    def __init__(self, messages):
        Exception.__init__(self, '; '.join(messages))
        self.messages = list(messages)


# ----------------------------------------------------------------------------------------------
# Reading and writing

def read_source(path):
    """Read a file as UTF-8 and remember its byte-order mark and line endings.

    The script writes the same mark and the same endings back, so a refresh
    never converts a CRLF file to LF and never drops a byte-order mark.
    """
    with open(path, 'rb') as handle:
        raw = handle.read()
    bom = raw.startswith(UTF8_BOM)
    if bom:
        raw = raw[len(UTF8_BOM):]
    text = raw.decode('utf-8')
    lines, eols = split_lines(text)
    crlf_count = eols.count('\r\n')
    lf_count = eols.count('\n')
    eol = '\r\n' if crlf_count > lf_count else '\n'
    return Source(lines, eols, bom, eol)


def split_lines(text):
    """Split text into lines and a parallel list that holds each line's own ending."""
    parts = re.split('(\r\n|\n)', text)
    lines = parts[0::2]
    eols = parts[1::2] + ['']
    return lines, eols


def join_lines(lines, eols):
    """Rebuild the text from lines and their endings."""
    return ''.join(line + eol for line, eol in zip(lines, eols))


def write_atomic(path, data):
    """Replace a file's content in one step.

    The new content goes to a temporary file in the same directory first. A full
    disk or a killed process therefore leaves the original file complete.
    """
    target = os.path.realpath(path)
    directory = os.path.dirname(target)
    prefix = '.' + os.path.basename(target) + '.'
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=prefix, suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        shutil.copymode(target, temporary)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


# ----------------------------------------------------------------------------------------------
# Line scanner: fenced code, inline code, HTML comments

def scan_lines(lines):
    """Classify every line once, so that later steps never read code or comments as content.

    Returns the scanned lines, the comment bodies by comment number, and a list of
    structure problems (a fence or a comment that never closes).
    """
    scanned = []
    comments = {}
    problems = []
    fence = None
    fence_line = 0
    open_comment = None
    comment_line = 0
    for number, line in enumerate(lines, 1):
        if fence is not None:
            scanned.append(Line(True, [(CODE, line, None)]))
            if closes_fence(line, fence):
                fence = None
            continue
        if open_comment is None:
            opened = opening_fence(line)
            if opened is not None:
                fence = opened
                fence_line = number
                scanned.append(Line(True, [(CODE, line, None)]))
                continue
        was_open = open_comment
        segments, open_comment = split_inline(line, open_comment, comments)
        if open_comment is not None and open_comment != was_open:
            comment_line = number
        scanned.append(Line(False, segments))
    if fence is not None:
        problems.append('line %d: the code fence that opens here never closes' % fence_line)
    if open_comment is not None:
        problems.append('line %d: the HTML comment that opens here never closes' % comment_line)
    return scanned, comments, problems


def opening_fence(line):
    """Return (character, length) when the line opens a fenced code block."""
    match = FENCE.match(line)
    if match is None:
        return None
    run = match.group(1)
    if run[0] == '`' and '`' in match.group(2):
        return None
    return (run[0], len(run))


def closes_fence(line, fence):
    """A fence closes on a run of the same character, at least as long, with nothing after it."""
    match = FENCE.match(line)
    if match is None:
        return False
    run = match.group(1)
    return run[0] == fence[0] and len(run) >= fence[1] and not match.group(2).strip()


def split_inline(line, open_comment, comments):
    """Split one line into text, inline-code and comment segments.

    The segments joined together equal the line. Returns the segments and the number
    of the comment that is still open at the end of the line (or None).
    """
    segments = []
    position = 0
    if open_comment is not None:
        end = line.find('-->')
        if end < 0:
            comments[open_comment].append(line)
            return [(COMMENT, line, open_comment)], open_comment
        comments[open_comment].append(line[:end])
        segments.append((COMMENT, line[:end + 3], open_comment))
        position = end + 3
    while True:
        match = INLINE_TOKEN.search(line, position)
        if match is None:
            break
        if match.start() > position:
            segments.append((TEXT, line[position:match.start()], None))
        if match.group(1):
            close = closing_backticks(line, match.end(), len(match.group(1)))
            if close is None:
                segments.append((TEXT, match.group(1), None))
                position = match.end()
            else:
                segments.append((CODE, line[match.start():close], None))
                position = close
            continue
        number = len(comments)
        comments[number] = []
        end = line.find('-->', match.end())
        if end < 0:
            comments[number].append(line[match.end():])
            segments.append((COMMENT, line[match.start():], number))
            return segments, number
        comments[number].append(line[match.end():end])
        segments.append((COMMENT, line[match.start():end + 3], number))
        position = end + 3
    if position < len(line):
        segments.append((TEXT, line[position:], None))
    return segments, None


def closing_backticks(line, start, length):
    """Return the position just after the next backtick run of exactly this length."""
    for match in BACKTICK_RUN.finditer(line, start):
        if len(match.group(0)) == length:
            return match.end()
    return None


def visible_text(line):
    """The prose of a line: inline code becomes one space and comments disappear."""
    if line.is_fence:
        return ''
    parts = []
    for kind, text, _ in line.segments:
        if kind == TEXT:
            parts.append(text)
        elif kind == CODE:
            parts.append(' ')
    return ''.join(parts)


def text_without_comments(line):
    """The line with comments removed and inline code kept (used for titles and citations)."""
    if line.is_fence:
        return ''
    return ''.join(text for kind, text, _ in line.segments if kind != COMMENT)


def comment_body(comments, number):
    """The text between the comment delimiters."""
    return '\n'.join(comments[number])


def marker_of(line, comments):
    """Return (name, 'start' or 'end') when the whole line is one block marker."""
    if line.is_fence:
        return None
    found = None
    for kind, text, number in line.segments:
        if kind == COMMENT:
            if found is not None:
                return None
            if not (text.startswith('<!--') and text.endswith('-->')):
                return None
            found = number
        elif text.strip():
            return None
    if found is None:
        return None
    match = MARKER_BODY.match(comment_body(comments, found).strip())
    if match is None or match.group(1) not in BLOCK_NAMES:
        return None
    return (match.group(1), match.group(2))


def comments_starting_on(line):
    """Numbers of the comments that open on this line."""
    numbers = []
    for kind, text, number in line.segments:
        if kind == COMMENT and text.startswith('<!--'):
            numbers.append(number)
    return numbers


def is_index_comment(body):
    """True for the invisible tag form <!-- index: term | alias -->."""
    return INDEX_PREFIX.match(body) is not None


# ----------------------------------------------------------------------------------------------
# Generated blocks: find and validate before anything is replaced

def find_blocks(scanned, comments, allow_missing):
    """Locate the four marker pairs and refuse any layout that could delete content.

    A block is valid when it has exactly one start marker and one end marker, in
    that order, with no heading and no other marker between them.
    """
    positions = {}
    for index, line in enumerate(scanned):
        marker = marker_of(line, comments)
        if marker is not None:
            positions.setdefault(marker[0], {'start': [], 'end': []})[marker[1]].append(index)
    spans = {}
    problems = []
    marker_lines = set()
    for found in positions.values():
        marker_lines.update(found['start'])
        marker_lines.update(found['end'])
    for name in BLOCK_NAMES:
        found = positions.get(name)
        if found is None:
            if not allow_missing:
                problems.append(
                    'block "%s" is missing: add the lines <!-- %s:start --> and <!-- %s:end -->'
                    % (name, name, name))
            continue
        problem = block_problem(name, found, scanned, marker_lines)
        if problem is not None:
            problems.append(problem)
            continue
        spans[name] = (found['start'][0], found['end'][0])
    return spans, problems


def block_problem(name, found, scanned, marker_lines):
    """Describe what is wrong with one block's markers, or return None."""
    starts = [index + 1 for index in found['start']]
    ends = [index + 1 for index in found['end']]
    if len(starts) != 1 or len(ends) != 1:
        return ('block "%s" needs exactly 1 start marker and 1 end marker (start at line %s; '
                'end at line %s)' % (name, describe_numbers(starts), describe_numbers(ends)))
    if starts[0] > ends[0]:
        return ('block "%s": the end marker (line %d) is above the start marker (line %d)'
                % (name, ends[0], starts[0]))
    for index in range(starts[0], ends[0] - 1):
        if index in marker_lines:
            return ('block "%s": another marker sits inside the block at line %d'
                    % (name, index + 1))
        if not scanned[index].is_fence and ATX_HEADING.match(text_without_comments(scanned[index])):
            return ('block "%s": a heading sits inside the block at line %d; '
                    'the end marker is misplaced' % (name, index + 1))
    return None


def describe_numbers(numbers):
    """Line numbers as text, or the word none."""
    if not numbers:
        return 'none'
    return ', '.join(str(number) for number in numbers)


def line_roles(scanned, comments, spans):
    """Give every line one role: content, fence, marker or generated."""
    roles = []
    for line in scanned:
        if line.is_fence:
            roles.append(ROLE_FENCE)
        elif marker_of(line, comments) is not None:
            roles.append(ROLE_MARKER)
        else:
            roles.append(ROLE_CONTENT)
    for start, end in spans.values():
        for index in range(start + 1, end):
            roles[index] = ROLE_GENERATED
    return roles


# ----------------------------------------------------------------------------------------------
# Headings and sections

def parse_heading(text):
    """Return (level, heading text) for an ATX heading, with a closing # run removed."""
    match = ATX_HEADING.match(text)
    if match is None:
        return None
    title = (match.group(2) or '').strip()
    without_hashes = title.rstrip('#')
    if without_hashes != title and (not without_hashes or without_hashes[-1] in ' \t'):
        title = without_hashes.rstrip()
    return len(match.group(1)), title


def split_heading_id(heading_text):
    """Return (section ID, title) when the heading has the form [12.04] Title."""
    match = HEADING_ID.match(heading_text)
    if match is None:
        return None
    section_id = match.group(1)
    title = match.group(2).strip()
    if ID_SHAPE.match(section_id) is None or not title:
        return None
    return section_id, title


def github_slug(heading_text, seen):
    """Build the anchor that GitHub gives a heading, numbering repeats (-1, -2)."""
    plain = MARKDOWN_LINK.sub(r'\1', heading_text)
    slug = SLUG_DROPPED.sub('', plain.lower()).replace(' ', '-')
    count = seen.get(slug, 0)
    seen[slug] = count + 1
    if count == 0:
        return slug
    return '%s-%d' % (slug, count)


def collect_sections(scanned, roles, errors):
    """Read every heading outside code and comments and cut the file into sections.

    A heading without a valid [ID] and a title is an error finding, because the
    contents, the index and the checks cannot see its text.
    """
    sections = []
    headings = []
    seen_slugs = {}
    current = None
    for index, line in enumerate(scanned):
        if roles[index] != ROLE_CONTENT:
            continue
        heading = parse_heading(text_without_comments(line))
        if heading is None:
            if current is not None:
                current['lines'].append(index)
            continue
        level, heading_text = heading
        slug = github_slug(heading_text, seen_slugs)
        parsed = split_heading_id(heading_text)
        if parsed is None:
            errors.append('line %d: heading has no valid [ID] and title ("%s"); write it as '
                          '"## [12] Title" or "### [12.04] Title"' % (index + 1, heading_text))
            headings.append(None)
            current = None
            continue
        current = {'id': parsed[0], 'title': parsed[1], 'level': level, 'slug': slug,
                   'line': index, 'lines': [], 'first': not headings}
        headings.append(current)
        sections.append(current)
    return sections


def in_source_list(section):
    """True for the Sources section [90] and its sub-sections."""
    return section['id'] == SOURCES_ID or section['id'].startswith(SOURCES_ID + '.')


def is_rule_section(section, texts):
    """A rule section has a Rule label, or a dotted ID inside the body topic range."""
    for text in texts:
        if RULE_LABEL.match(text.strip()):
            return True
    if '.' not in section['id']:
        return False
    topic = int(section['id'].split('.')[0])
    return RULE_TOPIC_FIRST <= topic <= RULE_TOPIC_LAST


# ----------------------------------------------------------------------------------------------
# Source list and cites

def read_source_list(sections, scanned, errors):
    """Read source lines from the Sources section only, in file order."""
    sources = collections.OrderedDict()
    counts = collections.Counter()
    found_section = False
    for section in sections:
        if not in_source_list(section):
            continue
        found_section = True
        last_key = None
        for index in section['lines']:
            text = text_without_comments(scanned[index])
            match = SOURCE_LINE.match(text)
            if match is not None:
                last_key = match.group(1)
                counts[last_key] += 1
                if last_key not in sources:
                    sources[last_key] = normalise_space(match.group(2))
                continue
            if SOURCE_LIKE.match(text):
                errors.append('line %d: source line is not in the form "- [S12] citation"'
                              % (index + 1))
                last_key = None
                continue
            if last_key is not None and text[:1] in (' ', '\t') and text.strip():
                if not LIST_ITEM.match(text) and counts[last_key] == 1:
                    sources[last_key] += ' ' + normalise_space(text)
                continue
            last_key = None
    if not found_section:
        errors.append('no Sources section: add the heading "## [%s] Sources" and list each '
                      'source under it' % SOURCES_ID)
    for key, count in counts.items():
        if count > 1:
            errors.append('source key [%s] appears %d times in the source list; a key must '
                          'name 1 source' % (key, count))
    for key, text in sources.items():
        match = SUPERSEDED.search(text)
        if match is not None and match.group(1) not in sources:
            errors.append('[%s] is superseded by [%s], which is not in the source list'
                          % (key, match.group(1)))
    return sources


def normalise_space(text):
    """Collapse every whitespace run to one space."""
    return ' '.join(text.split())


def parse_cite_group(inner):
    """Return the source keys in one bracket such as 'S1 at 4; S2' or 'S5-S7', or None."""
    keys = []
    for part in inner.split(';'):
        for item in CITE_COMMA.split(part):
            match = CITE_ITEM.match(item.strip())
            if match is None:
                return None
            low = int(match.group(1))
            high = int(match.group(2) or match.group(1))
            if high < low or high - low > MAX_CITE_RANGE:
                return None
            keys.extend('S%d' % number for number in range(low, high + 1))
    return keys


def cites_in(text):
    """Return (source keys, malformed cite brackets) found in a piece of prose."""
    keys = []
    malformed = []
    for match in BRACKET.finditer(text):
        inner = match.group(1).strip()
        if CITE_START.match(inner) is None:
            continue
        parsed = parse_cite_group(inner)
        if parsed is not None:
            keys.extend(parsed)
        elif text[match.end():match.end() + 1] != '(':
            malformed.append('[' + inner + ']')
    return keys, malformed


def strip_cites(text):
    """Remove cite brackets, so that a pinpoint such as [S1 at §3] is not read as a cross-reference."""
    def replace(match):
        if CITE_START.match(match.group(1).strip()):
            return ' '
        return match.group(0)
    return BRACKET.sub(replace, text)


def short_cite(full):
    """Shorten a source line for the cite index: cut at the URL, Accessed or Grade field."""
    short = SHORT_CITE_CUT.split(full, maxsplit=1)[0].rstrip(' .')
    if len(short) <= SHORT_CITE_LIMIT:
        return short
    return short[:SHORT_CITE_LIMIT].rsplit(' ', 1)[0] + '…'


def build_cite_index(sources, cited_in):
    """One line for each source, in source-list order, with every section that cites it."""
    lines = []
    for key, text in sources.items():
        where = cited_in.get(key)
        if where:
            locators = ', '.join('§' + section_id for section_id in where)
        else:
            locators = '(not cited)'
        lines.append('- [%s] %s — %s' % (key, short_cite(text), locators))
    return lines


# ----------------------------------------------------------------------------------------------
# Index tags

def tag_bodies(section, scanned, comments, errors):
    """Collect the bodies of both tag forms in one section, in file order."""
    bodies = []
    for index in section['lines']:
        line = scanned[index]
        for number in comments_starting_on(line):
            body = comment_body(comments, number)
            if is_index_comment(body):
                bodies.append(INDEX_PREFIX.sub('', body, count=1))
        text = visible_text(line)
        for match in BRACE_TAG.finditer(text):
            if INDEX_PREFIX.match(match.group(1)):
                bodies.append(INDEX_PREFIX.sub('', match.group(1), count=1))
        if OPEN_BRACE_TAG.search(BRACE_TAG.sub('', text)):
            errors.append('line %d: index tag has no closing }}' % (index + 1))
    return bodies


def parse_tag(body):
    """Split a tag body into (term, aliases, see-also terms)."""
    term, _, rest = body.partition('|')
    aliases = []
    related = []
    for part in rest.split(';'):
        part = normalise_space(part)
        if not part:
            continue
        if SEE_ALSO_PREFIX.match(part):
            pointers = SEE_ALSO_PREFIX.sub('', part, count=1)
            related.extend(normalise_space(item) for item in pointers.split(',') if item.strip())
        else:
            aliases.append(part)
    return normalise_space(term), aliases, related


def collect_index(sections, scanned, comments, errors, warnings):
    """Build the index data: terms with locators, aliases, and see-also pointers."""
    terms = collections.OrderedDict()
    aliases = collections.OrderedDict()
    for section in sections:
        for body in tag_bodies(section, scanned, comments, errors):
            term, tag_aliases, related = parse_tag(body)
            if not term:
                errors.append('§%s: index tag has no term' % section['id'])
                continue
            entry = terms.setdefault(term.casefold(), {
                'display': term, 'spellings': [], 'sections': [], 'related': []})
            if term not in entry['spellings']:
                entry['spellings'].append(term)
            if section['id'] not in entry['sections']:
                entry['sections'].append(section['id'])
            for pointer in related:
                if pointer.casefold() not in [item.casefold() for item in entry['related']]:
                    entry['related'].append(pointer)
            for alias in tag_aliases:
                record = aliases.setdefault(alias.casefold(), {'display': alias, 'targets': []})
                if term.casefold() not in record['targets']:
                    record['targets'].append(term.casefold())
    check_index(terms, aliases, errors, warnings)
    return terms, aliases


def check_index(terms, aliases, errors, warnings):
    """Report index entries that would lose a reader: conflicts and dangling pointers."""
    for key in list(aliases):
        record = aliases[key]
        if key in terms:
            warnings.append('index alias "%s" is also a preferred term; the alias is ignored'
                            % record['display'])
            del aliases[key]
            continue
        if len(record['targets']) > 1:
            names = ', '.join(terms[target]['display'] for target in record['targets'])
            errors.append('index alias "%s" points to %d terms (%s); keep 1'
                          % (record['display'], len(record['targets']), names))
    for key, entry in terms.items():
        if len(entry['spellings']) > 1:
            warnings.append('index term is spelled %d ways (%s); the index uses the first'
                            % (len(entry['spellings']), ', '.join(entry['spellings'])))
        if len(entry['sections']) > MAX_LOCATORS:
            warnings.append('index term "%s" has %d locators; split it into narrower terms '
                            '(limit %d)' % (entry['display'], len(entry['sections']), MAX_LOCATORS))
        for pointer in entry['related']:
            if pointer.casefold() not in terms and pointer.casefold() not in aliases:
                errors.append('index term "%s" has a see-also pointer to "%s", which is not an '
                              'index term' % (entry['display'], pointer))


def sort_key(term):
    """Sort text without regard to case or accents; put symbols before letters."""
    folded = ''.join(char for char in unicodedata.normalize('NFKD', term)
                     if not unicodedata.combining(char)).casefold()
    return (index_group(term) != 'Symbols', folded)


def index_group(term):
    """The letter heading for a term; every term that starts with a non-letter goes to Symbols."""
    first = unicodedata.normalize('NFKD', term.strip())[:1]
    if first.isalpha():
        return first.upper()
    return 'Symbols'


def escape_markdown(text):
    """Escape characters that would start emphasis, code, a link or HTML in an index line."""
    return INDEX_ESCAPED.sub(r'\\\1', text)


def build_index(terms, aliases):
    """Render the subject index, grouped by first letter."""
    entries = []
    for entry in terms.values():
        locators = ', '.join('§' + section_id for section_id in entry['sections'])
        text = '- **%s** — %s' % (escape_markdown(entry['display']), locators)
        if entry['related']:
            pointers = ', '.join(escape_markdown(item) for item in entry['related'])
            text += '; *see also* ' + pointers
        entries.append((entry['display'], text))
    for record in aliases.values():
        target = terms[record['targets'][0]]['display']
        text = '- %s — *see* %s' % (escape_markdown(record['display']), escape_markdown(target))
        entries.append((record['display'], text))
    entries.sort(key=lambda item: sort_key(item[0]))
    lines = []
    group = None
    for display, text in entries:
        if index_group(display) != group:
            group = index_group(display)
            if lines:
                lines.append('')
            lines.append('**%s**' % group)
            lines.append('')
        lines.append(text)
    return lines


# ----------------------------------------------------------------------------------------------
# Contents

def build_toc(sections):
    """Render the contents list with GitHub anchors, nested by heading level."""
    lines = []
    open_levels = []
    for section in sections:
        if section['first'] and section['level'] == 1:
            continue
        if section['title'].lower() in TOC_SKIPPED_TITLES:
            continue
        while open_levels and open_levels[-1] >= section['level']:
            open_levels.pop()
        label = '%s %s' % (section['id'], section['title'])
        label = label.replace('[', '\\[').replace(']', '\\]')
        lines.append('%s- [%s](#%s)' % ('  ' * len(open_levels), label, section['slug']))
        open_levels.append(section['level'])
    return lines


# ----------------------------------------------------------------------------------------------
# Checks

def find_stale_days(scanned, roles, errors):
    """Read the cadence that the file stores in a line such as 'Stale-after: 120'."""
    values = []
    for index, line in enumerate(scanned):
        if roles[index] != ROLE_CONTENT:
            continue
        match = STALE_LINE.match(visible_text(line))
        if match is None:
            continue
        value = match.group(1).strip('*_.')
        if value.isdigit() and int(value) > 0:
            values.append(int(value))
        else:
            errors.append('line %d: Stale-after needs a whole number of days greater than 0'
                          % (index + 1))
    if len(set(values)) > 1:
        errors.append('the file holds %d different Stale-after values; keep 1' % len(set(values)))
    if values:
        return values[0]
    return None


def check_dates(section, texts, rule, today, stale_days, errors, warnings):
    """Check the section's last 'Last verified' line: present, valid, not future, not stale."""
    label = '§' + section['id']
    values = []
    for text in texts:
        match = VERIFIED_LINE.match(text.strip())
        if match is not None:
            values.append(match.group(1).strip('*_.,;'))
    if not values:
        if rule:
            warnings.append('%s: no Last verified line' % label)
        return
    try:
        verified = datetime.date.fromisoformat(values[-1])
    except ValueError:
        errors.append('%s: Last verified date "%s" is not a valid YYYY-MM-DD date'
                      % (label, values[-1]))
        return
    if verified > today:
        errors.append('%s: Last verified date %s is in the future' % (label, verified.isoformat()))
    elif (today - verified).days > stale_days:
        warnings.append('%s: last verified %s, older than the %d-day cadence'
                        % (label, verified.isoformat(), stale_days))


def rule_line_has_cite(texts):
    """True unless a Rule field exists and holds neither a cite nor [cite needed]."""
    in_rule = False
    field = []
    for text in texts:
        stripped = text.strip()
        if RULE_LABEL.match(stripped):
            in_rule = True
            field = [stripped]
            continue
        if in_rule:
            if not stripped or FIELD_LABEL.match(stripped) or VERIFIED_LINE.match(stripped):
                break
            field.append(stripped)
    if not field:
        return True
    joined = ' '.join(field)
    keys, _ = cites_in(joined)
    return bool(keys) or CITE_NEEDED in joined.lower()


def cross_references(text):
    """Return the section IDs that a line refers to with the section sign.

    Only a number in the shape of this file's IDs counts, so a statute cite such
    as '17 U.S.C. §107' is not read as a link to a section of the file.
    """
    cleaned = strip_cites(URL.sub(' ', text))
    found = []
    position = 0
    while True:
        match = XREF.search(cleaned, position)
        if match is None:
            break
        found.append(match.group(1))
        position = match.end()
        while True:
            more = XREF_RANGE.match(cleaned, position) or XREF_LIST.match(cleaned, position)
            if more is None:
                break
            found.append(more.group(1))
            position = more.end()
    return [reference for reference in found if ID_SHAPE.match(reference)]


def check_sections(sections, scanned, sources, today, stale_days, errors, warnings):
    """Run the per-section checks and return the map from source key to citing sections."""
    ids = collections.Counter(section['id'] for section in sections)
    for section_id, count in ids.items():
        if count > 1:
            errors.append('section ID [%s] is used %d times; an ID must name 1 section'
                          % (section_id, count))
    cited_in = collections.OrderedDict()
    undefined = collections.OrderedDict()
    for section in sections:
        label = '§' + section['id']
        texts = [visible_text(scanned[index]) for index in section['lines']]
        check_dates(section, texts, is_rule_section(section, texts), today, stale_days,
                    errors, warnings)
        if in_source_list(section):
            continue
        joined = '\n'.join(texts)
        if CITE_NEEDED in joined.lower():
            warnings.append('%s: holds [cite needed]' % label)
        if not rule_line_has_cite(texts):
            warnings.append('%s: the Rule line has no cite; add one or write [cite needed]'
                            % label)
        keys, malformed = cites_in(joined)
        for cite in malformed:
            errors.append('%s: malformed cite %s; write [S1], [S1 at 4], [S1, S2] or [S1; S2]'
                          % (label, cite))
        for key in keys:
            target = cited_in if key in sources else undefined
            if section['id'] not in target.setdefault(key, []):
                target[key].append(section['id'])
        missing = []
        for text in texts:
            for reference in cross_references(text):
                if reference not in ids and reference not in missing:
                    missing.append(reference)
        for reference in missing:
            errors.append('%s refers to §%s, which does not exist' % (label, reference))
    for key, where in undefined.items():
        locators = ', '.join('§' + section_id for section_id in where)
        errors.append('cite key [%s] in %s is not in the source list' % (key, locators))
    for key, text in sources.items():
        if key not in cited_in and RETIRED.match(text) is None:
            warnings.append('source [%s] is not cited; cite it, or mark it "(retired YYYY-MM-DD)"'
                            % key)
    return cited_in


# ----------------------------------------------------------------------------------------------
# Whole-file refresh

def plural(count, noun):
    """Return '1 source' or '2 sources'."""
    if count == 1:
        return '1 %s' % noun
    return '%d %ss' % (count, noun)


def build_health(summary, stale_days, stamp_date, errors, warnings):
    """Render the health block: one stamp line, then every finding."""
    stamp = '_%s. Cadence: %d days. Generated content last changed %s._' % (
        summary, stale_days, stamp_date)
    lines = [stamp, '']
    if not errors and not warnings:
        lines.append('- No findings.')
    lines.extend('- Error: %s.' % finding for finding in errors)
    lines.extend('- Warning: %s.' % finding for finding in warnings)
    return lines


def existing_stamp_date(lines, span):
    """Read the date from the stamp line that the file already holds."""
    for index in range(span[0] + 1, span[1]):
        match = STAMP_DATE.search(lines[index])
        if match is not None:
            return match.group(1)
    return None


def refresh_lines(lines, eols, eol, today, stale_days=None, allow_missing_blocks=False):
    """Build the refreshed file in memory and return a Result. Nothing is written here.

    The date in the stamp line changes only when other generated content changes,
    so a refresh on a later day leaves an unchanged file byte-identical.
    Raises StructureError when the file cannot be refreshed safely.
    """
    scanned, comments, problems = scan_lines(lines)
    if problems:
        raise StructureError(problems)
    spans, problems = find_blocks(scanned, comments, allow_missing_blocks)
    if problems:
        raise StructureError(problems)
    roles = line_roles(scanned, comments, spans)
    errors = []
    warnings = []
    sections = collect_sections(scanned, roles, errors)
    if not sections:
        raise StructureError(['no heading of the form "## [12] Title" found; '
                              'this is not a living reference'])
    file_days = find_stale_days(scanned, roles, errors)
    if stale_days is not None:
        origin = 'from --stale-days'
    elif file_days is not None:
        stale_days = file_days
        origin = 'from the Stale-after line'
    else:
        stale_days = DEFAULT_STALE_DAYS
        origin = 'default'
    sources = read_source_list(sections, scanned, errors)
    cited_in = check_sections(sections, scanned, sources, today, stale_days, errors, warnings)
    terms, aliases = collect_index(sections, scanned, comments, errors, warnings)
    summary = ', '.join([plural(len(sections), 'section'), plural(len(sources), 'source'),
                         plural(len(terms), 'index term')])
    blocks = {
        'toc': build_toc(sections),
        'authorities': build_cite_index(sources, cited_in),
        'index': build_index(terms, aliases),
    }
    old_date = None
    if 'health' in spans:
        old_date = existing_stamp_date(lines, spans['health'])
    blocks['health'] = build_health(summary, stale_days, old_date or today.isoformat(),
                                    errors, warnings)
    changed = changed_blocks(lines, spans, blocks)
    if changed and old_date is not None:
        blocks['health'] = build_health(summary, stale_days, today.isoformat(), errors, warnings)
        changed = changed_blocks(lines, spans, blocks)
    new_lines = list(lines)
    new_eols = list(eols)
    for name in sorted(changed, key=lambda item: spans[item][0], reverse=True):
        start, end = spans[name]
        new_lines[start + 1:end] = blocks[name]
        new_eols[start + 1:end] = [eol] * len(blocks[name])
    ordered = [name for name in BLOCK_NAMES if name in changed]
    return Result(new_lines, new_eols, ordered, errors, warnings, summary, stale_days, origin)


def changed_blocks(lines, spans, blocks):
    """Names of the blocks whose generated lines differ from the lines in the file."""
    changed = []
    for name, (start, end) in spans.items():
        if lines[start + 1:end] != blocks[name]:
            changed.append(name)
    return changed


# ----------------------------------------------------------------------------------------------
# Command line

def parse_date(value):
    """argparse type for --today."""
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError('%r is not a YYYY-MM-DD date' % value)


def parse_days(value):
    """argparse type for --stale-days."""
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError('%r is not a whole number of days greater than 0' % value)
    return int(value)


def build_parser():
    """Define the command line."""
    parser = argparse.ArgumentParser(
        prog='refresh_reference.py',
        description='Regenerate the contents, cite index, subject index and health block of a '
                    'living-reference Markdown file.',
        epilog='Exit status: 0 refreshed or clean; 1 with --check when findings exist or a '
               'block is out of date; 2 usage error, unreadable file or structure error.')
    parser.add_argument('files', nargs='+', metavar='FILE.md')
    parser.add_argument('--check', action='store_true',
                        help='write nothing; exit 1 on findings or out-of-date blocks')
    parser.add_argument('--warnings-ok', action='store_true',
                        help='with --check: let warnings pass and fail on errors only')
    parser.add_argument('--stale-days', type=parse_days, metavar='N',
                        help='cadence in days; overrides the Stale-after line in the file '
                             '(default %d)' % DEFAULT_STALE_DAYS)
    parser.add_argument('--today', type=parse_date, metavar='YYYY-MM-DD',
                        help='use this date as today (for tests and reproducible runs)')
    parser.add_argument('--allow-missing-blocks', action='store_true',
                        help='accept a file that lacks 1 or more of the 4 marker pairs')
    return parser


def process_file(path, options, today):
    """Refresh or check one file and return its exit status."""
    try:
        source = read_source(path)
    except (OSError, UnicodeDecodeError) as error:
        print('%s: cannot read the file: %s' % (path, error), file=sys.stderr)
        return EXIT_ERROR
    try:
        result = refresh_lines(source.lines, source.eols, source.eol, today,
                               options.stale_days, options.allow_missing_blocks)
    except StructureError as error:
        print('%s: structure error; nothing was written' % path, file=sys.stderr)
        for message in error.messages:
            print('  - %s' % message, file=sys.stderr)
        return EXIT_ERROR
    print('%s: %s; cadence %d days (%s)'
          % (path, result.summary, result.stale_days, result.stale_origin))
    report_findings(result)
    if options.check:
        return report_check(result, options.warnings_ok)
    if not result.changed:
        print('  blocks: up to date; file not changed')
        return EXIT_OK
    data = join_lines(result.lines, result.eols).encode('utf-8')
    if source.bom:
        data = UTF8_BOM + data
    try:
        write_atomic(path, data)
    except OSError as error:
        print('%s: cannot write the file: %s' % (path, error), file=sys.stderr)
        return EXIT_ERROR
    print('  blocks updated: %s' % ', '.join(result.changed))
    return EXIT_OK


def report_findings(result):
    """Print every finding, errors first."""
    if result.errors:
        print('  errors: %d' % len(result.errors))
        for finding in result.errors:
            print('    - %s' % finding)
    if result.warnings:
        print('  warnings: %d' % len(result.warnings))
        for finding in result.warnings:
            print('    - %s' % finding)
    if not result.errors and not result.warnings:
        print('  findings: none')


def report_check(result, warnings_ok):
    """Print the --check verdict and return 0 or 1."""
    reasons = []
    if result.changed:
        reasons.append('out-of-date blocks: %s' % ', '.join(result.changed))
    if result.errors:
        reasons.append(plural(len(result.errors), 'error'))
    if result.warnings and not warnings_ok:
        reasons.append(plural(len(result.warnings), 'warning'))
    if reasons:
        print('  check: failed (%s); file not changed' % '; '.join(reasons))
        return EXIT_FINDINGS
    print('  check: passed; file not changed')
    return EXIT_OK


def use_utf8_output():
    """Print UTF-8 whatever the locale is, so that a section sign never crashes the run."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')


def main(argv=None):
    """Run the command line and return the highest exit status of all files."""
    use_utf8_output()
    options = build_parser().parse_args(argv)
    today = options.today or datetime.date.today()
    status = EXIT_OK
    for path in options.files:
        status = max(status, process_file(path, options, today))
    return status


if __name__ == '__main__':
    sys.exit(main())
