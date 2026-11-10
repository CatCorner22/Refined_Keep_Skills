"""Tests for the living-reference skill: refresh_reference.py, export_reference.py and the shipped files.

Each test reproduces a defect of the original scripts (review items LR-01 to LR-27 and
CW-26-V) and proves the corrected behaviour. No test depends on today's date: every
run passes --today. Every file is written inside a temporary directory.
"""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.normpath(os.path.join(HERE, '..', '.claude', 'skills', 'living-reference'))
REFRESH = os.path.join(SKILL, 'scripts', 'refresh_reference.py')
EXPORT = os.path.join(SKILL, 'scripts', 'export_reference.py')
TEMPLATE = os.path.join(SKILL, 'templates', 'living-reference.template.md')
EXAMPLE = os.path.join(SKILL, 'examples', 'claude-code-instructions.reference.md')
TODAY = '2026-11-10'
PANDOC = shutil.which('pandoc')
RUN_TIMEOUT = 120

DEFAULT_RULES = """\
### [10.01] Rule one is a full sentence

<!-- index: alpha | first alias -->

- **Rule.** Something true. [S1 at 4]
- Last verified: 2026-11-01
"""

DEFAULT_SOURCES = (
    '- [S1] Author, *Title*, Publisher (2025). https://example.org/a. '
    'Accessed 2026-11-01. Grade: A.\n')

BLOCKS = """\
## [91] Cite index

<!-- authorities:start -->
<!-- authorities:end -->

## [92] Index

<!-- index:start -->
<!-- index:end -->

## [99] Health

<!-- health:start -->
<!-- health:end -->
"""


def make_doc(rules=DEFAULT_RULES, sources=DEFAULT_SOURCES, header='Stale-after: 90',
             toc='<!-- toc:start -->\n<!-- toc:end -->\n', blocks=BLOCKS):
    """Build a small living reference; each argument replaces one part."""
    return ('# [00] Test: living reference\n\n' + header + '\n\n'
            '## [02] Contents\n\n' + toc + '\n'
            '## [10] Topic A\n\n' + rules + '\n'
            '## [90] Sources\n\n' + sources + '\n' + blocks)


def rule(section_id, title, body, verified='2026-11-01'):
    """Build one rule section."""
    text = '### [%s] %s\n\n%s\n' % (section_id, title, body)
    if verified:
        text += '- Last verified: %s\n' % verified
    return text + '\n'


def run_script(script, args, env=None):
    """Run a script and return (status, stdout, stderr) as text."""
    done = subprocess.run([sys.executable, script] + list(args), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env, timeout=RUN_TIMEOUT)
    return (done.returncode, done.stdout.decode('utf-8', 'replace'),
            done.stderr.decode('utf-8', 'replace'))


def load_module(path, name):
    """Import a script as a module without writing a __pycache__ directory."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Base(unittest.TestCase):
    """Gives each test its own temporary directory and short helpers."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='living-reference-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, text, name='ref.md', newline='\n', bom=False):
        path = os.path.join(self.tmp, name)
        data = text.replace('\n', newline).encode('utf-8')
        with open(path, 'wb') as handle:
            handle.write((b'\xef\xbb\xbf' if bom else b'') + data)
        return path

    def read_bytes(self, path):
        with open(path, 'rb') as handle:
            return handle.read()

    def read(self, path):
        return self.read_bytes(path).decode('utf-8')

    def refresh(self, path, *args, **kwargs):
        today = kwargs.pop('today', TODAY)
        return run_script(REFRESH, [path, '--today', today] + list(args), **kwargs)

    def check(self, path, *args, **kwargs):
        return self.refresh(path, '--check', *args, **kwargs)

    def findings(self, text, *args):
        """Write a document, run --check, and return (status, stdout)."""
        path = self.write(text)
        status, out, err = self.check(path, *args)
        self.assertIn(status, (0, 1), err)
        return status, out

    def block(self, path, name):
        text = self.read(path).replace('\r\n', '\n')
        start = text.index('<!-- %s:start -->\n' % name) + len('<!-- %s:start -->\n' % name)
        return text[start:text.index('<!-- %s:end -->' % name)]

    def export(self, path, *args, **kwargs):
        return run_script(EXPORT, [path, '--today', TODAY] + list(args), **kwargs)


class MarkerSafety(Base):
    """LR-01: marker handling must never delete content."""

    def assert_refused(self, text, fragment):
        path = self.write(text)
        before = self.read_bytes(path)
        for extra in ([], ['--check']):
            status, out, err = self.refresh(path, *extra)
            self.assertEqual(status, 2, out + err)
            self.assertIn(fragment, err)
            self.assertIn('nothing was written', err)
            self.assertEqual(self.read_bytes(path), before)

    def test_misplaced_end_marker_is_refused_and_content_survives(self):
        text = make_doc(toc='<!-- toc:start -->\n- [old](#old)\n')
        text = text.replace('## [90] Sources', '<!-- toc:end -->\n\n## [90] Sources')
        self.assertIn('Something true.', text)
        self.assert_refused(text, 'a heading sits inside the block')

    def test_missing_end_marker_is_refused(self):
        self.assert_refused(make_doc(toc='<!-- toc:start -->\n'), 'block "toc" needs exactly 1')

    def test_end_marker_above_start_marker_is_refused(self):
        self.assert_refused(make_doc(toc='<!-- toc:end -->\n<!-- toc:start -->\n'),
                            'is above the start marker')

    def test_duplicate_start_marker_is_refused(self):
        self.assert_refused(make_doc(toc='<!-- toc:start -->\n<!-- toc:start -->\n<!-- toc:end -->\n'),
                            'needs exactly 1 start marker')

    def test_missing_block_is_refused_unless_allowed(self):
        text = make_doc(toc='')
        self.assert_refused(text, 'block "toc" is missing')
        path = self.write(text)
        status, out, err = self.refresh(path, '--allow-missing-blocks')
        self.assertEqual(status, 0, err)
        self.assertIn('- [S1] Author', self.block(path, 'authorities'))

    def test_markers_inside_a_code_fence_are_ignored(self):
        example = ('### [10.02] The health block is generated\n\n```html\n<!-- health:start -->\n'
                   '<!-- health:end -->\n```\n\n- **Rule.** Do not edit it. [S1]\n'
                   '- Last verified: 2026-11-01\n')
        path = self.write(make_doc(rules=DEFAULT_RULES + '\n' + example))
        status, out, err = self.refresh(path)
        self.assertEqual(status, 0, err)
        text = self.read(path)
        self.assertIn('```html\n<!-- health:start -->\n<!-- health:end -->\n```', text)
        self.assertIn('- No findings.', text.split('## [99] Health')[1])

    def test_unknown_marker_names_do_not_hide_the_source_list(self):
        sources = '<!-- sources:start -->\n' + DEFAULT_SOURCES + '<!-- sources:end -->\n'
        status, out = self.findings(make_doc(sources=sources))
        self.assertIn('1 source,', out)
        self.assertNotIn('not in the source list', out)


