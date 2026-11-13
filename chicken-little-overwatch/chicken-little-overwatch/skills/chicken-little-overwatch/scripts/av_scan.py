#!/usr/bin/env python3
"""Fallback active-voice scanner.

The pattern set (P, NOT, ADV, DET, PATTERNS) comes verbatim from the fallback
scan in references/one-way-optimal-language.md. This wrapper adds a command
line, Markdown handling, zone markers, a scan across wrapped lines, and error
handling. The scanner flags more than it needs to, on purpose. Decide each hit
with the reference's Active Voice Step 2 (Decide). The eye check stays
mandatory: no scanner catches every reduced clause, heading fragment or
question.

Usage:  python3 av_scan.py [--strict] [--ignore-markers] [--include-code] FILE [FILE ...]
        FILE may be "-" to read standard input.
Exit:   0  no blocking hit
        1  one or more blocking hits, or a marker or code fence that never closes
        2  the scanner could not read a file, or the command line is wrong
Marker: <!-- av:verbatim --> ... <!-- /av:verbatim -->  (text that a law requires word for word)
        <!-- av:mention -->  ... <!-- /av:mention -->   (deliberate "before" examples)
        A marker may share a line with text. The scanner prints every hit inside
        a zone with the label VERBATIM or MENTION; it never hides one.
        --strict           counts MENTION hits as blocking
        --ignore-markers   treats every marker as absent; use it on a file whose
                           markers you did not write yourself

Standard library only. Runs on Python 3.8 or later.
"""
import argparse
import os
import re
import sys

P = (r"(?:\w{2,}ed|cut|put|set|read|hit|shut|hurt|spread|cast|shed|upset|run|overcome|done|given|taken|"
     r"mistaken|shaken|made|seen|written|known|shown|grown|thrown|blown|drawn|withdrawn|sworn|torn|worn|"
     r"born|found|told|held|withheld|kept|left|built|brought|bought|caught|taught|thought|sought|sent|"
     r"spent|meant|dealt|felt|led|misled|fed|bred|lit|met|paid|laid|said|sold|driven|hidden|broken|"
     r"chosen|frozen|spoken|stolen|forgotten|begun|struck|stuck|understood|beaten|bitten|eaten|forbidden|"
     r"ridden|proven|swollen|bound|lost|shot|heard|dug|hung|won)")
NOT = r"(?!(?:need|bed|red|seed|feed|speed|bleed|breed|proceed|exceed|succeed|hundred|sacred|naked|wicked)\b)"
ADV = r"(?:\s+(?:\w+ly|not|n't|also|only|then|often|usually|always|never|already|still|just|all|last|first|now|again|been|being|be))*"
DET = r"(?:the|a|an|your|my|his|her|its|our|their|this|that|these|those|each|every|any)"
PATTERNS = [
    ("be/get/stay + participle", rf"\b(?:am|is|are|was|were|be|been|being|'s|'re|isn't|aren't|wasn't|weren't|get|gets|got|gotten|getting|remains?|remained|stays?|stayed|seems?|seemed|looks?|looked|feels?|felt|appears?|appeared|becomes?|became){ADV}\s+{NOT}{P}\b"),
    ("question: be ... participle", rf"(?:^|[.?!]\s+)(?:(?:what|where|how|why|which|who|when)\s+)?(?:is|are|was|were|isn't|aren't|wasn't|weren't)\s+(?:\w+\s+){{1,4}}?{NOT}{P}\b[^.]*\?"),
    ("have/get/keep + object + participle", rf"\b(?:have|has|had|having|get|gets|got|keep|keeps|kept|leave|want|wants|need|needs|make|makes|find)\s+{DET}\s+(?:\w+\s+){{1,2}}?{NOT}{P}\b"),
    ("elliptical: if/when/as/once + participle", rf"\b(?:if|when|once|unless|until|as|while|although|though|where|than)(?:\s+(?:\w+ly|not|otherwise))*\s+{NOT}{P}\b"),
    ("sentence-initial participle", rf"(?:^|[.;:!?]\s+|,\s+)(?:not\s+(?:to\s+be\s+)?)?{NOT}{P}\b(?=\s*(?:,|\b(?:by|for|in|on|with|to|at|after|before|from|under|during)\b))"),
    ("need + -ing", r"\b(?:need|needs|needed|want|wants|require|requires)\s+(?!(?:nothing|something|anything|everything|bedding|clothing|counseling|training|nursing|screening)\b)\w{2,}ing\b"),
    ("noun + participle + by/prep", rf"\b(?!(?:i|you|we|he|she|it|they|who|which|that|the|a|an|to|and|or|have|has|had|be|is|are|was|were)\b)\w+\s+(?:not\s+)?{NOT}{P}\s+(?:by|in|on|at|after|before|for|from|with|during|under|into|through|late|early)\b"),
    ("thing + participle", rf"\b(?:anything|something|everything|nothing)\s+{NOT}{P}\b"),
    ("participle at end after object", rf"\b{DET}\s+\w+\s+{NOT}{P}\s*[.,;:)]"),
]
COMPILED = [(name, re.compile(p, re.I)) for name, p in PATTERNS]


