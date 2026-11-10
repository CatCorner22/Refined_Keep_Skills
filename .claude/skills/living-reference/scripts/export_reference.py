#!/usr/bin/env python3
"""Export a living-reference Markdown file to DOCX, HTML or PDF with pandoc.

Usage:
    export_reference.py FILE.md [--to docx|html|pdf] [--out PATH] [--force] [--strict]
                        [--allow-raw-html] [--pdf-engine NAME]
                        [--stale-days N] [--today YYYY-MM-DD]

The script never changes FILE.md. It regenerates the four blocks in memory, removes
the block markers and the index tags outside code, and gives the text to pandoc as
GitHub-flavoured Markdown (-f gfm).

Exit status:
    0  the export file is written
    1  --strict only: the health block has findings, so nothing is exported
    2  usage error, unreadable file, structure error, existing output without --force,
       missing pandoc or PDF engine, or a pandoc failure

Needs pandoc on PATH (or the pypandoc_binary package, which bundles pandoc).
PDF output also needs a pandoc PDF engine such as pdflatex, xelatex, typst,
weasyprint or wkhtmltopdf.
"""
import argparse
import datetime
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import refresh_reference as refresh  # noqa: E402  (the path line above must run first)

FORMATS = ('docx', 'html', 'pdf')
PDF_ENGINES = ('pdflatex', 'xelatex', 'lualatex', 'tectonic', 'typst', 'weasyprint',
               'wkhtmltopdf')
DEFAULT_FILE_MODE = 0o666

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

# Pandoc filter: drop raw HTML and links that run script. A reader extension is
# not enough, because pandoc still passes a script element through.
SAFE_HTML_FILTER = """\
local function unsafe(target)
  local compact = target:lower():gsub('%s', '')
  return compact:match('^javascript:') or compact:match('^vbscript:') or compact:match('^data:')
end
function RawInline(el)
  if el.format:match('html') then return {} end
end
function RawBlock(el)
  if el.format:match('html') then return {} end
end
function Link(el)
  if unsafe(el.target) then return el.content end
end
"""


class ExportError(Exception):
    """The export cannot run; the message tells the user what to change."""


def build_parser():
    """Define the command line."""
    parser = argparse.ArgumentParser(
        prog='export_reference.py',
        description='Export a living reference to DOCX, HTML or PDF. The source file is '
                    'never changed.',
        epilog='Exit status: 0 exported; 1 with --strict when findings exist; 2 any error. '
               'PDF needs a pandoc PDF engine (%s).' % ', '.join(PDF_ENGINES))
    parser.add_argument('file', metavar='FILE.md')
    parser.add_argument('--to', choices=FORMATS, default='docx', help='output format')
    parser.add_argument('--out', metavar='PATH',
                        help='output file (default: FILE with the new extension)')
    parser.add_argument('--force', action='store_true',
                        help='replace an existing output file')
    parser.add_argument('--strict', action='store_true',
                        help='refuse to export while the health block has findings')
    parser.add_argument('--allow-raw-html', action='store_true',
                        help='keep raw HTML and script links from the source in the export')
    parser.add_argument('--pdf-engine', metavar='NAME',
                        help='pandoc PDF engine to use (default: the first one found on PATH)')
    parser.add_argument('--stale-days', type=refresh.parse_days, metavar='N',
                        help='cadence in days; overrides the Stale-after line in the file')
    parser.add_argument('--today', type=refresh.parse_date, metavar='YYYY-MM-DD',
                        help='use this date as today')
    return parser


def output_path(options):
    """Choose the output file and refuse a path that would destroy something."""
    source = options.file
    out = options.out or os.path.splitext(source)[0] + '.' + options.to
    if os.path.realpath(out) == os.path.realpath(source):
        raise ExportError('the output path is the source file; choose another --out path')
    directory = os.path.dirname(os.path.abspath(out))
    if not os.path.isdir(directory):
        raise ExportError('the output directory does not exist: %s' % directory)
    if os.path.isdir(out):
        raise ExportError('the output path is a directory: %s' % out)
    if os.path.exists(out) and not options.force:
        raise ExportError('%s exists; pass --force to replace it' % out)
    return out


def find_pandoc():
    """Return the pandoc program: the one on PATH, or the one that pypandoc bundles."""
    found = shutil.which('pandoc')
    if found:
        return found
    try:
        import pypandoc
        return pypandoc.get_pandoc_path()
    except (ImportError, OSError, RuntimeError):
        raise ExportError('pandoc not found; install pandoc, or run '
                          '"pip install pypandoc_binary"')


def find_pdf_engine(requested, which=shutil.which):
    """Return a PDF engine that exists on this machine, or explain what is missing."""
    if requested:
        if which(requested):
            return requested
        raise ExportError('PDF engine "%s" is not on PATH' % requested)
    for engine in PDF_ENGINES:
        if which(engine):
            return engine
    raise ExportError('PDF export needs a pandoc PDF engine and none of these is on PATH: %s. '
                      'Install one, or export with --to docx or --to html'
                      % ', '.join(PDF_ENGINES))