class CheckIsAGate(Base):
    """LR-02: --check never writes, and each exit status has one meaning."""

    def test_check_never_writes_and_reports_out_of_date_blocks(self):
        path = self.write(make_doc())
        before = self.read_bytes(path)
        status, out, err = self.check(path)
        self.assertEqual(status, 1)
        self.assertIn('out-of-date blocks', out)
        self.assertEqual(self.read_bytes(path), before)
        self.assertEqual(self.refresh(path)[0], 0)
        status, out, err = self.check(path)
        self.assertEqual(status, 0, out)
        self.assertIn('check: passed', out)
        text = self.read(path).replace('- **Rule.** Something true. [S1 at 4]',
                                       '- **Rule.** Something true. [S1 at 4]\n\n'
                                       '### [10.02] A new rule\n\n- **Rule.** New. [S1]\n'
                                       '- Last verified: 2026-11-01')
        path = self.write(text)
        before = self.read_bytes(path)
        status, out, err = self.check(path)
        self.assertEqual(status, 1)
        self.assertIn('out-of-date blocks: toc', out)
        self.assertEqual(self.read_bytes(path), before)

    def test_findings_exit_1_and_warnings_ok_lets_warnings_pass(self):
        path = self.write(make_doc(sources=DEFAULT_SOURCES + '- [S2] Unused, *Book* (2020).\n'))
        self.assertEqual(self.refresh(path)[0], 0)
        status, out, err = self.check(path)
        self.assertEqual(status, 1)
        self.assertIn('source [S2] is not cited', out)
        self.assertEqual(self.check(path, '--warnings-ok')[0], 0)

    def test_errors_fail_even_with_warnings_ok(self):
        path = self.write(make_doc(rules=rule('10.01', 'Rule', '- **Rule.** X. [S9]')))
        self.refresh(path)
        self.assertEqual(self.check(path, '--warnings-ok')[0], 1)

    def test_usage_and_io_errors_exit_2(self):
        path = self.write(make_doc())
        self.assertEqual(run_script(REFRESH, [os.path.join(self.tmp, 'missing.md'), '--check'])[0], 2)
        self.assertEqual(run_script(REFRESH, [path, '--chek'])[0], 2)
        self.assertEqual(run_script(REFRESH, [path, '-check'])[0], 2)
        self.assertEqual(run_script(REFRESH, [path, '--stale-days'])[0], 2)
        self.assertEqual(run_script(REFRESH, [path, '--stale-days', 'abc'])[0], 2)
        self.assertEqual(run_script(REFRESH, [path, '--stale-days', '-5'])[0], 2)
        self.assertEqual(run_script(REFRESH, [path, '--today', '2026-13-45'])[0], 2)
        self.assertEqual(run_script(REFRESH, [])[0], 2)
        self.assertEqual(run_script(REFRESH, ['--help'])[0], 0)

    def test_non_utf8_file_exits_2(self):
        path = os.path.join(self.tmp, 'latin.md')
        with open(path, 'wb') as handle:
            handle.write(b'# [00] Caf\xe9\n')
        status, out, err = self.check(path)
        self.assertEqual(status, 2)
        self.assertIn('cannot read', err)

    def test_stale_days_accepts_the_equals_form(self):
        path = self.write(make_doc())
        status, out, err = self.check(path, '--stale-days=5')
        self.assertIn('older than the 5-day cadence', out)
        status, out, err = self.check(path, '--stale-days', '5')
        self.assertIn('older than the 5-day cadence', out)

    def test_flags_before_files_and_several_files(self):
        one = self.write(make_doc(), 'one.md')
        two = self.write(make_doc(), 'two.md')
        status, out, err = run_script(REFRESH, ['--today', TODAY, one, two])
        self.assertEqual(status, 0, err)
        for path in (one, two):
            self.assertIn('No findings', self.block(path, 'health'))
        self.assertEqual(run_script(REFRESH, ['--check', '--today', TODAY, one, two])[0], 0)
        broken = self.write(make_doc(toc='<!-- toc:start -->\n'), 'broken.md')
        self.assertEqual(run_script(REFRESH, ['--check', '--today', TODAY, one, broken])[0], 2)

    def test_file_that_is_not_a_living_reference_exits_2(self):
        empty = self.write('', 'empty.md')
        self.assertEqual(self.check(empty)[0], 2)
        readme = self.write('# Project\n\nSee [S1] and §9.\n', 'readme.md')
        status, out, err = self.check(readme, '--allow-missing-blocks')
        self.assertEqual(status, 2)
        self.assertIn('not a living reference', err)

    def test_file_name_with_a_leading_hyphen(self):
        path = self.write(make_doc(), '-notes.md')
        status, out, err = run_script(REFRESH, ['--today', TODAY, '--', path])
        self.assertEqual(status, 0, err)


class Headings(Base):
    """LR-05: a heading that deviates from the shape is reported, not skipped."""

    def test_headings_without_a_valid_id_are_errors(self):
        rules = DEFAULT_RULES + (
            '\n### Rule without an ID\n\n- Last verified: 2019-01-01\n'
            '\n### [10.02]\n\n### [10.03]Missing space is accepted\n\n- **Rule.** R. [S1]\n'
            '- Last verified: 2026-11-01\n'
            '\n### [ 10.05 ] Spaces inside the brackets\n\n### 10.06 ID without brackets\n'
            '\n### [2] Single digit\n')
        status, out = self.findings(make_doc(rules=rules))
        self.assertEqual(status, 1)
        for fragment in ('"Rule without an ID"', '"[10.02]"', '"[ 10.05 ] Spaces inside the brackets"',
                         '"10.06 ID without brackets"', '"[2] Single digit"'):
            self.assertIn('heading has no valid [ID] and title (' + fragment, out)
        self.assertNotIn('Missing space is accepted")', out)

    def test_leading_space_and_closing_hashes(self):
        rules = (' ### [10.01] One leading space\n\n- **Rule.** R. [S1]\n- Last verified: 2026-11-01\n'
                 '\n### [10.02] Closed heading ###\n\n- **Rule.** R. [S1]\n- Last verified: 2026-11-01\n')
        path = self.write(make_doc(rules=rules))
        self.assertEqual(self.refresh(path)[0], 0)
        toc = self.block(path, 'toc')
        self.assertIn('[10.01 One leading space](#1001-one-leading-space)', toc)
        self.assertIn('[10.02 Closed heading](#1002-closed-heading)', toc)

    def test_duplicate_section_id_is_an_error(self):
        rules = DEFAULT_RULES + '\n' + DEFAULT_RULES
        status, out = self.findings(make_doc(rules=rules))
        self.assertIn('section ID [10.01] is used 2 times', out)


