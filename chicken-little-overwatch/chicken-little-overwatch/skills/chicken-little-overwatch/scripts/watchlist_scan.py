#!/usr/bin/env python3
"""Watchlist scanner for the rules in references/one-way-optimal-language.md.

The scanner searches for words and patterns that the reference tells the
reviewer to inspect: lexicon words that carry more than one meaning, vague time
words, ambiguity triggers (R1-R30), look-alike medical words (R5), Joint
Commission "Do Not Use" items (R6), dose-format errors (R14), one space after a
sentence (Typography), and long sentences (S5). Every hit is a prompt to
decide, not a verdict.

Usage:  python3 watchlist_scan.py [--limit N] [--no-length] [--include-code]
                                  [--summary] [--fail] FILE [FILE ...]
        FILE may be "-" to read standard input.
Exit:   0  the scan ran (the scan informs; the reviewer decides)
        1  with --fail only: one or more hits
        2  the scanner could not read a file, or the command line is wrong

The scanner skips front matter, fenced code blocks, HTML comments, the text of
inline code spans, and URLs. --include-code scans the code blocks and the
inline code spans too. The sentence-length check joins the wrapped lines of one
paragraph or one list item, and it measures each table cell separately.

Standard library only. Runs on Python 3.8 or later.
"""
import argparse
import os
import re
import sys

WORDS = {
    "R1/lexicon": r"shall|should|consider|can|cannot|need to|needs to|is to|agrees to|is required to|is responsible for|will be expected to",
    "R9 and/or": r"and/or",
    "R28 slash": r"\b[A-Za-z]+/[A-Za-z]+\b",
    "R13 time": r"within|upon|until|by\s+(?:the\s+)?(?:end|close|date)|between|business day|periodically|daily|twice a day|at least",
    "R16 exceptions": r"provided that|notwithstanding|subject to|may\b[^.]{0,40}\bonly\b",
    "R7/R18 references": r"herein|said|such|the foregoing|the same|above|below",
    "R15 examples": r"such as|e\.g\.|i\.e\.|etc\.|including",
    "R21 respectively": r"respectively",
    "R27 earlier/later": r"whichever",
    "R10/R24 quantifiers": r"\bany\b|\beach\b|\ball\b|\bevery\b",
    "R12 negation": r"unless|not\s+\w+\s+unless|cannot|never|no\s+longer",
    "R25 notice": r"notice|notify",
    "R26 may require": r"may require|may ask",
    "Vague standard": r"sole discretion|satisfactory|acceptable to|good faith|best efforts|reasonable|appropriate|adequate|as clinically indicated|promptly|immediately|as soon as possible|right away|timely|regularly|frequently|significant|substantial|material|soon|normal|usual|as needed|as directed|PRN|mild|moderate|severe|very|extremely",
    "Please": r"please",
    "R17 possibility": r"likely|unlikely|rare|common|very common",
}
UNBOUNDED = ("R9 and/or", "R28 slash", "R16 exceptions")
LOOKALIKES = r"negative|positive|unremarkable|impressive|progressing|stable|occult|NPO|febrile|acute|chronic|discharge|culture|tolerate|compliance"
DO_NOT_USE = [
    ("R6 Do Not Use: U/IU after a number", r"\b\d+(?:\.\d+)?\s?(?:U|IU)\b"),
    ("R6 Do Not Use: QD/QOD", r"\b(?:Q\.D\.|QD|Q\.O\.D\.|QOD)\b"),
    ("R6 Do Not Use: MS/MSO4/MgSO4", r"\b(?:MS|MSO4|MgSO4)\b"),
    ("R14 trailing zero", r"\b\d+\.0\s?(?:mg|mcg|g|mL|units?)\b"),
    ("R14 missing leading zero", r"(?<![\d.])\.\d+\s?(?:mg|mcg|g|mL|units?)\b"),
]
ABBREVIATIONS = {"dr", "mr", "mrs", "ms", "prof", "st", "vs", "no", "u.s", "e.g", "i.e", "etc", "inc", "jr", "sr"}
ONE_SPACE = re.compile(r"(\S*)[.?!][\"\u201d\u2019)]? (?=[\"\u201c\u2018(]?[A-Z0-9])")
SENTENCE_BREAK = re.compile(r"(?<=[.?!])\s+(?=[A-Z0-9\"\u201c(])")
WORD = re.compile(r"[A-Za-z0-9'\u2019-]+")
COMMENT = re.compile(r"<!--.*?-->")
CODE_SPAN = re.compile(r"`[^`\n]+`")
URL = re.compile(r"\b(?:https?|ftp)://[^\s)>\]]+", re.I)
WORD_RX = [(label, re.compile(pattern if label in UNBOUNDED else r"\b(?:%s)\b" % pattern, re.I))
           for label, pattern in WORDS.items()]