def normalise(text):
    """Replace the 3 characters that the reference replaces. Each replacement keeps the length."""
    return text.replace("’", "'").replace("*", " ").replace("`", " ")


def scan_spans(text):
    """Return (pattern name, start, end, fragment) for every match in text."""
    text = normalise(text)
    return [(name, m.start(), m.end(), m.group(0)) for name, rx in COMPILED for m in rx.finditer(text)]


def scan(text):
    """Return (pattern name, fragment) for every match in text, as the reference's scan does."""
    return [(name, fragment.strip()) for name, _start, _end, fragment in scan_spans(text)]


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


def hits_of(text, include_code=False, use_markers=True):
    """Return (hits, notes, faults). A hit is (line number, zone, pattern name, fragment)."""
    pieces, notes, faults = pieces_of(text, include_code, use_markers)
    hits = []
    for number, piece, zone, _continues in pieces:
        for name, fragment in scan(piece):
            hits.append((number, zone, name, fragment))
    for zone, joined, starts in units_of(pieces):
        if len(starts) < 2:
            continue
        for name, start, end, fragment in scan_spans(joined):
            lead = len(fragment) - len(fragment.lstrip())
            first_line = line_at(starts, start + lead)
            last_line = line_at(starts, max(start + lead, end - 1))
            if first_line != last_line:
                hits.append((first_line, zone, name + " (across lines)", fragment.strip()))
    hits.sort(key=lambda hit: (hit[0], hit[2], hit[3]))
    return hits, notes, faults


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("files", nargs="+", help='files to scan; "-" reads standard input')
    parser.add_argument("--strict", action="store_true",
                        help="count hits inside av:mention zones as blocking")
    parser.add_argument("--ignore-markers", action="store_true",
                        help="treat every av marker as absent")
    parser.add_argument("--include-code", action="store_true",
                        help="scan the text inside fenced code blocks too")
    args = parser.parse_args(argv)
    blocking = verbatim = mention = fault_count = unreadable = 0
    for path in args.files:
        try:
            text, notes = read_source(path)
        except ReadError as error:
            print("%s: ERROR: %s" % (path, error), file=sys.stderr)
            unreadable += 1
            continue
        hits, more_notes, faults = hits_of(text, args.include_code, not args.ignore_markers)
        for note in notes + more_notes:
            print("%s: NOTE: %s" % (path, note), file=sys.stderr)
        for fault in faults:
            print("%s: FAULT: %s" % (path, fault))
            fault_count += 1
        for number, zone, name, fragment in hits:
            label = {"TEXT": "HIT", "VERBATIM": "VERBATIM", "MENTION": "MENTION"}[zone]
            print("%s:%d: [%s:%s] %s" % (path, number, label, name, fragment))
            if zone == "VERBATIM":
                verbatim += 1
            elif zone == "MENTION":
                mention += 1
                if args.strict:
                    blocking += 1
            else:
                blocking += 1
    print("blocking=%d verbatim=%d mention=%d faults=%d unreadable=%d"
          % (blocking, verbatim, mention, fault_count, unreadable), file=sys.stderr)
    if unreadable:
        return 2
    return 1 if (blocking or fault_count) else 0


if __name__ == "__main__":
    sys.exit(main())