class CodeAndComments(Base):
    """LR-06: text inside code and comments is never live content."""

    FENCED = ('### [77.01] Heading in example\n{{index: fenced term | fenced alias}}\n'
              '**Rule.** x [S55 at 3] see §88.88 [cite needed]\n- [S66] Fake source line.\n'
              'Last verified: 2001-01-01')

    def variants(self):
        return [
            '```markdown\n%s\n```' % self.FENCED,
            '~~~\n%s\n~~~' % self.FENCED,
            '  ```\n%s\n  ```' % self.FENCED.replace('\n', '\n  '),
            '````\n```\n%s\n```\n````' % self.FENCED,
            '- item\n\n    ```\n    %s\n    ```' % self.FENCED.replace('\n', '\n    '),
        ]

    def test_fenced_examples_are_not_content(self):
        for number, fence in enumerate(self.variants()):
            body = '%s\n\n- **Rule.** Real. [S1]' % fence
            path = self.write(make_doc(rules=rule('10.01', 'Real rule', body)), 'f%d.md' % number)
            status, out, err = self.refresh(path)
            self.assertEqual(status, 0, err)
            self.assertIn('findings: none', out, fence)
            self.assertNotIn('77.01', self.block(path, 'toc'))
            self.assertNotIn('S66', self.block(path, 'authorities'))
            self.assertNotIn('fenced', self.block(path, 'index'))

    def test_last_verified_inside_a_fence_does_not_count(self):
        body = '```\nLast verified: 2026-11-01\n```\n\n- **Rule.** Real. [S1]'
        status, out = self.findings(make_doc(rules=rule('10.01', 'Real rule', body, verified=None)))
        self.assertIn('§10.01: no Last verified line', out)

    def test_unclosed_fence_is_a_structure_error(self):
        body = '```bash\necho never closed\n\n- **Rule.** Real. [S1]'
        path = self.write(make_doc(rules=rule('10.01', 'Real rule', body)))
        before = self.read_bytes(path)
        status, out, err = self.refresh(path)
        self.assertEqual(status, 2)
        self.assertIn('code fence that opens here never closes', err)
        self.assertEqual(self.read_bytes(path), before)

    def test_unclosed_comment_is_a_structure_error(self):
        text = make_doc(toc='', blocks='') + '\n<!-- draft that never ends\n'
        path = self.write(text)
        status, out, err = self.refresh(path, '--allow-missing-blocks')
        self.assertEqual(status, 2)
        self.assertIn('HTML comment that opens here never closes', err)

    def test_html_comment_hides_a_draft_section(self):
        draft = ('<!--\n### [10.02] Draft rule\n{{index: draft term}}\n**Rule.** x [S404] §55.55\n-->\n')
        path = self.write(make_doc(rules=DEFAULT_RULES + '\n' + draft))
        status, out, err = self.refresh(path)
        self.assertEqual(status, 0, err)
        self.assertIn('findings: none', out)
        self.assertNotIn('10.02', self.block(path, 'toc'))
        self.assertNotIn('draft', self.block(path, 'index'))

    def test_inline_code_is_not_content(self):
        body = ('- **Rule.** Write a cite as `[S78]`, a reference as `§99.99`, a tag as '
                '`{{index: shown}}` and a marker as `<!-- toc:start -->`. [S1]\n'
                '- **Examples.** A stray ` backtick does not hide [S79].')
        path = self.write(make_doc(rules=rule('10.01', 'Real rule', body)))
        status, out, err = self.check(path)
        self.assertIn('cite key [S79] in §10.01 is not in the source list', out)
        self.assertNotIn('S78', out)
        self.assertNotIn('99.99', out)
        self.assertEqual(self.refresh(path)[0], 0)
        self.assertNotIn('shown', self.block(path, 'index'))


class SourceList(Base):
    """LR-07, LR-16, CW-26-V: sources come from the Sources section only."""

    def test_body_bullets_do_not_define_sources(self):
        body = ('- **Rule.** Limit is five. [S1]\n- [S1] holds that the limit is five.\n'
                '- [S9] reports a rate; no such source is in the source list.')
        appendix_blocks = BLOCKS.replace('## [91] Cite index',
                                         '## [95] Appendix\n\n- [S1] also appears in a bullet here.\n\n'
                                         '## [91] Cite index')
        path = self.write(make_doc(rules=rule('10.01', 'Real rule', body), blocks=appendix_blocks))
        status, out, err = self.refresh(path)
        self.assertIn('1 source,', out)
        self.assertIn('cite key [S9] in §10.01 is not in the source list', out)
        authorities = self.block(path, 'authorities')
        self.assertEqual(authorities, '- [S1] Author, *Title*, Publisher (2025) \u2014 §10.01, §95\n')

    def test_bullet_styles_sub_sections_and_continuation_lines(self):
        sources = ('### [90.01] Cases\n\n* [S1] Zeta Corp. v. Alpha Inc., 123 F.3d 456 (9th Cir. 1999).\n'
                   '   Accessed 2026-11-01. Grade: A.\n\n### [90.02] Statutes\n\n'
                   '+ [S2] 17 U.S.C. §107.\n  - [S3] Indented, *Book* (2001).\n')
        body = '- **Rule.** R. [S1, S2] [S3]'
        path = self.write(make_doc(rules=rule('10.01', 'Real rule', body), sources=sources))
        status, out, err = self.refresh(path)
        self.assertIn('3 sources', out)
        self.assertIn('findings: none', out)
        self.assertIn('- [S1] Zeta Corp. v. Alpha Inc., 123 F.3d 456 (9th Cir. 1999) \u2014 §10.01',
                      self.block(path, 'authorities'))

    def test_malformed_source_lines_are_errors(self):
        sources = DEFAULT_SOURCES + ('1. [S19] Numbered.\n- [S1a] Letter key.\n- [s21] Lower case.\n'
                                     '- **[S22]** Bold key.\n- [S23]No space.\n')
        status, out = self.findings(make_doc(sources=sources))
        self.assertEqual(out.count('source line is not in the form'), 5)

    def test_duplicate_source_key_is_an_error(self):
        sources = '- [S1] First version (2024).\n- [S1] Second, different source (2025).\n'
        path = self.write(make_doc(sources=sources))
        status, out, err = self.refresh(path)
        self.assertIn('source key [S1] appears 2 times', out)
        self.assertIn('Error: source key [S1] appears 2 times', self.block(path, 'health'))
        self.assertIn('First version (2024)', self.block(path, 'authorities'))

    def test_uncited_sources_are_reported_whatever_the_section_title(self):
        sources = DEFAULT_SOURCES + '- [S2] Never cited (2001).\n'
        text = make_doc(sources=sources).replace('## [90] Sources', '## [90] References')
        status, out = self.findings(text)
        self.assertIn('source [S2] is not cited', out)
        self.assertNotIn('source [S1] is not cited', out)

    def test_body_title_that_starts_with_sources_keeps_its_cites(self):
        rules = rule('10.01', 'Sources must carry a grade', '- **Rule.** R. [S1] [S404]')
        status, out = self.findings(make_doc(rules=rules))
        self.assertNotIn('source [S1] is not cited', out)
        self.assertIn('cite key [S404] in §10.01', out)

    def test_retired_source_and_superseded_key(self):
        sources = (DEFAULT_SOURCES + '- [S2] (retired 2026-05-01, superseded by [S1]) Old, *Book*.\n'
                   '- [S3] (retired 2026-05-01, superseded by [S77]) Older, *Book*.\n')
        status, out = self.findings(make_doc(sources=sources))
        self.assertNotIn('source [S2] is not cited', out)
        self.assertNotIn('source [S3] is not cited', out)
        self.assertIn('[S3] is superseded by [S77], which is not in the source list', out)

    def test_missing_sources_section_is_an_error(self):
        text = make_doc(sources='').replace('## [90] Sources\n', '')
        status, out = self.findings(text)
        self.assertIn('no Sources section', out)

    def test_cite_index_keeps_source_order_and_whole_names(self):
        sources = ('- [S5] Zeta Corp. v. Alpha Inc., 123 F.3d 456 (9th Cir. 1999). Accessed 2026-11-01.\n'
                   '- [S2] J. R. R. Tolkien, *The Hobbit*, Allen & Unwin (1937). Grade: B.\n'
                   '- [S1] U.S. Dept. of Justice, *Manual* (2023). https://example.org/a.b/c.\n'
                   '- [S7] ' + 'word ' * 40 + 'end.\n')
        body = '- **Rule.** R. [S1; S2] [S5]'
        path = self.write(make_doc(rules=rule('10.01', 'Real rule', body), sources=sources))
        self.refresh(path)
        lines = self.block(path, 'authorities').splitlines()
        self.assertEqual(lines[0], '- [S5] Zeta Corp. v. Alpha Inc., 123 F.3d 456 (9th Cir. 1999) \u2014 §10.01')
        self.assertEqual(lines[1], '- [S2] J. R. R. Tolkien, *The Hobbit*, Allen & Unwin (1937) \u2014 §10.01')
        self.assertEqual(lines[2], '- [S1] U.S. Dept. of Justice, *Manual* (2023) \u2014 §10.01')
        self.assertTrue(lines[3].endswith('word\u2026 \u2014 (not cited)'), lines[3])