LOOK_RX = re.compile(r"\b(?:%s)\b" % LOOKALIKES, re.I)
DNU_RX = [(label, re.compile(pattern)) for label, pattern in DO_NOT_USE]


# --- shared reader: this block is identical in av_scan.py and watchlist_scan.py ---
MARK = re.compile(r"<!--\s*(/?)av:(verbatim|mention)\s*-->")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
OWN_UNIT = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#{1,6}\s|>|\||<!--)")
NEVER_CONTINUED = re.compile(r"^\s*(?:#{1,6}\s|\|)")
MAX_BYTES = 20 * 1024 * 1024


class ReadError(Exception):
    """The scanner could not read a file."""


def read_source(path):
    """Return (text, notes) for one path. "-" means standard input."""
    if path == "-":
        data = sys.stdin.buffer.read()
    else:
        if os.path.isdir(path):
            raise ReadError("is a directory; name a file")
        try:
            if os.path.getsize(path) > MAX_BYTES:
                raise ReadError("is larger than %d bytes; split the file" % MAX_BYTES)
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError as error:
            raise ReadError(error.strerror or str(error))
    if len(data) > MAX_BYTES:
        raise ReadError("is larger than %d bytes; split the input" % MAX_BYTES)
    if b"\x00" in data:
        raise ReadError("holds a NUL byte, so it is not a text file")
    text = data.decode("utf-8-sig", errors="replace")
    notes = []
    if "�" in text:
        notes.append("the file holds bytes that are not valid UTF-8; the scan replaced each of them")
    return text.replace("\r\n", "\n").replace("\r", "\n"), notes


def pieces_of(text, include_code=False, use_markers=True):
    """Split text into pieces. Return (pieces, notes, faults).

    A piece is (line number, text, zone, continues). The zone is TEXT, VERBATIM
    or MENTION. `continues` is True when the piece continues the sentence flow
    of the piece before it (a wrapped line of one paragraph or one list item).
    A fault is a marker or a code fence that never closes: text after it has a
    zone or a skip that nobody closed, so the caller must not report a clean scan.
    """
    lines = text.split("\n")
    notes, faults, pieces = [], [], []
    first = 0
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                first = index + 1
                break
        else:
            notes.append("line 1 opens front matter that never closes; the scan covers the whole file")
    zone, zone_line = "TEXT", 0
    fence, fence_line = None, 0
    joinable = False
    for index in range(first, len(lines)):
        number, line = index + 1, lines[index]
        fence_match = FENCE.match(line)
        if fence is not None:
            if fence_match and fence_match.group(1)[0] == fence:
                fence = None
            joinable = False
            if not include_code:
                continue
            if fence_match:
                continue
        elif fence_match:
            fence, fence_line = fence_match.group(1)[0], number
            joinable = False
            continue
        if not line.strip():
            joinable = False
            continue
        markers = list(MARK.finditer(line))
        if markers and not use_markers:
            line, markers = MARK.sub(" ", line), []
        if not markers:
            continues = joinable and not OWN_UNIT.match(line)
            pieces.append((number, line, zone, continues))
            joinable = not NEVER_CONTINUED.match(line)
            continue
        position = 0
        for marker in markers:
            segment = line[position:marker.start()]
            if segment.strip():
                pieces.append((number, segment, zone, False))
            kind = marker.group(2).upper()
            if marker.group(1):
                if zone != kind:
                    notes.append("line %d: the closing av:%s marker matches no opening marker" % (number, kind.lower()))
                zone = "TEXT"
            else:
                if zone != "TEXT":
                    notes.append("line %d: an av:%s marker opens inside the av:%s zone from line %d"
                                 % (number, kind.lower(), zone.lower(), zone_line))
                zone, zone_line = kind, number
            position = marker.end()
        segment = line[position:]
        if segment.strip():
            pieces.append((number, segment, zone, False))
        joinable = False
    if zone != "TEXT":
        faults.append("the av:%s marker on line %d never closes" % (zone.lower(), zone_line))
    if fence is not None and not include_code:
        faults.append("the code fence on line %d never closes; the scan skipped every line after it" % fence_line)
    return pieces, notes, faults


