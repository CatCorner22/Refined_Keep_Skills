"""Tests for lib/ad_shell.py: tokenizing, segments, nesting, wrappers, redirects, cd tracking, fetches."""
import os
import sys
import unittest

sys.dont_write_bytecode = True
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import ad_shell  # noqa: E402


def programs(command):
    """Return the program of every segment of a command."""
    return [ad_shell.program(segment.argv) for segment in ad_shell.parse(command).segments]


def argvs(command):
    """Return the argv of every segment of a command."""
    return [segment.argv for segment in ad_shell.parse(command).segments]


class TokenizeTests(unittest.TestCase):

    def test_quotes_and_escapes_are_removed_from_words(self):
        cases = [
            ("echo 'a b' \"c d\" e\\ f", [["echo", "a b", "c d", "e f"]]),
            ("\"rm\" -rf build/", [["rm", "-rf", "build/"]]),
            ("r\\m -rf build/", [["rm", "-rf", "build/"]]),
            ("rm \"-rf\" build/", [["rm", "-rf", "build/"]]),
            ("rm -r\"f\" build/", [["rm", "-rf", "build/"]]),
            ("echo \"say \\\"hi\\\"\"", [["echo", "say \"hi\""]]),
            ("echo $'a\\tb'", [["echo", "a\tb"]]),
            ("echo a#b # trailing comment", [["echo", "a#b"]]),
            ("echo one \\\n two", [["echo", "one", "two"]]),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(argvs(command), expected)

    def test_segments_split_on_every_operator(self):
        cases = [
            ("a && b || c ; d | e |& f & g", ["a", "b", "c", "d", "e", "f", "g"]),
            ("a\nb", ["a", "b"]),
            ("(a; b) && { c; d; }", ["a", "b", "c", "d"]),
            ("if true; then rm -rf x; else ls; fi", ["true", "rm", "ls", "fi"]),
            ("while read f; do rm \"$f\"; done", ["read", "rm", "done"]),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(programs(command), expected)

    def test_unbalanced_quotes_fail_without_segments(self):
        for command in ("echo 'unbalanced", "echo \"unbalanced", "echo $(ls", "echo `ls"):
            with self.subTest(command=command):
                parsed = ad_shell.parse(command)
                self.assertFalse(parsed.ok)
                self.assertEqual(parsed.segments, [])
                self.assertTrue(parsed.error)

    def test_non_text_and_empty_commands(self):
        self.assertFalse(ad_shell.parse(None).ok)
        empty = ad_shell.parse("   ")
        self.assertTrue(empty.ok)
        self.assertEqual(empty.segments, [])

    def test_raw_is_the_source_text_of_the_segment(self):
        parsed = ad_shell.parse("git commit -m \"fix: x\"   &&  npm test")
        self.assertEqual([segment.raw for segment in parsed.segments], ["git commit -m \"fix: x\"", "npm test"])


class NestingTests(unittest.TestCase):

    def test_nested_command_text_becomes_segments(self):
        cases = [
            ("echo $(rm -rf x)", ["echo", "rm"]),
            ("echo \"count: $(ls | wc -l)\"", ["echo", "ls", "wc"]),
            ("echo `git push --force`", ["echo", "git"]),
            ("sh -c 'rm -rf build/'", ["sh", "rm"]),
            ("bash -lc \"rm -rf build/\"", ["bash", "rm"]),
            ("bash -ic 'cd /x && make'", ["bash", "cd", "make"]),
            ("zsh -c 'a; b'", ["zsh", "a", "b"]),
            ("eval \"rm -rf $DIR\"", ["eval", "rm"]),
            ("find . -name '*.pyc' | xargs rm -rf", ["find", "xargs", "rm"]),
            ("xargs -0 -n 1 rm -f < list.txt", ["xargs", "rm"]),
            ("find . -type f -exec rm -f {} \\;", ["find", "rm"]),
            ("find . -execdir shred {} +", ["find", "shred"]),
            ("sudo sh -c 'echo x > /etc/y'", ["sh", "echo"]),
            ("timeout 5 watch -n 2 'rm -rf a; ls'", ["rm -rf a; ls", "rm", "ls"]),
            ("diff <(sort a) <(sort b)", ["diff", "sort", "sort"]),
            ("trap 'rm -rf \"$TMP\"' EXIT", ["trap", "rm"]),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(programs(command), expected)

    def test_nested_segments_are_marked(self):
        parsed = ad_shell.parse("bash -c 'rm -rf x'")
        self.assertEqual([segment.nested for segment in parsed.segments], [False, True])

    def test_xargs_keeps_the_options_of_the_command_it_runs(self):
        self.assertEqual(argvs("xargs -I{} rm -rf {}")[1], ["rm", "-rf", "{}"])

    def test_quoted_text_of_non_executing_programs_is_not_nested(self):
        cases = [
            "git commit -m \"docs: never run rm -rf on the data dir\"",
            "grep -rn \"DROP TABLE\" migrations",
            "echo \"Do not run terraform destroy here\"",
            "printf '%s\\n' 'git push --force'",
        ]
        for command in cases:
            with self.subTest(command=command):
                self.assertEqual(len(ad_shell.parse(command).segments), 1)

    def test_literal_assignments_resolve_a_computed_program(self):
        self.assertEqual(programs("X=rm; $X -rf build/"), ["", "rm"])
        self.assertEqual(argvs("CMD=\"rm -rf build\"; $CMD")[1], ["rm", "-rf", "build"])

    def test_deep_nesting_stops_without_error(self):
        command = "echo hi"
        for _ in range(12):
            command = "sh -c %s" % ("'" + command.replace("'", "'\\''") + "'")
        self.assertTrue(ad_shell.parse(command).ok)


class HeredocTests(unittest.TestCase):

    def test_heredoc_body_is_data(self):
        command = "cat > NOTES.md <<'EOF'\nNever run `rm -rf /`\ngit push --force\nEOF\necho done"
        parsed = ad_shell.parse(command)
        self.assertTrue(parsed.ok)
        self.assertEqual([ad_shell.program(segment.argv) for segment in parsed.segments], ["cat", "echo"])
        self.assertIn("rm -rf /", parsed.segments[0].heredoc)
        self.assertEqual(parsed.segments[0].redirects, [(">", "NOTES.md")])

    def test_heredoc_variants(self):
        cases = [
            ("psql <<EOF\nDELETE FROM users;\nEOF", "DELETE FROM users;"),
            ("psql <<-EOF\n\tDELETE FROM users;\n\tEOF", "\tDELETE FROM users;"),
            ("psql <<\"SQL\"\nSELECT 1;\nSQL", "SELECT 1;"),
            ("psql <<< \"DELETE FROM users;\"", "DELETE FROM users;"),
            ("psql <<EOF\nno terminator", "no terminator"),
        ]
        for command, body in cases:
            with self.subTest(command=command):
                segment = ad_shell.parse(command).segments[0]
                self.assertEqual(segment.argv, ["psql"])
                self.assertEqual(segment.heredoc, body)

    def test_text_echoed_through_a_pipe_is_the_stdin_of_the_next_segment(self):
        parsed = ad_shell.parse("echo \"DROP DATABASE app\" | mysql -uroot")
        self.assertEqual(parsed.segments[1].heredoc, "DROP DATABASE app")

    def test_heredoc_fed_to_a_shell_is_parsed_as_commands(self):
        self.assertEqual(programs("bash <<EOF\nrm -rf /x\nEOF"), ["bash", "rm"])
        self.assertEqual(programs("bash script.sh <<EOF\nrm -rf /x\nEOF"), ["bash"])


class WrapperTests(unittest.TestCase):

    def test_strip_wrappers(self):
        cases = [
            ("sudo rm -rf x", ["rm", "-rf", "x"]),
            ("sudo -u postgres -H dropdb production", ["dropdb", "production"]),
            ("sudo -- rm x", ["rm", "x"]),
            ("doas -u root rm x", ["rm", "x"]),
            ("env rm -rf x", ["rm", "-rf", "x"]),
            ("env -i -u FOO A=1 B=2 rm x", ["rm", "x"]),
            ("A=1 B=2 rm x", ["rm", "x"]),
            ("nohup rm x", ["rm", "x"]),
            ("time -p rm x", ["rm", "x"]),
            ("nice -n 5 rm x", ["rm", "x"]),
            ("ionice -c 3 rm x", ["rm", "x"]),
            ("timeout -s KILL 5m rm x", ["rm", "x"]),
            ("timeout --signal=KILL 10 rm x", ["rm", "x"]),
            ("stdbuf -oL -eL rm x", ["rm", "x"]),
            ("command rm x", ["rm", "x"]),
            ("builtin cd /x", ["cd", "/x"]),
            ("exec rm x", ["rm", "x"]),
            ("setsid -w rm x", ["rm", "x"]),
            ("watch -n 5 rm x", ["rm", "x"]),
            ("sudo env X=1 nice -n 5 timeout 3 /bin/rm -rf x", ["/bin/rm", "-rf", "x"]),
            ("command -v rm", []),
            ("FOO=bar", []),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(ad_shell.strip_wrappers(command.split()), expected)

    def test_program_is_the_basename_after_wrappers(self):
        cases = [("/bin/rm -rf x", "rm"), ("sudo /usr/bin/git push", "git"), ("./gradlew test", "gradlew"),
                 ("X=1", ""), ("", "")]
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(ad_shell.program(command.split()), expected)

    def test_argv_keeps_the_wrappers(self):
        self.assertEqual(argvs("sudo rm x"), [["sudo", "rm", "x"]])


class RedirectTests(unittest.TestCase):

    def test_file_targets(self):
        cases = [
            ("echo hi > out/log.txt", [(">", "out/log.txt")]),
            ("echo hi >> log.txt", [(">>", "log.txt")]),
            ("echo hi >| log.txt", [(">|", "log.txt")]),
            ("cmd &> all.log", [("&>", "all.log")]),
            ("cmd &>> all.log", [("&>>", "all.log")]),
            ("cmd 2> err.txt", [("2>", "err.txt")]),
            ("cmd 2>err.txt >>out.txt", [("2>", "err.txt"), (">>", "out.txt")]),
            ("cmd 3>trace.log", [("3>", "trace.log")]),
            ("cmd >\"my file.txt\"", [(">", "my file.txt")]),
            ("> empty.txt", [(">", "empty.txt")]),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(ad_shell.parse(command).segments[0].redirects, expected)

    def test_fd_duplications_and_inputs_are_not_file_targets(self):
        for command in ("pytest tests/unit 2>&1 | tail -50", "echo warn >&2", "cmd 2>&-", "sort < input.txt",
                        "cmd <&3", "wc -l <<< text"):
            with self.subTest(command=command):
                self.assertEqual(ad_shell.parse(command).segments[0].redirects, [])

    def test_fd_number_must_touch_the_operator(self):
        segment = ad_shell.parse("echo 2 > two.txt").segments[0]
        self.assertEqual(segment.argv, ["echo", "2"])
        self.assertEqual(segment.redirects, [(">", "two.txt")])


class CwdHintTests(unittest.TestCase):

    def hints(self, command):
        return [(ad_shell.program(segment.argv), segment.cwd_hint) for segment in ad_shell.parse(command).segments]

    def test_cd_applies_to_later_segments(self):
        self.assertEqual(self.hints("cd build && rm -rf *"), [("cd", None), ("rm", "build")])
        self.assertEqual(self.hints("cd / ; rm -r -f etc"), [("cd", None), ("rm", "/")])
        self.assertEqual(self.hints("cd a && cd b && ls"), [("cd", None), ("cd", "a"), ("ls", "a/b")])
        self.assertEqual(self.hints("cd a && cd /abs && ls")[-1], ("ls", "/abs"))
        self.assertEqual(self.hints("cd build || exit 1; rm x")[-1], ("rm", "build"))
        self.assertEqual(self.hints("cd && ls")[-1], ("ls", "~"))
        self.assertEqual(self.hints("pushd sub; ls")[-1], ("ls", "sub"))

    def test_cd_in_subshell_or_pipeline_does_not_leak(self):
        self.assertEqual(self.hints("(cd /tmp && ls); rm y"), [("cd", None), ("ls", "/tmp"), ("rm", None)])
        self.assertEqual(self.hints("cd /x | cat; rm y")[-1], ("rm", None))
        self.assertEqual(self.hints("cd /x & rm y")[-1], ("rm", None))

    def test_unknown_target_is_marked_unresolvable(self):
        self.assertEqual(self.hints("cd - && rm x")[-1], ("rm", "$OLDPWD"))
        self.assertEqual(self.hints("cd \"$DIR\" && rm x")[-1], ("rm", "$DIR"))

    def test_nested_commands_inherit_and_keep_their_own_cd(self):
        self.assertEqual(self.hints("cd a && sh -c 'cd b && rm x'")[-1], ("rm", "a/b"))
        self.assertEqual(self.hints("sh -c 'cd /etc && ls'; rm x")[-1], ("rm", None))


class OptionTests(unittest.TestCase):

    def test_scan_options(self):
        options, operands = ad_shell.scan_options(
            ["-sSLo", "out.bin", "--output=x", "--max-time", "5", "-v", "url", "--", "-not-an-option"],
            "o", ("--max-time",))
        self.assertEqual(options, [("-s", None), ("-S", None), ("-L", None), ("-o", "out.bin"), ("--output", "x"),
                                   ("--max-time", "5"), ("-v", None)])
        self.assertEqual(operands, ["url", "-not-an-option"])
        self.assertEqual(ad_shell.option_value(options, "-o", "--output"), "x")
        self.assertTrue(ad_shell.has_option(options, "-v"))
        self.assertFalse(ad_shell.has_option(options, "-z"))

    def test_attached_short_value(self):
        options, _ = ad_shell.scan_options(["-ofile.txt"], "o")
        self.assertEqual(options, [("-o", "file.txt")])

    def test_git_subcommand_skips_global_options(self):
        cases = [
            (["push", "--force"], "push", ["--force"]),
            (["-C", ".", "push", "origin"], "push", ["origin"]),
            (["--no-pager", "-c", "a.b=c", "log"], "log", []),
            (["--git-dir=/x/.git", "status"], "status", []),
            (["--version"], "", []),
        ]
        for args, subcommand, rest in cases:
            with self.subTest(args=args):
                _, found, found_rest = ad_shell.git_subcommand(args)
                self.assertEqual((found, found_rest), (subcommand, rest))


class FetchTests(unittest.TestCase):

    def fetched(self, command):
        return [(fetch["program"], fetch["urls"], fetch["output"])
                for fetch in ad_shell.fetches(ad_shell.parse(command))]

    def test_fetch_programs_and_outputs(self):
        url = "https://files.example.org/u/123/dataset.cram"
        cases = [
            ("curl -L -o dataset.cram " + url, [("curl", [url], "dataset.cram")]),
            ("curl -sSLo out.bin " + url, [("curl", [url], "out.bin")]),
            ("curl -L --output=model.bin " + url, [("curl", [url], "model.bin")]),
            ("curl -LO " + url, [("curl", [url], "dataset.cram")]),
            ("curl -L -O \"" + url + "#frag\"", [("curl", [url + "#frag"], "dataset.cram")]),
            ("curl -L " + url + " > local.cram", [("curl", [url], "local.cram")]),
            ("curl -s " + url, [("curl", [url], None)]),
            ("curl -H 'Accept: x' -X POST -d a=b " + url, [("curl", [url], None)]),
            ("curl --output-dir dl -O " + url, [("curl", [url], "dl/dataset.cram")]),
            ("wget " + url, [("wget", [url], "dataset.cram")]),
            ("wget -q -O /data/g.cram " + url, [("wget", [url], "/data/g.cram")]),
            ("wget -P downloads " + url, [("wget", [url], "downloads/dataset.cram")]),
            ("wget https://example.org/", [("wget", ["https://example.org/"], "index.html")]),
            ("aria2c -x 8 -d dl -o g.cram " + url, [("aria2c", [url], "dl/g.cram")]),
            ("scp host:/data/x.bam .", [("scp", ["host:/data/x.bam"], ".")]),
            ("rsync -av user@host:/data/x.bam data/", [("rsync", ["user@host:/data/x.bam"], "data/")]),
            ("gsutil -m cp gs://bucket/u/x.cram .", [("gsutil cp", ["gs://bucket/u/x.cram"], ".")]),
            ("aws --profile me s3 cp s3://bucket/k.cram .", [("aws s3 cp", ["s3://bucket/k.cram"], ".")]),
            ("aws s3 sync s3://bucket/dir local/", [("aws s3 sync", ["s3://bucket/dir"], "local/")]),
            ("gcloud storage cp gs://b/x.bin .", [("gcloud storage cp", ["gs://b/x.bin"], ".")]),
            ("gdown -O model.bin 1AbCdEf", [("gdown", ["1AbCdEf"], "model.bin")]),
            ("git clone https://github.com/a/b.git", [("git clone", ["https://github.com/a/b.git"], "b")]),
            ("git clone --depth 1 https://github.com/a/b dest",
             [("git clone", ["https://github.com/a/b"], "dest")]),
            ("pip download -d wheels requests", [("pip download", ["requests"], "wheels")]),
            ("python3 -m pip download requests", [("pip download", ["requests"], None)]),
            ("huggingface-cli download acme/m model.safetensors --local-dir models",
             [("huggingface-cli download", ["hf://acme/m/model.safetensors"], "models/model.safetensors")]),
            ("hf download acme/datasets", [("hf download", ["hf://acme/datasets"], None)]),
            ("sudo timeout 60 curl -LO " + url, [("curl", [url], "dataset.cram")]),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(self.fetched(command), expected)

    def test_uploads_copies_and_mentions_are_not_fetches(self):
        cases = [
            "scp dist/app.tar.gz deploy@staging:/srv/releases/",
            "rsync -a data/sample.vcf.gz backup/",
            "aws s3 cp build/site.zip s3://acme-artifacts/site.zip",
            "gsutil cp local.bin gs://bucket/local.bin",
            "git commit -m \"replace curl with requests when fetching data.zip\"",
            "echo curl -LO https://example.org/x.iso",
            "sort -o results.csv results.csv",
            "git pull",
            "pip install requests",
        ]
        for command in cases:
            with self.subTest(command=command):
                self.assertEqual(self.fetched(command), [])

    def test_cwd_hint_travels_with_the_fetch(self):
        fetch = ad_shell.fetches(ad_shell.parse("cd data && curl -LO https://example.org/a.bin"))[0]
        self.assertEqual(fetch["cwd_hint"], "data")

    def test_url_basename(self):
        cases = [("https://e.org/a/b.bin?x=1#frag", "b.bin"), ("https://e.org", ""), ("host:/data/x.bam", "x.bam"),
                 ("s3://bucket/dir/k.cram", "k.cram"), ("https://e.org/dir/", "dir")]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(ad_shell.url_basename(url), expected)


if __name__ == "__main__":
    unittest.main()