def strip_tags(line, comments):
    """Rebuild a line without index tags; inline code stays untouched."""
    def drop_index_tag(match):
        if refresh.INDEX_PREFIX.match(match.group(1)):
            return ''
        return match.group(0)
    parts = []
    for kind, text, number in line.segments:
        if kind == refresh.TEXT:
            parts.append(refresh.BRACE_TAG.sub(drop_index_tag, text))
        elif kind == refresh.CODE:
            parts.append(text)
        elif not refresh.is_index_comment(refresh.comment_body(comments, number)):
            parts.append(text)
    return ''.join(parts)


def export_markdown(lines):
    """Return the text for pandoc: no block markers and no index tags outside code."""
    scanned, comments, _ = refresh.scan_lines(lines)
    kept = []
    for raw, line in zip(lines, scanned):
        if line.is_fence:
            kept.append(raw)
            continue
        if refresh.marker_of(line, comments) is not None:
            continue
        rebuilt = strip_tags(line, comments)
        if raw.strip() and not rebuilt.strip():
            continue
        kept.append(rebuilt)
    return '\n'.join(kept)


def page_title(lines, fallback):
    """Take the title from the first level-1 heading outside code, without its [ID]."""
    scanned, _, _ = refresh.scan_lines(lines)
    for line in scanned:
        if line.is_fence:
            continue
        heading = refresh.parse_heading(refresh.text_without_comments(line))
        if heading is None or heading[0] != 1 or not heading[1]:
            continue
        parsed = refresh.split_heading_id(heading[1])
        if parsed is not None:
            return parsed[1]
        return heading[1]
    return fallback


def run_pandoc(pandoc, markdown, title, options, out):
    """Convert in a temporary file next to the output, then move it into place."""
    directory = os.path.dirname(os.path.abspath(out))
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix='.export-',
                                             suffix='.' + options.to)
    os.close(descriptor)
    work = tempfile.mkdtemp(prefix='living-reference-')
    try:
        command = [pandoc, '-f', 'gfm', '-o', temporary, '--metadata', 'pagetitle=' + title]
        if options.to == 'pdf':
            command.append('--pdf-engine=' + find_pdf_engine(options.pdf_engine))
        else:
            command.extend(['-t', options.to])
        if options.to == 'html':
            command.append('--standalone')
        if not options.allow_raw_html:
            filter_path = os.path.join(work, 'safe-html.lua')
            with open(filter_path, 'w', encoding='utf-8') as handle:
                handle.write(SAFE_HTML_FILTER)
            command.extend(['--lua-filter', filter_path])
        done = subprocess.run(command, input=markdown.encode('utf-8'),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if done.returncode != 0:
            detail = done.stderr.decode('utf-8', 'replace').strip()
            raise ExportError('pandoc failed (status %d): %s' % (done.returncode, detail))
        mask = os.umask(0)
        os.umask(mask)
        os.chmod(temporary, DEFAULT_FILE_MODE & ~mask)
        os.replace(temporary, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if os.path.exists(temporary):
            os.unlink(temporary)


def report_findings(path, result):
    """Print the health findings on stderr, so that an export never hides them."""
    if not result.errors and not result.warnings:
        return
    print('%s: the health block has %s and %s; the export includes them'
          % (path, refresh.plural(len(result.errors), 'error'),
             refresh.plural(len(result.warnings), 'warning')), file=sys.stderr)
    for finding in result.errors:
        print('  - Error: %s' % finding, file=sys.stderr)
    for finding in result.warnings:
        print('  - Warning: %s' % finding, file=sys.stderr)


def export(options):
    """Run one export and return the exit status."""
    out = output_path(options)
    try:
        source = refresh.read_source(options.file)
    except (OSError, UnicodeDecodeError) as error:
        raise ExportError('cannot read %s: %s' % (options.file, error))
    today = options.today or datetime.date.today()
    try:
        result = refresh.refresh_lines(source.lines, source.eols, source.eol, today,
                                       options.stale_days, allow_missing_blocks=True)
    except refresh.StructureError as error:
        raise ExportError('structure error in %s: %s' % (options.file, '; '.join(error.messages)))
    report_findings(options.file, result)
    if options.strict and (result.errors or result.warnings):
        print('%s: not exported, because --strict is set' % options.file, file=sys.stderr)
        return EXIT_FINDINGS
    pandoc = find_pandoc()
    fallback = os.path.splitext(os.path.basename(options.file))[0]
    title = page_title(result.lines, fallback)
    run_pandoc(pandoc, export_markdown(result.lines), title, options, out)
    print(out)
    return EXIT_OK


def main(argv=None):
    """Run the command line."""
    refresh.use_utf8_output()
    options = build_parser().parse_args(argv)
    try:
        return export(options)
    except ExportError as error:
        print('export_reference.py: %s' % error, file=sys.stderr)
        return EXIT_ERROR


if __name__ == '__main__':
    sys.exit(main())