def units_of(pieces):
    """Join pieces into units. A unit is (zone, text, starts); starts lists (offset, line number)."""
    units = []
    for number, text, zone, continues in pieces:
        if continues and units and units[-1][0] == zone:
            _zone, joined, starts = units[-1]
            starts.append((len(joined) + 1, number))
            units[-1] = (zone, joined + " " + text.strip(), starts)
        else:
            units.append((zone, text.strip(), [(0, number)]))
    return units


def line_at(starts, offset):
    """Return the line number that holds the character at offset."""
    line = starts[0][1]
    for start, number in starts:
        if start > offset:
            break
        line = number
    return line
# --- end of shared reader ---


def clean(text, include_code):
    """Remove what the scan must not read: comments, URLs, inline code, and Markdown emphasis marks."""
    text = URL.sub(" ", COMMENT.sub(" ", text))
    if not include_code:
        text = CODE_SPAN.sub(" ", text)
    return re.sub(r"[*_`]", "", text)


def sentences_of(text):
    """Yield (offset, sentence) for each sentence in text."""
    position = 0
    for match in SENTENCE_BREAK.finditer(text):
        yield position, text[position:match.start()]
        position = match.end()
    yield position, text[position:]


def hits_of(text, limit=25, check_length=True, include_code=False):
    """Return (hits, notes, faults). A hit is (line number, label, fragment)."""
    pieces, notes, faults = pieces_of(text, include_code, use_markers=False)
    hits = []
    for number, raw, _zone, _continues in pieces:
        if raw.lstrip().startswith("|---") or raw.lstrip().startswith("| ---"):
            continue
        line = clean(raw, include_code)
        for label, rx in WORD_RX:
            for match in rx.finditer(line):
                hits.append((number, label, match.group(0)))
        for match in LOOK_RX.finditer(line):
            hits.append((number, "R5 look-alike word", match.group(0)))
        for label, rx in DNU_RX:
            for match in rx.finditer(line):
                hits.append((number, label, match.group(0)))
        for match in ONE_SPACE.finditer(line):
            if match.group(1).lower().strip("\"\u201c(") in ABBREVIATIONS:
                continue
            context = line[max(0, match.start() - 12): match.end() + 6]
            hits.append((number, "Typography: one space after sentence", context.strip()))
    if check_length:
        cleaned = [(number, clean(raw, include_code), zone, continues) for number, raw, zone, continues in pieces]
        for _zone, joined, starts in units_of(cleaned):
            if joined.startswith("|"):
                cells, position = [], 0
                for cell in joined.split("|"):
                    cells.append((position, cell))
                    position += len(cell) + 1
            else:
                cells = [(0, joined)]
            for base, cell in cells:
                for offset, sentence in sentences_of(cell):
                    words = len(WORD.findall(sentence))
                    if words > limit:
                        hits.append((line_at(starts, base + offset), "S5 length %d > %d" % (words, limit),
                                     sentence.strip()[:60] + "..."))
    return sorted(hits), notes, faults


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("files", nargs="+", help='files to scan; "-" reads standard input')
    parser.add_argument("--limit", type=int, default=25,
                        help="sentence word limit (S5); use 15 for patient instructions")
    parser.add_argument("--no-length", action="store_true", help="skip the sentence-length check")
    parser.add_argument("--include-code", action="store_true",
                        help="scan fenced code blocks and inline code spans too")
    parser.add_argument("--summary", action="store_true", help="print the number of hits for each label")
    parser.add_argument("--fail", action="store_true", help="exit 1 when any hit appears")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be 1 or more")
    total = unreadable = 0
    counts = {}
    for path in args.files:
        try:
            text, notes = read_source(path)
        except ReadError as error:
            print("%s: ERROR: %s" % (path, error), file=sys.stderr)
            unreadable += 1
            continue
        hits, more_notes, faults = hits_of(text, args.limit, not args.no_length, args.include_code)
        for note in notes + more_notes + faults:
            print("%s: NOTE: %s" % (path, note), file=sys.stderr)
        for number, label, fragment in hits:
            print("%s:%d: [%s] %s" % (path, number, label, fragment))
            total += 1
            key = "S5 length" if label.startswith("S5 length") else label
            counts[key] = counts.get(key, 0) + 1
    if args.summary:
        for label in sorted(counts):
            print("%6d  %s" % (counts[label], label), file=sys.stderr)
    print("hits=%d unreadable=%d" % (total, unreadable), file=sys.stderr)
    if unreadable:
        return 2
    return 1 if (args.fail and total) else 0


if __name__ == "__main__":
    sys.exit(main())