class Cites(Base):
    """LR-08: every documented cite form is read; every other form is reported."""

    def test_cite_forms(self):
        sources = ''.join('- [S%d] Source %d, *Book* (2020).\n' % (n, n) for n in range(1, 9))
        body = ('- **Rule.** A [S1, S2] b [S3 at 4; S4] c [S5-S7] d [S8 at 4, 7].\n'
                '- **Examples.** [S9 p. 4] [s14] [S1a] [S10 §3] [S11at 4] and a link '
                '[S3 pricing](https://example.org).')
        status, out = self.findings(make_doc(rules=rule('10.01', 'Real rule', body), sources=sources))
        self.assertNotIn('is not cited', out)
        for bad in ('[S9 p. 4]', '[s14]', '[S1a]', '[S10 §3]', '[S11at 4]'):
            self.assertIn('§10.01: malformed cite %s' % bad, out)
        self.assertNotIn('pricing', out)
        self.assertNotIn('refers to §3', out)

    def test_undefined_key_inside_a_group(self):
        status, out = self.findings(make_doc(rules=rule('10.01', 'Rule', '- **Rule.** R. [S1, S99]')))
        self.assertIn('cite key [S99] in §10.01 is not in the source list', out)

    def test_rule_line_without_a_cite_is_a_warning(self):
        status, out = self.findings(make_doc(rules=rule('10.01', 'Rule', '- **Rule.** No cite.\n'
                                                        '- **Examples.** Has one. [S1]')))
        self.assertIn('§10.01: the Rule line has no cite', out)
        status, out = self.findings(make_doc(rules=rule('10.01', 'Rule', '- **Rule.** Open. [cite needed]\n'
                                                        '- **Examples.** Has one. [S1]')))
        self.assertNotIn('the Rule line has no cite', out)
        self.assertIn('§10.01: holds [cite needed]', out)


class Staleness(Base):
    """LR-09, LR-11, LR-12: dates, cadence and the stamp line."""

    def test_cite_needed_does_not_hide_staleness(self):
        rules = rule('10.01', 'Rule', '- **Rule.** R. [S1] [cite needed]', verified='2020-01-01')
        status, out = self.findings(make_doc(rules=rules))
        self.assertIn('§10.01: holds [cite needed]', out)
        self.assertIn('§10.01: last verified 2020-01-01, older than the 90-day cadence', out)

    def test_future_and_invalid_dates_are_errors_not_crashes(self):
        rules = (rule('10.01', 'Future', '- **Rule.** R. [S1]', verified='2062-11-01')
                 + rule('10.02', 'Month 13', '- **Rule.** R. [S1]', verified='2026-13-45')
                 + rule('10.03', 'February 30', '- **Rule.** R. [S1]', verified='2026-02-30')
                 + rule('10.04', 'Placeholder', '- **Rule.** R. [S1]', verified='YYYY-MM-DD'))
        status, out = self.findings(make_doc(rules=rules))
        self.assertEqual(status, 1)
        self.assertIn('§10.01: Last verified date 2062-11-01 is in the future', out)
        for section, value in (('10.02', '2026-13-45'), ('10.03', '2026-02-30'), ('10.04', 'YYYY-MM-DD')):
            self.assertIn('§%s: Last verified date "%s" is not a valid' % (section, value), out)

    def test_last_date_in_a_section_counts_and_plain_form_is_read(self):
        rules = ('### [10.01] Rule\n\n**Rule.** R. [S1]\nLast verified: 2020-01-01\n'
                 '**Last verified:** 2026-11-01\n')
        status, out = self.findings(make_doc(rules=rules))
        self.assertNotIn('older than', out)
        self.assertNotIn('no Last verified line', out)

    def test_only_rule_sections_need_a_date(self):
        blocks = BLOCKS.replace('## [91] Cite index', '## [80] Glossary\n\n### [80.01] Sub-glossary\n\n'
                                '- **Term**: definition.\n\n## [91] Cite index')
        rules = DEFAULT_RULES + '\n### [10.02] No date here\n\n- **Rule.** R. [S1]\n'
        status, out = self.findings(make_doc(rules=rules, blocks=blocks))
        self.assertIn('§10.02: no Last verified line', out)
        self.assertNotIn('§80.01', out)
        self.assertNotIn('§10:', out)

    def test_cadence_comes_from_the_file_and_the_flag_overrides_it(self):
        path = self.write(make_doc(header='Stale-after: 120'))
        status, out, err = self.check(path, today='2027-02-15')
        self.assertIn('cadence 120 days (from the Stale-after line)', out)
        self.assertNotIn('older than', out)
        status, out, err = self.check(path, '--stale-days', '90', today='2027-02-15')
        self.assertIn('cadence 90 days (from --stale-days)', out)
        self.assertIn('last verified 2026-11-01, older than the 90-day cadence', out)
        status, out, err = self.check(self.write(make_doc(header='')), today='2027-02-15')
        self.assertIn('cadence 90 days (default)', out)
        self.assertIn('older than the 90-day cadence', out)

    def test_invalid_stale_after_value_is_an_error(self):
        status, out = self.findings(make_doc(header='Stale-after: soon'))
        self.assertIn('Stale-after needs a whole number of days greater than 0', out)
        status, out = self.findings(make_doc(header='Stale-after: 30\n\nStale-after: 60'))
        self.assertIn('2 different Stale-after values', out)

    def test_no_daily_churn(self):
        path = self.write(make_doc())
        self.assertEqual(self.refresh(path, today='2026-11-10')[0], 0)
        first = self.read_bytes(path)
        self.assertIn(b'Generated content last changed 2026-11-10._', first)
        self.assertNotIn(b'days ago', first)
        for later in ('2026-11-11', '2026-12-25', '2027-01-30'):
            status, out, err = self.refresh(path, today=later)
            self.assertEqual(status, 0, err)
            self.assertIn('file not changed', out)
            self.assertEqual(self.read_bytes(path), first, later)
            self.assertEqual(self.check(path, today=later)[0], 0)

    def test_stamp_date_changes_only_with_other_generated_content(self):
        path = self.write(make_doc())
        self.refresh(path, today='2026-11-10')
        status, out, err = self.check(path, today='2027-03-01')
        self.assertEqual(status, 1)
        self.assertIn('out-of-date blocks: health', out)
        status, out, err = self.refresh(path, today='2027-03-01')
        self.assertIn('blocks updated: health', out)
        health = self.block(path, 'health')
        self.assertIn('Generated content last changed 2027-03-01._', health)
        self.assertIn('- Warning: §10.01: last verified 2026-11-01, older than the 90-day cadence.', health)
        second = self.read_bytes(path)
        self.refresh(path, today='2027-06-01')
        self.assertEqual(self.read_bytes(path), second)

    def test_stamp_counts_use_singular_and_plural(self):
        path = self.write(make_doc())
        self.refresh(path)
        self.assertIn('_8 sections, 1 source, 1 index term. Cadence: 90 days.', self.block(path, 'health'))


class CrossReferences(Base):
    """LR-10: section signs."""

    def test_statutes_and_urls_are_not_cross_references(self):
        body = ('- **Rule.** See 17 U.S.C. §107 and 47 U.S.C. §230(c)(1); compare § 44.44 and '
                'https://example.org/law/§10.99 and [S1 at §33.33]. [S1]')
        sources = '- [S1] Act, 17 U.S.C. §108 and §55.55. https://example.org/§109.\n'
        status, out = self.findings(make_doc(rules=rule('10.01', 'Rule', body), sources=sources))
        self.assertNotIn('refers to', out)
        self.assertIn('findings: none', out)

    def test_ranges_and_lists_are_checked_and_the_holder_is_named(self):
        body = ('- **Rule.** See §10.01-10.02, §10.01\u201377.77, §10.01, 66.66 and §§10.01, §55.55 '
                'and §10. [S1]')
        rules = rule('10.01', 'Rule', body) + rule('10.02', 'Second', '- **Rule.** R. [S1]')
        status, out = self.findings(make_doc(rules=rules))
        for missing in ('77.77', '66.66', '55.55'):
            self.assertIn('§10.01 refers to §%s, which does not exist' % missing, out)
        self.assertEqual(out.count('which does not exist'), 3)

    def test_index_term_with_a_section_sign_is_not_a_cross_reference(self):
        body = '<!-- index: §230 immunity -->\n\n- **Rule.** R. [S1]'
        status, out = self.findings(make_doc(rules=rule('10.01', 'Rule', body)))
        self.assertNotIn('refers to', out)


class Contents(Base):
    """LR-13: anchors follow GitHub's rule, and nesting follows the heading levels."""

    def test_anchors_match_github(self):
        titles = [('10.01', 'A/B and C - d', '1001-ab-and-c---d'),
                  ('10.02', 'Use --check in CI', '1002-use---check-in-ci'),
                  ('10.03', 'Em \u2014 dash & ampersand', '1003-em--dash--ampersand'),
                  ('10.04', 'See [a link](https://example.org) here', '1004-see-a-link-here')]
        rules = ''.join(rule(i, t, '- **Rule.** R. [S1]') for i, t, _ in titles)
        path = self.write(make_doc(rules=rules))
        self.refresh(path)
        toc = self.block(path, 'toc')
        for section_id, title, anchor in titles:
            self.assertIn('](#%s)\n' % anchor, toc, title)

    def test_repeated_titles_get_numbered_anchors(self):
        module = load_module(REFRESH, 'refresh_reference_slug')
        seen = {}
        self.assertEqual(module.github_slug('[10.07] Same title', seen), '1007-same-title')
        self.assertEqual(module.github_slug('[10.07] Same title', seen), '1007-same-title-1')
        self.assertEqual(module.github_slug('[00] Alpha \u2014 Beta', seen), '00-alpha--beta')
        self.assertEqual(module.github_slug('[10.11] Emoji \U0001F680 and \u00a9 50% + more', seen),
                         '1011-emoji--and--50--more')

    def test_nesting_and_title_handling(self):
        text = make_doc(rules='#### [10.50] Deep first\n\n' + DEFAULT_RULES)
        text += '\n# [95] Second part\n\n## [96] Child of the second part\n'
        path = self.write(text)
        self.refresh(path)
        toc = self.block(path, 'toc').splitlines()
        self.assertNotIn('00 Test', '\n'.join(toc))
        self.assertNotIn('Contents', '\n'.join(toc))
        self.assertEqual(toc[0], '- [10 Topic A](#10-topic-a)')
        self.assertEqual(toc[1], '  - [10.50 Deep first](#1050-deep-first)')
        self.assertEqual(toc[2], '  - [10.01 Rule one is a full sentence](#1001-rule-one-is-a-full-sentence)')
        self.assertIn('- [95 Second part](#95-second-part)', toc)
        self.assertIn('  - [96 Child of the second part](#96-child-of-the-second-part)', toc)
        for line in toc:
            self.assertFalse(line.startswith('    - [10.50'), line)


class Index(Base):
    """LR-15, LR-25, CW-26-V: the index builder."""

    def index_for(self, tags, extra_rules=''):
        body = '\n'.join(tags) + '\n\n- **Rule.** R. [S1]'
        path = self.write(make_doc(rules=rule('10.01', 'Rule', body) + extra_rules))
        status, out, err = self.refresh(path)
        self.assertEqual(status, 0, err)
        return out, self.block(path, 'index')

    def test_empty_tags_are_errors_not_crashes(self):
        out, index = self.index_for(['{{index: }}', '{{index: | orphan alias}}', '<!-- index: -->'])
        self.assertEqual(out.count('§10.01: index tag has no term'), 3)
        self.assertEqual(index, '')

    def test_unclosed_brace_tag_is_an_error(self):
        out, index = self.index_for(['{{index: never closed'])
        self.assertIn('index tag has no closing }}', out)

    def test_both_tag_forms_and_spacing_variants(self):
        out, index = self.index_for(['<!-- index: comment form | hidden alias -->',
                                     '{{index: brace form}}', '{{ Index: spaced form }}',
                                     '<!-- index: two\n   lines | second\n   alias -->'])
        for entry in ('- **comment form** \u2014 §10.01', '- hidden alias \u2014 *see* comment form',
                      '- **brace form** \u2014 §10.01', '- **spaced form** \u2014 §10.01',
                      '- **two lines** \u2014 §10.01', '- second alias \u2014 *see* two lines'):
            self.assertIn(entry + '\n', index)

    def test_case_merge_alias_conflicts_and_dangling_pointers(self):
        second = rule('10.02', 'Second', '<!-- index: retrieval | hooks -->\n'
                      '<!-- index: automation | hooks; Retrieval -->\n\n- **Rule.** R. [S1]')
        out, index = self.index_for(
            ['<!-- index: Retrieval | RAG -->', '<!-- index: enforcement | hooks; '
             'see also: Retrieval, no such term -->'], second)
        self.assertEqual(index.count('**Retrieval**'), 1)
        self.assertIn('- **Retrieval** \u2014 §10.01, §10.02', index)
        self.assertIn('index term is spelled 2 ways (Retrieval, retrieval)', out)
        self.assertIn('index alias "hooks" points to 3 terms', out)
        self.assertIn('index alias "Retrieval" is also a preferred term', out)
        self.assertIn('see-also pointer to "no such term", which is not an index term', out)
        self.assertNotIn('pointer to "Retrieval"', out)

    def test_markdown_characters_symbols_and_accents(self):
        out, index = self.index_for(['<!-- index: *starred* term -->', '<!-- index: \u00c9migr\u00e9 -->',
                                     '<!-- index: eagle -->', '<!-- index: 200 lines -->',
                                     '<!-- index: echo -->'])
        self.assertIn('- **\\*starred\\* term** \u2014 §10.01', index)
        self.assertNotIn('*****', index)
        lines = [line for line in index.splitlines() if line]
        self.assertEqual(lines[0], '**Symbols**')
        letters = [line for line in lines if re.match(r'^\*\*\w+\*\*$', line)]
        self.assertEqual(letters, ['**Symbols**', '**E**'])
        order = [line for line in lines if line.startswith('- **e') or line.startswith('- **\u00c9')]
        self.assertEqual(order, ['- **eagle** \u2014 §10.01', '- **echo** \u2014 §10.01',
                                 '- **\u00c9migr\u00e9** \u2014 §10.01'])

    def test_more_than_seven_locators_is_a_health_finding_in_file_order(self):
        rules = ''.join(rule('10.%02d' % n, 'Rule %d' % n, '<!-- index: negligence -->\n\n- **Rule.** R. [S1]')
                        for n in (9, 8, 7, 6, 5, 4, 3, 2, 1))
        path = self.write(make_doc(rules=rules))
        status, out, err = self.refresh(path)
        self.assertIn('index term "negligence" has 9 locators', out)
        self.assertIn('Warning: index term "negligence" has 9 locators', self.block(path, 'health'))
        self.assertIn('- **negligence** \u2014 §10.09, §10.08, §10.07', self.block(path, 'index'))
        self.assertEqual(self.check(path)[0], 1)

    def test_long_whitespace_runs_do_not_stall_the_script(self):
        pad = ' ' * 30000
        body = ('{{index:' + pad + 'x\n[S1' + pad + ', x\n#' + pad + 'x' + pad + '\n'
                '§10.01' + ' ,' * 15000 + '\n' + '`' * 3 + ' `` ` ' * 5000 + '\n'
                + '[' * 30000 + '\n- **Rule.** R. [S1]')
        sources = DEFAULT_SOURCES + '- [S2]' + pad + 'Late.' + pad + 'https://example.org\n'
        path = self.write(make_doc(rules=rule('10.01', 'Rule', body), sources=sources))
        done = subprocess.run([sys.executable, REFRESH, path, '--check', '--today', TODAY],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertIn(done.returncode, (1, 2))


class FileHandling(Base):
    """LR-17, LR-26: atomic writes, line endings, byte-order mark, output encoding."""

    def test_crlf_and_bom_are_preserved(self):
        path = self.write(make_doc(), newline='\r\n', bom=True)
        status, out, err = self.refresh(path)
        self.assertEqual(status, 0, err)
        self.assertIn('8 sections', out)
        data = self.read_bytes(path)
        self.assertTrue(data.startswith(b'\xef\xbb\xbf# [00]'))
        self.assertNotIn(b'\n', data.replace(b'\r\n', b''))
        self.assertIn(b'- No findings.\r\n', data)
        self.assertEqual(self.check(path)[0], 0)

    def test_hand_written_lines_keep_their_own_endings(self):
        text = make_doc().replace('## [10] Topic A\n', '## [10] Topic A\r\n')
        path = self.write(text)
        self.refresh(path)
        data = self.read_bytes(path)
        self.assertEqual(data.count(b'\r\n'), 1)
        self.assertIn(b'## [10] Topic A\r\n', data)

    def test_missing_final_newline_is_preserved(self):
        path = self.write(make_doc().rstrip('\n'))
        self.refresh(path)
        self.assertTrue(self.read(path).endswith('<!-- health:end -->'))

    def test_failed_write_leaves_the_original_and_no_temporary_file(self):
        module = load_module(REFRESH, 'refresh_reference_atomic')
        path = self.write('original content\n')
        real_replace = module.os.replace

        def failing_replace(source, target):
            raise OSError(28, 'No space left on device')
        module.os.replace = failing_replace
        try:
            with self.assertRaises(OSError):
                module.write_atomic(path, b'new content\n')
        finally:
            module.os.replace = real_replace
        self.assertEqual(self.read(path), 'original content\n')
        self.assertEqual(os.listdir(self.tmp), ['ref.md'])
        module.write_atomic(path, b'new content\n')
        self.assertEqual(self.read(path), 'new content\n')
        self.assertEqual(os.listdir(self.tmp), ['ref.md'])

    def test_file_mode_is_kept(self):
        path = self.write(make_doc())
        os.chmod(path, 0o640)
        self.refresh(path)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o640)

    def test_ascii_locale_does_not_crash_the_output(self):
        path = self.write(make_doc(rules=rule('10.01', 'Appeal \u2192 30 days', '- **Rule.** R. [S9]')))
        env = dict(os.environ, PYTHONIOENCODING='ascii', LC_ALL='C', PYTHONUTF8='0')
        status, out, err = self.refresh(path, env=env)
        self.assertEqual(status, 0, err)
        self.assertIn('§10.01', out)

    def test_closed_output_pipe_does_not_stop_the_refresh(self):
        rules = DEFAULT_RULES + ''.join('\n### Heading %d without an ID\n' % n for n in range(3000))
        path = self.write(make_doc(rules=rules))
        process = subprocess.Popen([sys.executable, REFRESH, path, '--today', TODAY],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.stdout.readline()
        process.stdout.close()
        errors = process.stderr.read().decode('utf-8', 'replace')
        process.stderr.close()
        self.assertEqual(process.wait(timeout=RUN_TIMEOUT), 0, errors)
        self.assertNotIn('Traceback', errors)
        self.assertIn('Error: line', self.block(path, 'health'))

    def test_scripts_leave_no_bytecode_in_the_skill_folder(self):
        path = self.write(make_doc())
        self.refresh(path)
        self.export(path, '--to', 'html', '--out', os.path.join(self.tmp, 'missing-dir', 'a.html'))
        for folder, names, files in os.walk(SKILL):
            self.assertNotIn('__pycache__', names, folder)


class ShippedFiles(Base):
    """LR-19, LR-20, LR-22 to LR-24: the template, the example and SKILL.md."""

    FIELD_LABELS = ['Rule', 'Elements', 'Exceptions', 'Test', 'Examples', 'Policy', 'Open']

    def skill_files(self):
        paths = []
        for folder, names, files in os.walk(SKILL):
            for name in files:
                paths.append(os.path.join(folder, name))
        return paths

    def frontmatter_and_body(self):
        with open(os.path.join(SKILL, 'SKILL.md'), encoding='utf-8') as handle:
            text = handle.read()
        self.assertTrue(text.startswith('---\n'))
        front, body = text[4:].split('\n---\n', 1)
        return front, body

    def test_example_passes_check_with_a_pinned_clock(self):
        before = self.read_bytes(EXAMPLE)
        status, out, err = run_script(REFRESH, [EXAMPLE, '--check', '--today', '2026-11-20'])
        self.assertEqual(status, 0, out + err)
        self.assertIn('findings: none', out)
        self.assertIn('cadence 120 days (from the Stale-after line)', out)
        self.assertEqual(self.read_bytes(EXAMPLE), before)

    def test_example_uses_only_the_fixed_labels_and_grades(self):
        text = self.read(EXAMPLE)
        labels = set(re.findall(r'^- \*\*([^*]+)\.\*\*', text, flags=re.M))
        self.assertTrue(labels)
        self.assertLessEqual(labels, set(self.FIELD_LABELS))
        skill_format = self.read(os.path.join(SKILL, 'references', 'format.md'))
        for label in self.FIELD_LABELS:
            self.assertIn('- **%s.**' % label, skill_format)
        for line in re.findall(r'^- \[S\d+\].*$', text.split('## [91]')[0], flags=re.M):
            self.assertRegex(line, r'https://\S+\. Accessed \d{4}-\d{2}-\d{2}\. Grade: [A-D]\.$')

    def test_template_ships_empty_blocks_and_placeholder_dates(self):
        text = self.read(TEMPLATE)
        for name in ('toc', 'authorities', 'index', 'health'):
            self.assertIn('<!-- %s:start -->\n<!-- %s:end -->\n' % (name, name), text)
        self.assertNotRegex(text, r'\d{4}-\d{2}-\d{2}')
        self.assertNotIn('scripts/', text)
        self.assertIn('Stale-after: 90', text)

    def test_template_refreshes_and_reports_only_its_placeholder_date(self):
        path = self.write(self.read(TEMPLATE))
        status, out, err = self.refresh(path)
        self.assertEqual(status, 0, err)
        self.assertIn('errors: 1', out)
        self.assertIn('Last verified date "YYYY-MM-DD" is not a valid', out)
        self.assertNotIn('warnings:', out)
        self.assertIn('- [10.01 Write the rule here as a full sentence]', self.block(path, 'toc'))
        filled = self.read(path).replace('YYYY-MM-DD', '2026-11-01')
        path = self.write(filled, 'filled.md')
        self.refresh(path)
        self.assertEqual(self.check(path)[0], 0)

    def test_no_private_reference_ships_and_owner_is_a_placeholder(self):
        banned = re.compile(r'session note|exhaustive-research', re.I)
        for path in self.skill_files():
            text = self.read(path)
            self.assertIsNone(banned.search(text), path)
        for path in (TEMPLATE, EXAMPLE):
            owners = re.findall(r'Owner: ([^.]*)\.', self.read(path))
            self.assertEqual(owners, ['(owner name)'], path)

    def test_skill_folder_holds_no_tests_and_no_stray_files(self):
        self.assertEqual(sorted(os.listdir(SKILL)),
                         ['SKILL.md', 'examples', 'references', 'scripts', 'templates'])
        self.assertEqual(sorted(os.listdir(os.path.join(SKILL, 'scripts'))),
                         ['export_reference.py', 'refresh_reference.py'])

    def test_frontmatter(self):
        front, body = self.frontmatter_and_body()
        keys = re.findall(r'^([A-Za-z-]+):', front, flags=re.M)
        self.assertEqual(keys, ['name', 'description', 'compatibility', 'metadata', 'allowed-tools'])
        self.assertIn('name: living-reference\n', front)
        self.assertIn('metadata:\n  version: "2.0.0"\n', front)
        description = re.search(r'^description: "(.*)"$', front, flags=re.M).group(1)
        self.assertGreaterEqual(len(description), 200)
        self.assertLessEqual(len(description), 400)
        for banned in ('<', '>', '`', 'enforced by'):
            self.assertNotIn(banned, description)
        self.assertIn('Use when', description)
        allowed = re.search(r"^allowed-tools: '(.*)'$", front, flags=re.M).group(1)
        self.assertEqual(allowed, 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/refresh_reference.py" *)')

    def test_body_length_commands_and_links(self):
        front, body = self.frontmatter_and_body()
        self.assertLessEqual(len(body.strip('\n').split('\n')), 120)
        for line in body.split('\n'):
            if line.startswith('python3 '):
                self.assertRegex(line, r'^python3 "\$\{CLAUDE_SKILL_DIR\}/scripts/\w+\.py" ')
        self.assertNotRegex(body, r'(?<!\}/)scripts/\w+\.py')
        self.assertNotIn('unittest', body)
        links = re.findall(r'\]\((references/[\w-]+\.md)\)', body)
        self.assertGreaterEqual(len(set(links)), 4)
        for link in links:
            self.assertTrue(os.path.isfile(os.path.join(SKILL, link)), link)
        for word in (' should ', 'and/or', '\u2192', '\u00b7'):
            self.assertNotIn(word, body)

    def test_every_documented_option_exists(self):
        documents = self.read(os.path.join(SKILL, 'SKILL.md'))
        documents += self.read(os.path.join(SKILL, 'references', 'script-reference.md'))
        help_text = run_script(REFRESH, ['--help'])[1] + run_script(EXPORT, ['--help'])[1]
        for option in set(re.findall(r'`(--[a-z][a-z-]+)', documents)):
            self.assertIn(option, help_text)


@unittest.skipUnless(PANDOC, 'pandoc is not installed')
class Export(Base):
    """LR-03, LR-04, LR-18, LR-27: the export."""

    def html(self, text, *args):
        path = self.write(text)
        out = os.path.join(self.tmp, 'out.html')
        status, stdout, stderr = self.export(path, '--to', 'html', '--out', out, *args)
        self.assertEqual(status, 0, stderr)
        return self.read(out), stderr

    def test_export_never_changes_the_source(self):
        path = self.write(make_doc())
        before = self.read_bytes(path)
        status, out, err = self.export(path, '--to', 'html')
        self.assertEqual(status, 0, err)
        self.assertEqual(out.strip(), os.path.join(self.tmp, 'ref.html'))
        self.assertEqual(self.read_bytes(path), before)
        html = self.read(os.path.join(self.tmp, 'ref.html'))
        self.assertIn('No findings', html)
        self.assertIn('Generated content last changed %s' % TODAY, html)

    def test_failed_export_leaves_the_source_and_no_partial_file(self):
        path = self.write(make_doc())
        before = self.read_bytes(path)
        status, out, err = self.export(path, '--to', 'html', '--out',
                                       os.path.join(self.tmp, 'nodir', 'a.html'))
        self.assertEqual(status, 2)
        self.assertIn('output directory does not exist', err)
        self.assertEqual(self.read_bytes(path), before)
        self.assertEqual(os.listdir(self.tmp), ['ref.md'])

    def test_existing_output_needs_force_and_the_source_is_never_the_output(self):
        path = self.write(make_doc())
        neighbour = self.write('DO NOT LOSE\n', 'ref.html')
        status, out, err = self.export(path, '--to', 'html')
        self.assertEqual(status, 2)
        self.assertIn('pass --force', err)
        self.assertEqual(self.read(neighbour), 'DO NOT LOSE\n')
        self.assertEqual(self.export(path, '--to', 'html', '--force')[0], 0)
        self.assertIn('<html', self.read(neighbour))
        before = self.read_bytes(path)
        status, out, err = self.export(path, '--to', 'html', '--out', path, '--force')
        self.assertEqual(status, 2)
        self.assertIn('output path is the source file', err)
        self.assertEqual(self.read_bytes(path), before)

    def test_structure_error_stops_the_export(self):
        path = self.write(make_doc(toc='<!-- toc:start -->\n'))
        status, out, err = self.export(path, '--to', 'html')
        self.assertEqual(status, 2)
        self.assertIn('structure error', err)
        self.assertEqual(os.listdir(self.tmp), ['ref.md'])

    def test_findings_reach_stderr_and_strict_refuses(self):
        path = self.write(make_doc(rules=rule('10.01', 'Rule', '- **Rule.** R. [S9] §77.77',
                                              verified='2020-01-01')))
        status, out, err = self.export(path, '--to', 'html')
        self.assertEqual(status, 0, err)
        self.assertIn('cite key [S9]', err)
        self.assertIn('refers to §77.77', err)
        self.assertIn('older than the 90-day cadence', err)
        status, out, err = self.export(path, '--to', 'html', '--strict', '--force')
        self.assertEqual(status, 1)
        self.assertIn('not exported', err)

    def test_cadence_in_the_file_applies_to_the_export(self):
        path = self.write(make_doc(header='Stale-after: 120'))
        status, out, err = run_script(EXPORT, [path, '--to', 'html', '--today', '2027-02-15'])
        self.assertEqual(status, 0, err)
        self.assertNotIn('older than', err)

    def test_headings_survive_without_blank_lines(self):
        text = ('# [00] Test reference\n## [02] Contents\n<!-- toc:start -->\n<!-- toc:end -->\n'
                '## [10] Topic A\n### [10.01] Rule one\n**Rule.** Something. [S1 at 4]\n'
                'Last verified: 2026-11-01\n### [10.02] Rule two\n**Rule.** Else. [S1]\n'
                'Last verified: 2026-11-01\n## [90] Sources\n- [S1] A, *B* (2020).\n')
        html, _ = self.html(text)
        self.assertEqual(len(re.findall(r'<h[1-6]\b', html)), 6)

    def test_flags_paths_and_single_title_survive(self):
        body = ('- **Rule.** Run refresh with --check and set --stale-days 120; never pass '
                '--force. Path C:\\new\\table. [S1]')
        html, _ = self.html(make_doc(rules=rule('10.01', 'Rule', body)))
        self.assertIn('--check', html)
        self.assertIn('--stale-days 120', html)
        self.assertIn('C:\\new\\table', html)
        self.assertEqual(len(re.findall(r'<h1\b', html)), 1)
        self.assertIn('<title>Test: living reference</title>', html)
        self.assertNotIn('id="TOC"', html)

    def test_example_exports_with_every_heading_and_no_dead_link(self):
        out = os.path.join(self.tmp, 'example.html')
        before = self.read_bytes(EXAMPLE)
        status, stdout, stderr = run_script(EXPORT, [EXAMPLE, '--to', 'html', '--out', out,
                                                     '--today', '2026-11-20'])
        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, '')
        self.assertEqual(self.read_bytes(EXAMPLE), before)
        html = self.read(out)
        source_headings = len(re.findall(r'^#{1,6} ', self.read(EXAMPLE), flags=re.M))
        self.assertEqual(len(re.findall(r'<h[1-6]\b', html)), source_headings)
        ids = set(re.findall(r'\bid="([^"]+)"', html))
        internal = re.findall(r'href="#([^"]+)"', html)
        self.assertGreaterEqual(len(internal), 10)
        self.assertEqual([link for link in internal if link not in ids], [])
        self.assertIn('<li><strong>Rule.</strong>', html)

    def test_raw_html_is_removed_unless_allowed(self):
        body = ('- **Rule.** x <script>document.title="INJECTED"</script> y '
                '<img src=x onerror="alert(1)"> [l](javascript:alert(2)) [S1]\n\n'
                '<iframe src="https://example.org"></iframe>\n')
        text = make_doc(rules=rule('10.01', 'Rule', body))
        html, _ = self.html(text)
        for fragment in ('<script>document', 'onerror', '<iframe', 'javascript:'):
            self.assertNotIn(fragment, html)
        html, _ = self.html(text, '--allow-raw-html', '--force')
        self.assertIn('<script>document', html)

    def test_markers_and_tags_are_stripped_outside_code_only(self):
        body = ('<!-- index: hidden term | hidden alias -->\n{{index: brace term}}\n\n'
                '- **Rule.** Tag a section with `{{index: shown term}}` between '
                '`<!-- toc:start -->` and `<!-- toc:end -->`. [S1]\n\n'
                '```markdown\n<!-- health:start -->\n{{index: fenced term}}\n```\n')
        html, _ = self.html(make_doc(rules=rule('10.01', 'Rule', body)), '--allow-raw-html')
        self.assertIn('{{index: shown term}}', html)
        self.assertIn('{{index: fenced term}}', html)
        self.assertIn('&lt;!-- toc:start --&gt;', html)
        self.assertIn('&lt;!-- health:start --&gt;', html)
        self.assertNotIn('<!-- toc:start -->', html)
        self.assertNotIn('<!-- index: hidden', html)
        self.assertNotIn('{{index: brace term}}', html)
        self.assertIn('<strong>hidden term</strong>', html)

    def test_docx_export_writes_a_zip_container(self):
        path = self.write(make_doc())
        status, out, err = self.export(path)
        self.assertEqual(status, 0, err)
        self.assertEqual(self.read_bytes(os.path.join(self.tmp, 'ref.docx'))[:2], b'PK')

    def test_pdf_without_an_engine_explains_and_writes_nothing(self):
        bin_dir = os.path.join(self.tmp, 'bin')
        os.mkdir(bin_dir)
        os.symlink(PANDOC, os.path.join(bin_dir, 'pandoc'))
        work = os.path.join(self.tmp, 'work')
        os.mkdir(work)
        path = os.path.join(work, 'ref.md')
        shutil.copy(self.write(make_doc()), path)
        before = self.read_bytes(path)
        status, out, err = self.export(path, '--to', 'pdf', env=dict(os.environ, PATH=bin_dir))
        self.assertEqual(status, 2)
        self.assertIn('PDF export found no way to make a PDF', err)
        self.assertIn('LibreOffice', err)
        self.assertEqual(os.listdir(work), ['ref.md'])
        self.assertEqual(self.read_bytes(path), before)
        status, out, err = self.export(path, '--to', 'pdf', '--pdf-engine', 'no-such-engine',
                                       env=dict(os.environ, PATH=bin_dir))
        self.assertEqual(status, 2)
        self.assertIn('"no-such-engine" is not on PATH', err)

    def pdf_with_only(self, program_names):
        """Export to PDF with a PATH that holds pandoc plus the first named program found."""
        found = None
        for name in program_names:
            found = shutil.which(name)
            if found:
                break
        if not found:
            self.skipTest('none of %s is installed' % ', '.join(program_names))
        bin_dir = os.path.join(self.tmp, 'bin-pdf')
        os.mkdir(bin_dir)
        os.symlink(PANDOC, os.path.join(bin_dir, 'pandoc'))
        os.symlink(os.path.realpath(found), os.path.join(bin_dir, os.path.basename(found)))
        path = self.write(make_doc())
        before = self.read_bytes(path)
        env = dict(os.environ, PATH=bin_dir + os.pathsep + '/usr/bin' + os.pathsep + '/bin')
        for other in ('pdflatex', 'xelatex', 'lualatex', 'tectonic', 'typst', 'weasyprint',
                      'wkhtmltopdf'):
            if shutil.which(other):
                self.skipTest('a pandoc PDF engine is installed, so the fallback is not reached')
        status, out, err = self.export(path, '--to', 'pdf', env=env)
        self.assertEqual(status, 0, err)
        pdf = self.read_bytes(os.path.join(self.tmp, 'ref.pdf'))
        self.assertEqual(pdf[:5], b'%PDF-')
        self.assertGreater(len(pdf), 1000)
        self.assertEqual(self.read_bytes(path), before)

    def test_pdf_falls_back_to_libreoffice(self):
        self.pdf_with_only(('soffice', 'libreoffice'))

    def test_pdf_falls_back_to_a_chromium_browser(self):
        self.pdf_with_only_browser()

    def pdf_with_only_browser(self):
        """Call the browser route directly, because LibreOffice on PATH would win otherwise."""
        scripts = os.path.dirname(EXPORT)
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        sys.dont_write_bytecode = True
        import export_reference
        self.assertIsNone(export_reference.find_program(('no-such-program-anywhere',)))
        import glob
        shells = sorted(glob.glob('/opt/pw-browsers/chromium_headless_shell-*/*/chrome-headless-shell'))
        browser = shells[-1] if shells else export_reference.find_program(
            export_reference.BROWSER_PROGRAMS)
        if not browser:
            self.skipTest('no Chromium browser is installed')
        work = os.path.join(self.tmp, 'browser-work')
        os.mkdir(work)
        target = os.path.join(self.tmp, 'browser.pdf')

        def pandoc_step(kind, destination, engine=None):
            with open(destination, 'w', encoding='utf-8') as handle:
                handle.write('<html><body><h1>Title</h1><p>Body text.</p></body></html>')

        try:
            export_reference.pdf_through_browser(browser, pandoc_step, work, target)
        except export_reference.ExportError as error:
            if 'did not finish' in str(error):
                self.skipTest('the installed browser hangs in this environment: %s' % error)
            raise
        self.assertEqual(self.read_bytes(target)[:5], b'%PDF-')


class ExportWithoutPandoc(Base):
    """LR-04: a missing tool is one clear line, not a traceback."""

    def test_missing_pandoc_is_reported(self):
        try:
            import pypandoc  # noqa: F401
        except ImportError:
            pass
        else:
            self.skipTest('pypandoc is installed and can supply pandoc')
        path = self.write(make_doc())
        before = self.read_bytes(path)
        empty = os.path.join(self.tmp, 'empty-bin')
        os.mkdir(empty)
        status, out, err = self.export(path, '--to', 'html', env=dict(os.environ, PATH=empty))
        self.assertEqual(status, 2)
        self.assertIn('pandoc not found', err)
        self.assertNotIn('Traceback', err)
        self.assertEqual(self.read_bytes(path), before)

    def test_usage_errors_exit_2(self):
        path = self.write(make_doc())
        self.assertEqual(run_script(EXPORT, [path, '--to', 'odt'])[0], 2)
        self.assertEqual(run_script(EXPORT, [])[0], 2)
        self.assertEqual(run_script(EXPORT, [os.path.join(self.tmp, 'missing.md'), '--to', 'html'])[0], 2)


if __name__ == '__main__':
    unittest.main()
