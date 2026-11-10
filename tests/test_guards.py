"""Tests for lib/ad_guards.py: approvals, destructive classification, write targets, scope fence,
fetch guard, retry rule and the hook entrypoints (run as the host runs them)."""
import datetime
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import ad_core  # noqa: E402
import ad_gates  # noqa: E402
import ad_shell  # noqa: E402
import ad_state  # noqa: E402
import ad_guards  # noqa: E402

AD = os.path.join(LIB, "ad.py")
UTC = datetime.timezone.utc
START = datetime.datetime(2030, 3, 1, 9, 0, 0, tzinfo=UTC)
PROJECT = "/home/dev/proj"
HOME = "/home/dev"


class GuardCase(unittest.TestCase):
    """Base class: temp directory, own AGENT_STATE_DIR, fixed HOME, injected clock.

    The modelled project is `/home/dev/proj`. It does not exist: path checks only resolve
    names, so nothing is written outside the temp directory.
    """

    @classmethod
    def setUpClass(cls):
        importlib.reload(ad_core)
        importlib.reload(ad_gates)
        importlib.reload(ad_state)
        importlib.reload(ad_guards)

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="ad-guards-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = dict(os.environ)
        self.addCleanup(self._restore_env, saved)
        for name in list(os.environ):
            if name.startswith("AD_") or name in ("AGENT_STATE_DIR", "CLAUDE_PROJECT_DIR", "TMPDIR"):
                del os.environ[name]
        self.state = os.path.join(self.tmp, "state")
        os.environ["AGENT_STATE_DIR"] = self.state
        os.environ["HOME"] = HOME
        ad_core.set_start_dir(self.tmp)
        self.addCleanup(ad_core.set_start_dir, None)
        self.clock = START
        original_clock = ad_core.time_now
        ad_core.time_now = lambda: self.clock
        self.addCleanup(setattr, ad_core, "time_now", original_clock)

    @staticmethod
    def _restore_env(saved):
        os.environ.clear()
        os.environ.update(saved)

    def tick(self, **delta):
        self.clock = self.clock + datetime.timedelta(**delta)

    def declare_project(self):
        ad_guards.scope_set([PROJECT])

    def bash(self, command, cwd=PROJECT, **extra):
        payload = {"session_id": "S1", "hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": cwd,
                   "tool_input": {"command": command}}
        payload.update(extra)
        return payload

    def fence(self, command, cwd=PROJECT, **extra):
        return ad_guards.scope_fence_decide(self.bash(command, cwd, **extra))

    def labels(self, command):
        return [label for label, _ in ad_guards.classify(ad_shell.parse(command), command)]

    def write_file(self, relative, size=10):
        path = os.path.join(self.tmp, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"x" * size)
        return path


class ApprovalTests(GuardCase):

    def test_normalize_command(self):
        self.assertEqual(ad_guards.normalize_command("  rm   -rf \n build/ "), "rm -rf build/")
        self.assertEqual(ad_guards.normalize_command(None), "")

    def test_exact_command_only(self):
        ad_guards.approve("rm -rf build/")
        self.assertTrue(ad_guards.is_approved("rm -rf build/"))
        self.assertTrue(ad_guards.is_approved("  rm  -rf   build/ "))
        for other in ("rm -rf build/ ~/", "rm -rf build", "rm -fr build/", "sudo rm -rf build/",
                      "rm -rf build/; terraform destroy", "echo rm -rf build/", ""):
            with self.subTest(other=other):
                self.assertFalse(ad_guards.is_approved(other))

    def test_expires_after_default_30_minutes(self):
        ad_guards.approve("git push origin main")
        self.tick(minutes=29)
        self.assertTrue(ad_guards.is_approved("git push origin main"))
        self.tick(minutes=2)
        self.assertFalse(ad_guards.is_approved("git push origin main"))
        self.assertEqual(ad_guards.approvals_show(), "no approvals")

    def test_lifetime_from_argument_environment_and_maximum(self):
        ad_guards.approve("a", minutes=5)
        self.tick(minutes=6)
        self.assertFalse(ad_guards.is_approved("a"))
        os.environ["AD_APPROVAL_MINUTES"] = "2"
        ad_guards.approve("b")
        self.tick(minutes=3)
        self.assertFalse(ad_guards.is_approved("b"))
        os.environ["AD_APPROVAL_MINUTES"] = "not-a-number"
        ad_guards.approve("c")
        self.tick(minutes=29)
        self.assertTrue(ad_guards.is_approved("c"))
        message = ad_guards.approve("d", minutes=999999)
        self.assertIn("1440 minutes", message)

    def test_bad_arguments_raise_value_error(self):
        for arguments in (("",), ("   ",), ("x", 0), ("x", -5), ("x", "soon")):
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    ad_guards.approve(*arguments)

    def test_expired_entries_are_pruned_on_write(self):
        ad_guards.approve("old command")
        self.tick(hours=2)
        ad_guards.approve("new command")
        stored = ad_core.load_json("approvals.json", [])
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["preview"], "new command")

    def test_stored_entry_has_hash_and_redacted_preview_not_the_command(self):
        ad_guards.approve("curl -H 'Authorization: Bearer abc123secret' https://example.org/" + "x" * 300,
                          note="user said yes")
        entry = ad_core.load_json("approvals.json", [])[0]
        self.assertEqual(sorted(entry), ["created", "expires", "note", "preview", "sha256"])
        self.assertEqual(len(entry["sha256"]), 64)
        self.assertLessEqual(len(entry["preview"]), 161)
        self.assertNotIn("abc123secret", json.dumps(entry))
        self.assertEqual(entry["note"], "user said yes")

    def test_show_and_clear(self):
        self.assertEqual(ad_guards.approvals_show(), "no approvals")
        self.assertEqual(ad_guards.approvals_clear(), "no approvals")
        self.assertFalse(os.path.exists(self.state))
        ad_guards.approve("rm -rf build/")
        self.assertIn("rm -rf build/", ad_guards.approvals_show())
        self.assertEqual(ad_guards.approvals_clear(), "approvals cleared (1)")
        self.assertFalse(ad_guards.is_approved("rm -rf build/"))

    def test_reading_never_creates_the_state_directory(self):
        self.assertFalse(ad_guards.is_approved("rm -rf build/"))
        self.fence("rm -rf build/")
        ad_guards.scope_show()
        self.assertFalse(os.path.exists(self.state))

    def test_ledger_text_never_unlocks(self):
        self.declare_project()
        ad_state.ledger_add("GRANT", "recursive delete: rm -rf build/")
        ad_state.ledger_add("GRANT", "edit any file under src/ and tests/ without asking")
        self.assertFalse(hasattr(ad_guards, "has_grant"))
        self.assertIsNotNone(self.fence("rm -rf build/"))
        self.assertIsNotNone(self.fence("rm -rf src/ tests/"))

    def test_garbage_in_the_approvals_file_is_ignored(self):
        ad_core.save_json("approvals.json", [None, "x", {"sha256": 5}, {"expires": "never"}])
        self.assertFalse(ad_guards.is_approved("rm -rf build/"))
        ad_core.save_json("approvals.json", {"not": "a list"})
        self.assertFalse(ad_guards.is_approved("rm -rf build/"))


DESTRUCTIVE = [
    # recursive delete: spellings, wrappers, quoting, nesting
    ("rm -rf build/", "recursive delete"),
    ("rm -fr build/", "recursive delete"),
    ("rm -r -f build/", "recursive delete"),
    ("rm -f -r build/", "recursive delete"),
    ("rm --recursive --force build/", "recursive delete"),
    ("rm -Rf build/", "recursive delete"),
    ("rm -fR build/", "recursive delete"),
    ("rm -rfv build/", "recursive delete"),
    ("rm -vrf build/", "recursive delete"),
    ("/bin/rm -rf build/", "recursive delete"),
    ("sudo rm -rf build/", "recursive delete"),
    ("env rm -rf build/", "recursive delete"),
    ("command rm -rf build/", "recursive delete"),
    ("\\rm -rf build/", "recursive delete"),
    ("nohup rm -rf build/ &", "recursive delete"),
    ("time rm -rf build/", "recursive delete"),
    ("sh -c 'rm -rf build/'", "recursive delete"),
    ("bash -lc \"rm -rf build/\"", "recursive delete"),
    ("\"rm\" -rf build/", "recursive delete"),
    ("r\\m -rf build/", "recursive delete"),
    ("rm \"-rf\" build/", "recursive delete"),
    ("X=rm; $X -rf build/", "recursive delete"),
    ("xargs rm -rf < list.txt", "recursive delete"),
    ("echo $(rm -rf build/)", "recursive delete"),
    ("if true; then rm -rf build/; fi", "recursive delete"),
    ("rm -r -f /", "recursive delete"),
    ("rm -Rf ~", "recursive delete"),
    ("rm -r -f \"$HOME\"", "recursive delete"),
    ("rm -Rf ${HOME}", "recursive delete"),
    ("rm -r /", "recursive delete"),
    ("rm -r ~", "recursive delete"),
    ("rm -R $HOME", "recursive delete"),
    ("rm -r .", "recursive delete"),
    ("rm -R ..", "recursive delete"),
    ("rm -r *", "recursive delete"),
    ("rm -r /*", "recursive delete"),
    ("rm --recursive ~/", "recursive delete"),
    ("cd / && rm -r -f etc", "recursive delete"),
    ("rm -rf / --no-preserve-root", "recursive delete"),
    # find delete
    ("find . -delete", "find delete"),
    ("find ~/Downloads -mtime +30 -delete", "find delete"),
    ("find . -type f -exec rm -f {} \\;", "find delete"),
    ("find . -name '*.log' -execdir shred {} +", "find delete"),
    ("find . -ok unlink {} \\;", "find delete"),
    ("find . -name '*.pyc' | xargs rm -f", "find delete"),
    # force push
    ("git push --force origin feature", "force push"),
    ("git push -f origin feature", "force push"),
    ("git push origin feature -f", "force push"),
    ("git push origin +feature", "force push"),
    ("git push --mirror", "force push"),
    ("git push origin --delete feature", "force push"),
    ("git push origin -d feature", "force push"),
    ("git push origin :feature", "force push"),
    ("git -C . push --force origin feat", "force push"),
    ("git --no-pager push --force", "force push"),
    ("git push origin --tags --force", "force push"),
    ("git push origin 'refs/heads/*:refs/heads/*' --force", "force push"),
    ("sudo git push -f", "force push"),
    # push to protected branch
    ("git push origin main", "push to protected branch"),
    ("git push origin master", "push to protected branch"),
    ("git push -u origin main", "push to protected branch"),
    ("git push origin HEAD:main", "push to protected branch"),
    ("git push origin feature:main", "push to protected branch"),
    ("git push origin refs/heads/main", "push to protected branch"),
    ("git push origin HEAD:refs/heads/master", "push to protected branch"),
    ("git push origin +HEAD:main", "push to protected branch"),
    ("git push --force-with-lease origin main", "push to protected branch"),
    ("git push origin $(git rev-parse HEAD):main", "push to protected branch"),
    # discards uncommitted work
    ("git reset --hard", "discards uncommitted work"),
    ("git reset --hard HEAD~3", "discards uncommitted work"),
    ("git clean -fdx", "discards uncommitted work"),
    ("git clean -d -f -x", "discards uncommitted work"),
    ("git clean --force -d", "discards uncommitted work"),
    ("git checkout -- .", "discards uncommitted work"),
    ("git checkout -- src/app.py", "discards uncommitted work"),
    ("git checkout HEAD~1 -- .", "discards uncommitted work"),
    ("git checkout .", "discards uncommitted work"),
    ("git checkout -f", "discards uncommitted work"),
    ("git restore .", "discards uncommitted work"),
    ("git restore src/app.py", "discards uncommitted work"),
    ("git restore --worktree --source=origin/main :/", "discards uncommitted work"),
    ("git restore --staged --worktree src/app.py", "discards uncommitted work"),
    ("git switch --discard-changes main", "discards uncommitted work"),
    ("git stash drop", "discards uncommitted work"),
    ("git stash drop stash@{2}", "discards uncommitted work"),
    ("git stash clear", "discards uncommitted work"),
    # history rewrite
    ("git filter-branch --tree-filter 'rm secrets.txt' HEAD", "history rewrite"),
    ("git filter-repo --path secrets --invert-paths", "history rewrite"),
    ("git reflog expire --expire=now --all", "history rewrite"),
    ("git update-ref -d HEAD", "history rewrite"),
    ("GIT_DIR=/srv/repo.git git update-ref -d HEAD", "history rewrite"),
    ("git branch -D feature", "history rewrite"),
    # destructive SQL
    ("psql -c \"DROP TABLE users;\"", "destructive SQL"),
    ("psql -c 'drop schema public cascade;'", "destructive SQL"),
    ("psql -c \"DELETE FROM users;\"", "destructive SQL"),
    ("psql -c 'DELETE FROM users'", "destructive SQL"),
    ("psql mydb -c \"UPDATE users SET email = NULL;\"", "destructive SQL"),
    ("psql -c \"DELETE FROM users WHERE 1=1;\"", "destructive SQL"),
    ("psql -d app -c \"delete from users where 'a'='a'\"", "destructive SQL"),
    ("psql -c \"TRUNCATE users\"", "destructive SQL"),
    ("psql -c \"ALTER TABLE users DROP COLUMN email;\"", "destructive SQL"),
    ("echo \"DELETE FROM users;\" | psql", "destructive SQL"),
    ("psql <<< \"DELETE FROM users;\"", "destructive SQL"),
    ("psql <<EOF\nDELETE FROM users;\nEOF", "destructive SQL"),
    ("mysql -uroot -e \"TRUNCATE TABLE orders\" shop", "destructive SQL"),
    ("mysql -h db.internal app -e \"drop table if exists users, orders\"", "destructive SQL"),
    ("echo \"DROP DATABASE app\" | mysql -uroot", "destructive SQL"),
    ("sqlite3 app.db 'DROP INDEX idx_users'", "destructive SQL"),
    ("duckdb analytics.db \"DROP TABLE raw_events\"", "destructive SQL"),
    ("clickhouse-client -q \"TRUNCATE TABLE events\"", "destructive SQL"),
    ("mongosh \"$MONGO_URL\" --eval \"db.dropDatabase()\"", "destructive SQL"),
    ("mongosh --quiet --eval \"db.getSiblingDB('app').users.drop()\"", "destructive SQL"),
    ("redis-cli FLUSHDB", "destructive SQL"),
    ("redis-cli -h cache flushall", "destructive SQL"),
    ("sudo -u postgres dropdb app", "destructive SQL"),
    ("prisma migrate reset --force", "destructive SQL"),
    ("npx prisma migrate reset", "destructive SQL"),
    ("rails db:drop db:create", "destructive SQL"),
    ("bundle exec rails db:reset", "destructive SQL"),
    ("python manage.py flush --noinput", "destructive SQL"),
    ("alembic downgrade base", "destructive SQL"),
    # production data
    ("psql \"$PROD_DATABASE_URL\" -c \"select 1\"", "production data"),
    ("psql \"$DATABASE_URL_PRODUCTION\" -c \"select 1\"", "production data"),
    ("PGPASSWORD=x psql -h prod.db.acme.com -U admin app -f fix.sql", "production data"),
    ("PGHOST=prod-db.internal psql -c 'select 1'", "production data"),
    ("ENV=production python manage.py migrate", "production data"),
    ("export RAILS_ENV=production; rails db:migrate", "production data"),
    ("alembic -x env=production upgrade head", "production data"),
    ("npx prisma migrate deploy --schema prod/schema.prisma", "production data"),
    ("supabase db push --env live", "production data"),
    ("knex migrate:latest -e live", "production data"),
    ("mysql -h acme-prod -e 'select 1'", "production data"),
    # infrastructure delete
    ("terraform destroy", "infrastructure delete"),
    ("terraform -chdir=infra destroy", "infrastructure delete"),
    ("terraform apply -destroy -auto-approve", "infrastructure delete"),
    ("kubectl delete pods --all", "infrastructure delete"),
    ("kubectl -n prod delete deployment api", "infrastructure delete"),
    ("kubectl --context production delete deployment api", "infrastructure delete"),
    ("helm uninstall api", "infrastructure delete"),
    ("helm delete api -n staging", "infrastructure delete"),
    ("aws ec2 terminate-instances --instance-ids i-123", "infrastructure delete"),
    ("aws dynamodb delete-table --table-name users", "infrastructure delete"),
    ("aws --profile me s3 rb s3://acme-backups --force", "infrastructure delete"),
    ("aws s3 rm s3://acme-backups --recursive", "infrastructure delete"),
    ("gcloud compute instances delete web-1 --zone us-central1-a -q", "infrastructure delete"),
    ("az vm delete -g rg -n vm1 --yes", "infrastructure delete"),
    ("gsutil -m rm -r gs://acme-backups", "infrastructure delete"),
    ("gsutil rb gs://acme-backups", "infrastructure delete"),
    ("docker system prune -af --volumes", "infrastructure delete"),
    ("docker volume rm pgdata", "infrastructure delete"),
    ("docker volume prune -f", "infrastructure delete"),
    ("docker compose down -v", "infrastructure delete"),
    ("docker-compose down --volumes", "infrastructure delete"),
    ("gh repo delete acme/api --yes", "infrastructure delete"),
    ("pulumi destroy --yes", "infrastructure delete"),
    # publish or deploy
    ("npm publish", "publish or deploy"),
    ("npm publish --access public", "publish or deploy"),
    ("pnpm publish", "publish or deploy"),
    ("yarn publish --new-version 2.0.0", "publish or deploy"),
    ("npm unpublish acme-lib --force", "publish or deploy"),
    ("twine upload dist/*", "publish or deploy"),
    ("python -m twine upload dist/*", "publish or deploy"),
    ("cargo publish", "publish or deploy"),
    ("gem push acme-1.0.gem", "publish or deploy"),
    ("vercel --prod", "publish or deploy"),
    ("vercel deploy --prebuilt --prod", "publish or deploy"),
    ("npx vercel --prod --yes", "publish or deploy"),
    ("netlify deploy --dir=dist --prod", "publish or deploy"),
    ("firebase deploy --only hosting", "publish or deploy"),
    ("gh pr merge 41 --admin --squash", "publish or deploy"),
    ("gh release create v1.0.0", "publish or deploy"),
    ("gh release delete v1.0.0 -y", "publish or deploy"),
    ("docker push acme/api:latest", "publish or deploy"),
    # system destructive
    ("mkfs.ext4 /dev/sdb1", "system destructive"),
    ("sudo mkfs -t ext4 /dev/sdb1", "system destructive"),
    ("dd if=/dev/zero of=/dev/sda bs=1M", "system destructive"),
    ("dd of=/dev/sda if=/dev/zero bs=1M", "system destructive"),
    ("shred -u secrets.txt", "system destructive"),
    ("sudo shutdown -h now", "system destructive"),
    ("reboot", "system destructive"),
    ("halt", "system destructive"),
    ("poweroff", "system destructive"),
    ("kill -9 -1", "system destructive"),
    ("killall node", "system destructive"),
    ("crontab -r", "system destructive"),
    ("chmod -R 777 /", "system destructive"),
    ("chmod -R 777 ~", "system destructive"),
    ("chown -R nobody $HOME", "system destructive"),
    (":(){ :|:& };:", "system destructive"),
    ("cat image.iso > /dev/sda", "system destructive"),
    # inline delete code
    ("python3 -c \"import shutil; shutil.rmtree('/home/dev')\"", "inline delete code"),
    ("python -c 'import os; os.remove(\"x\")'", "inline delete code"),
    ("python3 -c 'import os; os.system(\"rm -rf ~/projects\")'", "inline delete code"),
    ("node -e \"require('fs').rmSync(process.env.HOME,{recursive:true,force:true})\"", "inline delete code"),
    ("perl -e 'unlink(\"x\")'", "inline delete code"),
    ("ruby -e 'FileUtils.rm_rf(\"build\")'", "inline delete code"),
    ("ruby -e 'File.delete(\"x\")'", "inline delete code"),
    ("python3 - <<'EOF'\nimport shutil\nshutil.rmtree('build')\nEOF", "inline delete code"),
]

NOT_DESTRUCTIVE = [
    # quoted text of non-executing programs
    "git commit -m \"docs: never run rm -rf on the data dir\"",
    "git commit -am \"remove --force from deploy script\"",
    "git add -A && git commit -m \"wip: drop table migration draft\"",
    "grep -rn \"DROP TABLE\" migrations",
    "grep -rn 'rm -rf' scripts/",
    "rg 'git push --force' docs/",
    "git log --oneline --grep \"git push --force\"",
    "echo \"Do not run terraform destroy here\"",
    "printf '%s\\n' 'kubectl delete pods --all'",
    "gh pr create --title \"Stop using git push --force in release script\" --body \"x\"",
    "sed -n '/rm -rf/p' Makefile",
    "cat > NOTES.md <<'EOF'\nNever run `rm -rf /`\nEOF",
    "cat <<EOF\ngit push --force origin main\nDROP TABLE users;\nEOF",
    "psql -c \"SELECT 1\" && echo delete from users",
    "python3 scripts/ad.py ledger add FORBID \"never git push --force or DROP TABLE without asking\"",
    "python3 scripts/ad.py approve -- 'rm -rf build/'",
    "python3 scripts/ad.py checkpoint write \"Next: ask the user before rm -rf build\"",
    # file names and branch names that contain a dangerous word
    "ls reboot-notes.md",
    "cat docs/shutdown-procedure.md",
    "git checkout -b fix/reboot-loop",
    "git log -p -- src/rm.py",
    "git switch -c feature/delete-account",
    "git push origin feature/remove-force-flag",
    "git push --set-upstream origin fix/prod-crash",
    "git push origin main-nav-fix",
    "git push -u origin feature/prod-readiness",
    # safe spellings of risky programs
    "rm build/output.txt",
    "rm -f build/output.txt",
    "rm -r build/",
    "rm -ri build/",
    "git push",
    "git push origin feature",
    "git push origin HEAD",
    "git push --force-with-lease origin feature",
    "git push --all --force-if-includes",
    "git push --dry-run --force origin main",
    "git tag v1.2.3 && git push origin v1.2.3",
    "git fetch origin main:refs/remotes/origin/main",
    "git pull --rebase origin main",
    "git checkout main",
    "git checkout src/app.py",
    "git restore --staged src/app.py",
    "git clean -n -d",
    "git clean -nfd",
    "git reset --soft HEAD~1",
    "git reset HEAD src/app.py",
    "git stash && git pull && git stash pop",
    "git stash push -m \"before reset --hard experiment\"",
    "git branch -d merged-feature",
    "git rm --cached secrets/.env",
    "find . -name '*.py'",
    "find . -type f -exec grep -l TODO {} +",
    "psql -c \"DELETE FROM sessions WHERE expires_at < now()\"",
    "psql -c \"UPDATE users SET plan = 'free' WHERE id = 7\"",
    "psql -d shop_dev -c \"select count(*) from products\"",
    "psql -d dev -c \"select * from reproductions\"",
    "psql -d dev -f sql/liveness_probe.sql",
    "psql -d app_test -f tests/fixtures/production_like_seed.sql",
    "sqlite3 app.sqlite \".tables\"",
    "redis-cli -h localhost ping && echo \"prod untouched\"",
    "cd products && alembic upgrade head",
    "alembic upgrade head  # not prod, local sqlite",
    "npx prisma migrate dev --name add-live-flag",
    "python manage.py makemigrations && python manage.py migrate",
    "python scripts/migrate.py --dry-run --env production",
    "grep -rn \"production\" config/ | grep -v migrate",
    "cat docs/migrate-to-production.md",
    "kubectl get pods -n production",
    "kubectl logs deploy/api -n prod --tail=100",
    "kubectl apply -f k8s/dev/ --dry-run=client",
    "terraform plan -out=tfplan",
    "terraform fmt -recursive && terraform validate",
    "helm list -A",
    "aws s3 ls s3://acme-backups",
    "aws ec2 describe-instances",
    "docker compose down",
    "docker run --rm -v \"$PWD\":/work -w /work node:20 npm test",
    "docker ps -a --filter status=exited",
    "npm publish --dry-run",
    "npm install && npm test",
    "npm run build",
    "gh pr view 41",
    "gh release list",
    "dd if=/dev/zero of=/dev/null bs=1M count=1",
    "kill -9 1234",
    "kill -1 1234",
    "crontab -l",
    "chmod -R 755 build/",
    "chmod +x scripts/run.sh",
    "command -v rm",
    "python3 -c \"import json,sys; print(json.load(open('package.json'))['version'])\"",
    "python3 -c \"open('out.txt','w').write('hi')\"",
    "node -e \"console.log(require('./package.json').version)\"",
    "pytest tests/unit 2>&1 | tail -50",
]


class ClassifyTests(GuardCase):

    def test_destructive_commands_get_their_label(self):
        for command, label in DESTRUCTIVE:
            with self.subTest(command=command):
                self.assertIn(label, self.labels(command))

    def test_benign_commands_get_no_label(self):
        for command in NOT_DESTRUCTIVE:
            with self.subTest(command=command):
                self.assertEqual(self.labels(command), [])

    def test_classify_returns_label_and_detail_pairs(self):
        found = ad_guards.classify(ad_shell.parse("git push --force origin main"), "git push --force origin main")
        self.assertEqual([label for label, _ in found], ["force push", "push to protected branch"])
        for _, detail in found:
            self.assertTrue(detail)

    def test_protected_branches_from_environment(self):
        os.environ["AD_PROTECTED_BRANCHES"] = "release, production"
        self.assertEqual(self.labels("git push origin HEAD:production"), ["push to protected branch"])
        self.assertEqual(self.labels("git push origin main"), [])

    def test_unparsed_command_falls_back_to_raw_rules(self):
        cases = [
            ("rm -rf 'build", "recursive delete"),
            ("git push --force origin \"main", "force push"),
            ("psql -c \"DROP TABLE users", "destructive SQL"),
            ("terraform destroy 'x", "infrastructure delete"),
        ]
        for command, label in cases:
            with self.subTest(command=command):
                parsed = ad_shell.parse(command)
                self.assertFalse(parsed.ok)
                found = ad_guards.classify(parsed, command)
                self.assertIn(label, [name for name, _ in found])
                self.assertIn("could not be parsed", found[0][1])
        self.assertEqual(self.labels("echo 'unbalanced"), [])

    def test_unparsed_denial_says_so(self):
        reason = self.fence("rm -rf 'build")
        self.assertIn("could not be parsed", reason)


class WriteTargetTests(GuardCase):

    def targets(self, command, cwd=PROJECT):
        return ad_guards.write_targets(ad_shell.parse(command), cwd)

    def test_only_write_operands_count(self):
        cases = [
            ("echo hi > out/log.txt", [PROJECT + "/out/log.txt"]),
            ("cp /etc/ssl/certs/ca.crt certs.pem", [PROJECT + "/certs.pem"]),
            ("cp -t /opt/dest a b", ["/opt/dest"]),
            ("cp --target-directory=/opt/dest a b", ["/opt/dest"]),
            ("mv a.txt b.txt", [PROJECT + "/a.txt", PROJECT + "/b.txt"]),
            ("rm -f /etc/hosts.bak ./local.txt", ["/etc/hosts.bak", PROJECT + "/local.txt"]),
            ("rmdir /opt/oldthing", ["/opt/oldthing"]),
            ("touch /etc/cron.d/job", ["/etc/cron.d/job"]),
            ("mkdir -p -m 755 /opt/newthing", ["/opt/newthing"]),
            ("tee -a /etc/sudoers", ["/etc/sudoers"]),
            ("truncate -s 0 /var/log/app.log", ["/var/log/app.log"]),
            ("ln -sf /dev/null /etc/resolv.conf", ["/etc/resolv.conf"]),
            ("install -m 755 tool /usr/local/bin/tool", ["/usr/local/bin/tool"]),
            ("rsync -a --delete empty/ /var/www/", ["/var/www"]),
            ("rsync -a src/ user@host:/srv/app/", []),
            ("scp build.tgz deploy@host:/srv/app/", []),
            ("scp host:/data/x.bin /mnt/data/", ["/mnt/data"]),
            ("sed -i 's/foo/bar/' src/app.py", [PROJECT + "/src/app.py"]),
            ("sed -i.bak -e 's|/etc/x|/etc/y|' /etc/app.conf", ["/etc/app.conf"]),
            ("sed -n '/x/p' /etc/passwd", []),
            ("perl -pi -e 's/a/b/' $HOME/.gitconfig", [HOME + "/.gitconfig"]),
            ("chmod 644 /etc/shadow", ["/etc/shadow"]),
            ("chmod +x scripts/run.sh", [PROJECT + "/scripts/run.sh"]),
            ("chown -R nobody /usr", ["/usr"]),
            ("dd if=/dev/zero of=/var/tmp-image.img bs=1M", ["/var/tmp-image.img"]),
            ("curl -sS -o /etc/apt/x.list https://example.org/x.list", ["/etc/apt/x.list"]),
            ("curl -LO https://example.org/dir/tool.bin", [PROJECT + "/tool.bin"]),
            ("curl -s https://api.example.com/v1/health > health.json", [PROJECT + "/health.json"]),
            ("curl -s https://api.example.com/v1/health", []),
            ("wget -q -O /usr/local/bin/tool https://example.org/tool", ["/usr/local/bin/tool"]),
            ("wget -P /opt/dl https://example.org/tool.bin", ["/opt/dl/tool.bin"]),
            ("tar xzf payload.tgz -C /etc", ["/etc"]),
            ("tar -xzf payload.tgz", [PROJECT]),
            ("tar czf /mnt/backup.tgz src", ["/mnt/backup.tgz"]),
            ("tar tzf payload.tgz", []),
            ("unzip -o payload.zip -d /usr/local/bin", ["/usr/local/bin"]),
            ("unzip -l payload.zip", []),
            ("git clone https://github.com/a/b.git /srv/b", ["/srv/b"]),
            ("git clone https://github.com/a/b.git", [PROJECT + "/b"]),
            ("git -C /srv/other-repo checkout -f", ["/srv/other-repo"]),
            ("git -C /srv/other-repo status", []),
            ("cat /etc/os-release 2>/dev/null", ["/dev/null"]),
            ("pytest tests/unit 2>&1 | tail -50", []),
            ("grep -r pattern /etc /usr/share", []),
            ("ls /root", []),
            ("pip install -r requirements/dev.txt", []),
            ("docker run --rm -v \"$PWD\":/work -w /work node:20 npm test", []),
            ("sudo tee /etc/hosts < hosts.new", ["/etc/hosts"]),
            ("sh -c 'echo x > /etc/y'", ["/etc/y"]),
            ("echo $(date) > \"$(mktemp)\"", []),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(self.targets(command), expected)

    def test_home_and_cd_resolution(self):
        cases = [
            ("echo x >> ~/.ssh/authorized_keys", [HOME + "/.ssh/authorized_keys"]),
            ("echo x > $HOME/.zshrc", [HOME + "/.zshrc"]),
            ("echo x > ${HOME}/.zshrc", [HOME + "/.zshrc"]),
            ("echo x > \"$PWD/out.txt\"", [PROJECT + "/out.txt"]),
            ("cd /etc && touch passwd", ["/etc/passwd"]),
            ("cd .. && rm notes.txt", [HOME + "/notes.txt"]),
            ("cd ~ && rm notes.txt", [HOME + "/notes.txt"]),
            ("cd src && cd lib && touch x", [PROJECT + "/src/lib/x"]),
            ("(cd /etc && ls); touch here", [PROJECT + "/here"]),
            ("mv src ..", [PROJECT + "/src", HOME]),
            ("rm /tmp/../etc/hosts", ["/etc/hosts"]),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(self.targets(command), expected)

    def test_unresolved_targets_are_left_out(self):
        for command in ("rm \"$BUILD_DIR/x\"", "echo x > `mktemp`", "cd \"$DIR\" && touch x", "cd - && touch x",
                        "cp a ${DEST:-/var/tmp}"):
            with self.subTest(command=command):
                self.assertEqual(self.targets(command), [])

    def test_glob_resolves_to_the_directory_before_it(self):
        self.assertEqual(self.targets("rm build/*.o"), [PROJECT + "/build"])
        self.assertEqual(self.targets("rm /etc/*.conf"), ["/etc"])
        self.assertEqual(self.targets("mv * .."), [PROJECT, HOME])

    def test_device_files_keep_their_name(self):
        self.assertEqual(self.targets("echo warn > /dev/stderr; echo x > /dev/null"), ["/dev/stderr", "/dev/null"])


class ContainmentTests(GuardCase):

    def setUp(self):
        GuardCase.setUp(self)
        self.declare_project()

    def test_in_scope_everyday_commands_pass(self):
        commands = [
            "echo hi > out/log.txt",
            "pytest tests/unit 2>&1 | tail -50",
            "./gradlew test 2>&1 | tail -20",
            "cp src/a.py src/b.py",
            "mv docs/old.md docs/new.md",
            "sed -i 's/foo/bar/' src/app.py",
            "pip install -r requirements/dev.txt",
            "docker run --rm -v \"$PWD\":/work -w /work node:20 npm test",
            "curl -s https://api.example.com/v1/health > health.json",
            "git clone https://github.com/psf/requests.git 2>&1 | tail -3",
            "cat /etc/os-release 2>/dev/null",
            "cp /etc/ssl/certs/ca-certificates.crt certs.pem",
            "echo warn > /dev/stderr",
            "echo x > /dev/stdout",
            "echo x > /dev/tty",
            "echo x > /dev/fd/3",
            "python3 scripts/ad.py manifest check data.csv > out/check.txt",
            "mkdir -p build/out && cp README.md build/out/",
            "tee logs/run.log < /dev/null",
            "git diff main...HEAD -- src/app.py > /tmp/app.diff",
            "npm test -- --watch=false 2>&1 | tee /tmp/test.log",
            "pytest -k \"not slow\" --maxfail=1 > /var/tmp/pytest.out 2>&1",
            "rm /tmp/scratch.txt",
            "touch %s/notes.txt" % PROJECT,
            "rm \"$BUILD_DIR/x.o\"",
            "ls /etc > listing.txt",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNone(self.fence(command))

    def test_writes_outside_the_declared_roots_are_denied(self):
        cases = [
            ("echo x > /tmpfoo/file.txt", "/tmpfoo/file.txt"),
            ("cp secrets.env /tmp-backup/secrets.env", "/tmp-backup/secrets.env"),
            ("cp secrets.env /var/tmpx/secrets.env", "/var/tmpx/secrets.env"),
            ("echo x > /dev/nullx", "/dev/nullx"),
            ("rm -f /tmp/../etc/hosts", "/etc/hosts"),
            ("echo x >> ~/.ssh/authorized_keys", HOME + "/.ssh/authorized_keys"),
            ("echo \"\" > ~/.zshrc", HOME + "/.zshrc"),
            ("cat /dev/null > ../other-repo/README.md", HOME + "/other-repo/README.md"),
            (": > /var/log/syslog", "/var/log/syslog"),
            ("cp -f ~/.aws/credentials /mnt/usb/", "/mnt/usb"),
            ("tee /etc/hosts < hosts.new", "/etc/hosts"),
            ("sudo tee -a /etc/sudoers <<< \"dev ALL=(ALL) NOPASSWD:ALL\"", "/etc/sudoers"),
            ("install -m 755 tool /usr/local/bin/tool", "/usr/local/bin/tool"),
            ("touch /etc/cron.d/job", "/etc/cron.d/job"),
            ("mkdir -p /opt/newthing", "/opt/newthing"),
            ("ln -sf /dev/null /etc/resolv.conf", "/etc/resolv.conf"),
            ("tar xzf payload.tgz -C /etc", "/etc"),
            ("unzip -o payload.zip -d /usr/local/bin", "/usr/local/bin"),
            ("curl -sS -o /etc/apt/sources.list.d/x.list https://example.org/x.list", "/etc/apt/sources.list.d/x.list"),
            ("wget -q -O /usr/local/bin/tool https://example.org/tool", "/usr/local/bin/tool"),
            ("cd / && touch etc/x", "/etc/x"),
            ("cd .. && rm notes.txt", HOME + "/notes.txt"),
            ("mv src ..", HOME),
            ("touch /home/dev/projX/file", "/home/dev/projX/file"),
            ("sh -c 'echo x > /etc/y'", "/etc/y"),
        ]
        for command, path in cases:
            with self.subTest(command=command):
                reason = self.fence(command)
                self.assertIsNotNone(reason)
                self.assertIn(path, reason)
                self.assertIn("outside the declared roots", reason)
                self.assertIn("scope add", reason)

    def test_scope_add_unlocks_a_path(self):
        self.assertIsNotNone(self.fence("touch /srv/shared/schema.json"))
        ad_guards.scope_add("/srv/shared")
        self.assertIsNone(self.fence("touch /srv/shared/schema.json"))
        self.assertIsNone(self.fence("touch %s/still-inside.txt" % PROJECT))

    def test_approval_of_the_exact_command_unlocks_its_paths(self):
        command = "cp report.pdf /mnt/share/report.pdf"
        self.assertIsNotNone(self.fence(command))
        ad_guards.approve(command)
        self.assertIsNone(self.fence(command))
        self.assertIsNotNone(self.fence("cp report.pdf /mnt/share/other.pdf"))

    def test_scratchpad_from_hook_input_is_allowed(self):
        self.assertIsNotNone(self.fence("echo x > /scratch/s1/notes.txt"))
        self.assertIsNone(self.fence("echo x > /scratch/s1/notes.txt", scratchpad_dir="/scratch/s1"))

    def test_allow_regex_and_invalid_regex(self):
        ad_core.save_json("scope.json", {"roots": [PROJECT], "allow": ["(", r"^/srv/cache/"]})
        self.assertIsNone(self.fence("touch /srv/cache/x"))
        self.assertIsNotNone(self.fence("touch /srv/other/x"))
        with self.assertRaises(ValueError):
            ad_guards.scope_set([PROJECT], ["("])

    def test_malformed_scope_file_falls_back_to_the_default_root(self):
        for content in ([], {"roots": "/"}, {"roots": [5, None]}, {"roots": [], "allow": "."}):
            with self.subTest(content=content):
                ad_core.save_json("scope.json", content)
                roots, cfg = ad_guards.declared_roots(PROJECT)
                self.assertEqual(roots, [PROJECT])
                self.assertTrue(cfg["default"])
                self.assertIsNotNone(self.fence("touch /etc/passwd"))

    def test_root_slash_as_declared_root_contains_everything(self):
        ad_guards.scope_set(["/"])
        self.assertIsNone(self.fence("touch /etc/x"))

    def test_symlink_out_of_the_root_is_followed(self):
        root = os.path.join(self.tmp, "root")
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(root)
        os.makedirs(outside)
        os.symlink(outside, os.path.join(root, "conf"))
        original = ad_guards._temp_roots
        ad_guards._temp_roots = lambda: []
        self.addCleanup(setattr, ad_guards, "_temp_roots", original)
        ad_guards.scope_set([root])
        self.assertIsNone(self.fence("touch a.txt", cwd=root))
        reason = self.fence("cp evil.conf conf/hosts", cwd=root)
        self.assertIn(os.path.join(outside, "hosts"), reason)
        write = {"tool_name": "Write", "cwd": root, "tool_input": {"file_path": os.path.join(root, "conf", "hosts")}}
        self.assertIn("outside the declared roots", ad_guards.scope_fence_decide(write))

    def test_default_root_is_the_git_root(self):
        os.remove(os.path.join(self.state, "scope.json"))
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, ".git"))
        os.makedirs(os.path.join(repo, "packages", "api"))
        roots, cfg = ad_guards.declared_roots(os.path.join(repo, "packages", "api"))
        self.assertEqual(roots, [repo])
        self.assertTrue(cfg["default"])

    def test_default_root_without_git_is_the_project_directory_or_cwd(self):
        os.remove(os.path.join(self.state, "scope.json"))
        self.assertEqual(ad_guards.declared_roots("/srv/work/sub")[0], ["/srv/work/sub"])
        os.environ["CLAUDE_PROJECT_DIR"] = "/srv/work"
        self.assertEqual(ad_guards.declared_roots("/srv/work/sub")[0], ["/srv/work"])
        self.assertEqual(ad_guards.declared_roots("/elsewhere")[0], ["/elsewhere"])

    def test_scope_show_and_set(self):
        text = ad_guards.scope_set([PROJECT, "/srv/data"], [r"^/srv/cache/"])
        self.assertIn(PROJECT, text)
        self.assertIn("/srv/data", text)
        self.assertIn("^/srv/cache/", text)
        self.assertIn("scope.json", ad_guards.scope_show())
        with self.assertRaises(ValueError):
            ad_guards.scope_set([])


class ScopeFenceDecisionTests(GuardCase):

    def setUp(self):
        GuardCase.setUp(self)
        self.declare_project()

    def test_destructive_command_is_denied_with_label_preview_and_next_step(self):
        reason = self.fence("git push --force origin main")
        self.assertIn("force push", reason)
        self.assertIn("push to protected branch", reason)
        self.assertIn("`git push --force origin main`", reason)
        self.assertIn("ask the user", reason)
        self.assertIn("approve -- 'git push --force origin main'", reason)
        self.assertTrue(reason.endswith("then retry the identical command."))

    def test_preview_is_cut_at_160_characters(self):
        command = "rm -rf " + " ".join("dir%03d" % index for index in range(100))
        reason = self.fence(command)
        preview = reason.split("`")[1]
        self.assertLessEqual(len(preview), 161)

    def test_approval_unlocks_exactly_one_command_until_it_expires(self):
        command = "rm -rf build/"
        self.assertIsNotNone(self.fence(command))
        ad_guards.approve(command)
        self.assertIsNone(self.fence(command))
        for other in ("rm -rf build/ ~/", "rm -rf build/ /etc", "rm -rf build/; terraform destroy -auto-approve",
                      "rm -rf dist/", "sudo rm -rf build/"):
            with self.subTest(other=other):
                self.assertIsNotNone(self.fence(other))
        self.tick(minutes=31)
        self.assertIsNotNone(self.fence(command))

    def test_the_approve_command_itself_is_not_blocked(self):
        reason = self.fence("git push origin main")
        instruction = reason.split("run `", 1)[1].split("`, then retry", 1)[0]
        self.assertIn(" approve -- ", instruction)
        self.assertIsNone(self.fence(instruction))
        self.assertIsNone(self.fence("python3 scripts/ad.py ledger add FORBID \"never git push --force\""))

    def test_denied_benign_looking_text_is_never_scanned(self):
        for command in NOT_DESTRUCTIVE:
            with self.subTest(command=command):
                self.assertIsNone(self.fence(command))

    def test_description_field_is_never_read(self):
        payload = self.bash("npm test > test.log")
        payload["tool_input"]["description"] = "Run unit/integration tests; never rm -rf / or git push --force"
        self.assertIsNone(ad_guards.scope_fence_decide(payload))

    def test_file_tools_check_only_the_path(self):
        dangerous_text = "#!/usr/bin/env python3\nimport os  # ../lib/x https://example.com/docs rm -rf / \n"
        allowed = [
            {"tool_name": "Write", "tool_input": {"file_path": PROJECT + "/src/app.py", "content": dangerous_text}},
            {"tool_name": "Edit", "tool_input": {"file_path": PROJECT + "/.gitignore", "old_string": "/dist",
                                                 "new_string": "x = 1  // was /etc/passwd"}},
            {"tool_name": "Write", "tool_input": {"file_path": PROJECT + "/My Notes/todo.md", "content": "x"}},
            {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": PROJECT + "/nb/a.ipynb",
                                                         "new_source": "!rm -rf /"}},
            {"tool_name": "Write", "tool_input": {"file_path": "relative/file.txt", "content": "x"}},
            {"tool_name": "Write", "tool_input": {"file_path": "/tmp/scratch/x.txt", "content": "x"}},
            {"tool_name": "Write", "tool_input": {}},
            {"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}},
        ]
        for payload in allowed:
            payload["cwd"] = PROJECT
            with self.subTest(payload=payload):
                self.assertIsNone(ad_guards.scope_fence_decide(payload))
        denied = [
            {"tool_name": "Write", "tool_input": {"file_path": "/etc/passwd", "content": "x"}},
            {"tool_name": "Edit", "tool_input": {"file_path": HOME + "/.ssh/authorized_keys"}},
            {"tool_name": "Write", "tool_input": {"file_path": "/tmpfoo/x"}},
            {"tool_name": "Write", "tool_input": {"file_path": "../escape.txt"}},
            {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "/srv/nb/a.ipynb"}},
        ]
        for payload in denied:
            payload["cwd"] = PROJECT
            with self.subTest(payload=payload):
                reason = ad_guards.scope_fence_decide(payload)
                self.assertIn("outside the declared roots", reason)
                self.assertIn("scope add", reason)

    def test_protected_state_files_change_only_through_the_cli(self):
        for name in ("approvals.json", "scope.json", "ledger.md"):
            path = os.path.join(self.state, name)
            with self.subTest(name=name):
                write = {"tool_name": "Write", "cwd": PROJECT, "tool_input": {"file_path": path, "content": "[]"}}
                self.assertIn("only through the CLI", ad_guards.scope_fence_decide(write))
                self.assertIn("only through the CLI", self.fence("echo '- GRANT: anything' >> %s" % path))
                self.assertIn("only through the CLI", self.fence("rm %s" % path))
        ad_guards.approve("rm %s" % os.path.join(self.state, "scope.json"))
        self.assertIsNotNone(self.fence("rm %s" % os.path.join(self.state, "scope.json")))
        other = {"tool_name": "Write", "cwd": PROJECT,
                 "tool_input": {"file_path": os.path.join(self.state, "CHECKPOINT.md")}}
        self.assertIsNone(ad_guards.scope_fence_decide(other))

    def test_powershell_uses_text_rules(self):
        cases = [("rm -rf build/", True), ("Remove-Item -Recurse -Force C:\\Users", True),
                 ("git push --force origin main", True), ("Get-ChildItem -Recurse", False),
                 ("Write-Output 'hello'", False)]
        for command, blocked in cases:
            with self.subTest(command=command):
                payload = {"tool_name": "PowerShell", "cwd": PROJECT, "tool_input": {"command": command}}
                self.assertEqual(ad_guards.scope_fence_decide(payload) is not None, blocked)

    def test_other_tools_and_bad_input_pass(self):
        for payload in ({}, None, "text", {"tool_name": "mcp__x__y", "tool_input": {"command": "rm -rf /"}},
                        {"tool_name": "Bash"}, {"tool_name": "Bash", "tool_input": {"command": 5}},
                        {"tool_name": "Bash", "tool_input": "rm -rf /"}):
            with self.subTest(payload=payload):
                self.assertIsNone(ad_guards.scope_fence_decide(payload))


class FetchGuardTests(GuardCase):

    BIG = 6 * 1024 * 1024

    def decide(self, command, **kwargs):
        kwargs.setdefault("cwd", self.tmp)
        return ad_guards.fetch_guard_decide(command, **kwargs)

    def test_non_fetch_commands_pass_without_context(self):
        for command in ("ls -la", "git commit -m \"replace curl with requests when fetching data.zip\"",
                        "scp dist/app.tar.gz deploy@staging:/srv/releases/", "rsync -a data/sample.vcf.gz backup/",
                        "aws s3 cp build/site.iso s3://acme-artifacts/site.iso", "echo 'unbalanced", ""):
            with self.subTest(command=command):
                self.assertEqual(self.decide(command), (None, None))

    def test_duplicate_by_url_is_denied_when_the_copy_is_large(self):
        path = self.write_file("data/dataset.dat", self.BIG)
        url = "https://files.example.org/u/123/dataset.dat"
        ad_state.manifest_record(path, source="fetch", url=url)
        for command in ("curl -L -o other-name.dat " + url, "wget " + url, "curl -sL '" + url + "#frag' | wc -c",
                        "cd /srv && curl -LO " + url):
            with self.subTest(command=command):
                reason, context = self.decide(command)
                self.assertIn("already available", reason)
                self.assertIn(path, reason)
                self.assertIn("the same URL", reason)
                self.assertTrue(reason.endswith("then retry the identical command."))
                self.assertIsNone(context)

    def test_duplicate_by_output_path_and_by_unique_basename(self):
        path = self.write_file("data/model.bin", self.BIG)
        ad_state.manifest_record(path)
        reason, _ = self.decide("curl -L -o data/model.bin https://cdn.example.org/repos/aa/bb/0f3c")
        self.assertIn("the same output path", reason)
        reason, _ = self.decide("curl -L --output=data/model.bin https://cdn.example.org/repos/aa/bb/0f3c")
        self.assertIn("the same output path", reason)
        reason, _ = self.decide("cd data && curl -L https://cdn.example.org/0f3c > model.bin")
        self.assertIn("the same output path", reason)
        reason, _ = self.decide("wget https://mirror.example.org/pub/model.bin", cwd="/srv/elsewhere")
        self.assertIn("the same file name", reason)
        reason, _ = self.decide("gsutil -m cp gs://bucket/u123/model.bin .", cwd="/srv/elsewhere")
        self.assertIn("the same file name", reason)

    def test_ambiguous_basename_does_not_match(self):
        ad_state.manifest_record(self.write_file("a/model.bin", self.BIG))
        ad_state.manifest_record(self.write_file("b/model.bin", self.BIG))
        self.assertEqual(self.decide("wget https://mirror.example.org/pub/model.bin", cwd="/srv/elsewhere"),
                         (None, None))

    def test_small_copy_allows_with_a_context_note(self):
        path = self.write_file("README.md", 2000)
        ad_state.manifest_record(path)
        reason, context = self.decide("curl -sSL https://raw.githubusercontent.com/psf/requests/main/README.md")
        self.assertIsNone(reason)
        self.assertIn(path, context)
        self.assertIn("already exists", context)
        self.assertNotIn("\n", context)

    def test_threshold_from_environment(self):
        path = self.write_file("data/small.dat", 2000)
        ad_state.manifest_record(path, source="fetch", url="https://example.org/small.dat")
        os.environ["AD_FETCH_DUP_MB"] = "0.001"
        self.assertIsNotNone(self.decide("curl -LO https://example.org/small.dat")[0])
        os.environ["AD_FETCH_DUP_MB"] = "garbage"
        self.assertIsNone(self.decide("curl -LO https://example.org/small.dat")[0])

    def test_deleted_copy_no_longer_blocks(self):
        path = self.write_file("data/dataset.dat", self.BIG)
        url = "https://files.example.org/dataset.dat"
        ad_state.manifest_record(path, source="fetch", url=url)
        os.remove(path)
        self.assertEqual(self.decide("curl -LO " + url), (None, None))

    def test_approval_passes_the_duplicate_rule(self):
        path = self.write_file("data/dataset.dat", self.BIG)
        url = "https://files.example.org/dataset.dat"
        ad_state.manifest_record(path, source="fetch", url=url)
        command = "curl -LO " + url
        self.assertIsNotNone(self.decide(command)[0])
        ad_guards.approve(command)
        self.assertEqual(self.decide(command), (None, None))

    def test_large_type_rule(self):
        denied = [
            "wget https://example.org/cohort/all_samples.vcf.gz",
            "curl -LO https://example.org/wgs/sample1.cram",
            "aria2c https://example.org/images/full-disk.iso",
            "curl -L 'https://example.org/dl?id=7' -o model.safetensors",
            "wget https://huggingface.co/TheBloke/x/resolve/main/model-70b.Q8_0.gguf",
            "curl -LO https://example.org/images/ubuntu-24.04.img?download=1",
            "aws s3 cp s3://bucket/sample.bam .",
            "scp host:/data/reads.fastq.gz .",
            "hf download acme/m model.safetensors",
        ]
        for command in denied:
            with self.subTest(command=command):
                reason, _ = self.decide(command)
                self.assertIn("large-file type", reason)
                self.assertIn("inventory line", reason)
                self.assertTrue(reason.endswith("then retry the identical command."))
        allowed = [
            "curl -LO https://github.com/protocolbuffers/protobuf/releases/download/v27.0/protoc-27.0-linux-x86_64.zip",
            "curl -sL https://github.com/acme/app/archive/refs/tags/v1.0.0.tar.gz | tar xz",
            "curl -s http://localhost:8000/health && sqlite3 app.sqlite \".tables\"",
            "curl -s https://www.iso.org/standard/74528.html",
            "curl -LO https://example.org/data.csv   # size: 2 TB",
            "curl -s \"https://api.example.com/search?q=x&size=500MB\"",
            "rsync -a --max-size=200MB assets/ mirror/",
            "git clone https://github.com/torvalds/linux",
        ]
        for command in allowed:
            with self.subTest(command=command):
                self.assertEqual(self.decide(command), (None, None))

    def test_large_type_rule_respects_approval_and_environment(self):
        command = "curl -LO https://example.org/wgs/sample1.cram"
        ad_guards.approve(command)
        self.assertEqual(self.decide(command), (None, None))
        os.environ["AD_BIG_EXT"] = "zip, .parquet"
        self.assertIsNone(self.decide("curl -LO https://example.org/other.cram")[0])
        self.assertIsNotNone(self.decide("curl -LO https://example.org/data.parquet")[0])

    def test_ledger_grant_does_not_disable_the_rule(self):
        ad_state.ledger_add("GRANT", "download and fetch anything from ~/Downloads without asking")
        self.assertIsNotNone(self.decide("wget https://example.org/cohort/all_samples.vcf.gz")[0])

    def test_webfetch_duplicate_by_url_only(self):
        path = self.write_file("pages/doc.html", self.BIG)
        url = "https://docs.example.org/guide/index.html"
        ad_state.manifest_record(path, source="fetch", url=url)
        ad_state.manifest_record(self.write_file("README.md", self.BIG))
        reason, _ = self.decide("", tool_name="WebFetch", tool_input={"url": url})
        self.assertIn("already available", reason)
        self.assertIn("approve -- " + url, reason)
        for other in ("https://github.com/pallets/flask/blob/main/README.md", "https://www.iso.org/standard/74528.html",
                      "https://example.org/huge.iso", "https://www.sqlite.org/lang_select.html"):
            with self.subTest(other=other):
                self.assertEqual(self.decide("", tool_name="WebFetch", tool_input={"url": other}), (None, None))
        ad_guards.approve(url)
        self.assertEqual(self.decide("", tool_name="WebFetch", tool_input={"url": url}), (None, None))
        self.assertEqual(self.decide("", tool_name="WebFetch", tool_input=None), (None, None))

    def test_no_state_directory_is_created_by_a_check(self):
        self.decide("curl -LO https://example.org/a.txt")
        self.assertFalse(os.path.exists(self.state))


class RetryRuleTests(GuardCase):

    def log(self, command, ok=True, session="S1", tool="Bash"):
        field = "command" if tool in ("Bash", "PowerShell") else "file_path"
        payload = {"session_id": session, "tool_name": tool, "tool_input": {field: command}}
        if not ok:
            payload["error"] = "Exit code 1\nboom"
        ad_gates.log_tool(payload, failed=not ok)

    def decide(self, command, session="S1"):
        return ad_guards.validate_call_decide(self.bash(command, cwd=self.tmp, session_id=session))

    def test_two_failures_in_a_row_deny_the_third_identical_call(self):
        self.log("npm test", ok=False)
        self.assertEqual(self.decide("npm test"), (None, None))
        self.log("npm test", ok=False)
        reason, context = self.decide("npm   test ")
        self.assertIn("failed 2 times in a row", reason)
        self.assertIn("nothing changed in between", reason)
        self.assertTrue(reason.endswith("then retry the identical command."))
        self.assertIsNone(context)
        self.assertEqual(self.decide("npm test -- --verbose"), (None, None))

    def test_any_mutating_record_in_between_resets_the_count(self):
        for between_tool, between in (("Edit", "/home/dev/proj/src/app.py"), ("Bash", "ls"), ("Write", "/x/y")):
            with self.subTest(between_tool=between_tool):
                self.log("npm test", ok=False)
                self.log(between, tool=between_tool)
                self.log("npm test", ok=False)
                self.assertEqual(self.decide("npm test"), (None, None))

    def test_non_mutating_records_in_between_do_not_reset(self):
        self.log("npm test", ok=False)
        ad_gates.log_tool({"session_id": "S1", "tool_name": "WebFetch", "tool_input": {"url": "https://e.org"}})
        self.log("npm test", ok=False)
        self.assertIsNotNone(self.decide("npm test")[0])

    def test_success_or_other_session_does_not_count(self):
        self.log("tail -3 logs/ci.log")
        self.log("tail -3 logs/ci.log")
        self.assertEqual(self.decide("tail -3 logs/ci.log"), (None, None))
        self.log("make", ok=False, session="OTHER")
        self.log("make", ok=False, session="OTHER")
        self.assertEqual(self.decide("make"), (None, None))
        self.assertIsNotNone(self.decide("make", session="OTHER")[0])

    def test_limit_from_environment_and_zero_disables(self):
        for _ in range(3):
            self.log("make", ok=False)
        os.environ["AD_RETRY_LIMIT"] = "3"
        self.assertIsNotNone(self.decide("make")[0])
        os.environ["AD_RETRY_LIMIT"] = "4"
        self.assertIsNone(self.decide("make")[0])
        os.environ["AD_RETRY_LIMIT"] = "0"
        self.assertIsNone(self.decide("make")[0])
        os.environ["AD_RETRY_LIMIT"] = "two"
        self.assertIsNotNone(self.decide("make")[0])

    def test_approval_lets_the_identical_call_through(self):
        self.log("make", ok=False)
        self.log("make", ok=False)
        ad_guards.approve("make")
        self.assertEqual(self.decide("make"), (None, None))

    def test_redacted_and_long_commands_still_match_their_log_record(self):
        command = "curl -H 'Authorization: Bearer abc123secret' https://example.org/" + "a" * 600
        self.log(command, ok=False)
        self.log(command, ok=False)
        self.assertIsNotNone(self.decide(command)[0])

    def test_context_notes_never_deny(self):
        reason, context = self.decide("   ")
        self.assertIsNone(reason)
        self.assertIn("empty", context)
        ad_guards.scope_set([PROJECT])
        reason, context = ad_guards.validate_call_decide(self.bash("ls", cwd="/home/dev/projX"))
        self.assertIsNone(reason)
        self.assertIn("outside the declared roots", context)
        self.assertEqual(ad_guards.validate_call_decide(self.bash("ls", cwd=PROJECT + "/src")), (None, None))

    def test_other_tools_and_bad_input(self):
        self.assertEqual(ad_guards.validate_call_decide({"tool_name": "Read", "tool_input": {}}), (None, None))
        self.assertEqual(ad_guards.validate_call_decide(None), (None, None))


class HookTests(GuardCase):
    """Run `ad.py hook NAME` as a subprocess with payloads shaped like the documented hook input."""

    def run_hook(self, name, payload, env=None):
        environment = dict(os.environ)
        environment.update(env or {})
        completed = subprocess.run([sys.executable, AD, "hook", name], input=json.dumps(payload).encode("utf-8"),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, cwd=self.tmp,
                                   timeout=60)
        output = completed.stdout.decode("utf-8").strip()
        return completed.returncode, (json.loads(output) if output else None), completed.stderr.decode("utf-8")

    def payload(self, tool, tool_input, event="PreToolUse", **extra):
        data = {"session_id": "abc123", "transcript_path": "/home/dev/.claude/projects/x/t.jsonl", "cwd": self.tmp,
                "permission_mode": "default", "hook_event_name": event, "tool_name": tool, "tool_input": tool_input,
                "tool_use_id": "toolu_01ABC"}
        data.update(extra)
        return data

    def decision(self, output):
        return (output or {}).get("hookSpecificOutput", {}).get("permissionDecision")

    @unittest.skipUnless(os.path.isfile(AD), "ad.py is not present")
    def test_pre_bash_denies_with_json_and_exit_0(self):
        code, output, _ = self.run_hook("pre-bash", self.payload("Bash", {"command": "rm -Rf ~",
                                                                          "description": "clean up"}))
        self.assertEqual(code, 0)
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertEqual(self.decision(output), "deny")
        self.assertIn("recursive delete", output["hookSpecificOutput"]["permissionDecisionReason"])

    @unittest.skipUnless(os.path.isfile(AD), "ad.py is not present")
    def test_pre_bash_allows_ordinary_commands_silently(self):
        for command in ("echo hi > out.txt", "git commit -m \"never rm -rf\"", "pytest tests 2>&1 | tail -5"):
            with self.subTest(command=command):
                code, output, _ = self.run_hook("pre-bash", self.payload("Bash", {"command": command}))
                self.assertEqual((code, output), (0, None))

    @unittest.skipUnless(os.path.isfile(AD), "ad.py is not present")
    def test_pre_bash_approval_round_trip(self):
        payload = self.payload("Bash", {"command": "git push origin main"})
        self.assertEqual(self.decision(self.run_hook("pre-bash", payload)[1]), "deny")
        approved = subprocess.run([sys.executable, AD, "approve", "--", "git push origin main"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.tmp, env=dict(os.environ))
        self.assertEqual(approved.returncode, 0, approved.stderr)
        self.assertEqual(self.run_hook("pre-bash", payload)[:2], (0, None))

    @unittest.skipUnless(os.path.isfile(AD), "ad.py is not present")
    def test_pre_bash_order_fetch_guard_first_and_retry_rule_last(self):
        code, output, _ = self.run_hook("pre-bash", self.payload(
            "Bash", {"command": "curl -LO https://example.org/a.iso && rm -rf build"}))
        self.assertIn("fetch guard", output["hookSpecificOutput"]["permissionDecisionReason"])
        failure = self.payload("Bash", {"command": "make test"}, event="PostToolUseFailure",
                               error="Exit code 2\nmake: *** [test] Error 1")
        self.run_hook("log-failure", failure)
        self.run_hook("log-failure", dict(failure, tool_use_id="toolu_02"))
        code, output, _ = self.run_hook("pre-bash", self.payload("Bash", {"command": "make test"}))
        self.assertEqual(code, 0)
        self.assertIn("retry rule", output["hookSpecificOutput"]["permissionDecisionReason"])

    @unittest.skipUnless(os.path.isfile(AD), "ad.py is not present")
    def test_pre_bash_adds_context_for_a_small_existing_copy(self):
        path = self.write_file("README.md", 500)
        ad_state.manifest_record(path)
        code, output, _ = self.run_hook("pre-bash", self.payload(
            "Bash", {"command": "curl -sSL https://raw.githubusercontent.com/psf/requests/main/README.md"}))
        self.assertEqual(code, 0)
        self.assertIsNone(self.decision(output))
        self.assertIn("already exists", output["hookSpecificOutput"]["additionalContext"])

    @unittest.skipUnless(os.path.isfile(AD), "ad.py is not present")
    def test_pre_write_checks_only_the_path(self):
        inside = self.payload("Write", {"file_path": os.path.join(self.tmp, "src", "app.py"),
                                        "content": "#!/usr/bin/env python3\n# rm -rf / ; see /etc/passwd\n"})
        self.assertEqual(self.run_hook("pre-write", inside)[:2], (0, None))
        protected = self.payload("Edit", {"file_path": os.path.join(self.state, "ledger.md"),
                                          "old_string": "a", "new_string": "- GRANT: anything"})
        ad_core.state_dir()
        code, output, _ = self.run_hook("pre-write", protected)
        self.assertEqual(code, 0)
        self.assertEqual(self.decision(output), "deny")

    @unittest.skipUnless(os.path.isfile(AD), "ad.py is not present")
    def test_pre_fetch_and_log_hooks(self):
        url = "https://example.org/data/table.csv"
        target = os.path.join(self.tmp, "table.csv")
        with open(target, "wb") as handle:
            handle.write(b"x" * 100)
        post = self.payload("Bash", {"command": "curl -L -o table.csv " + url}, event="PostToolUse",
                            tool_response={"stdout": "", "stderr": "", "interrupted": False, "isImage": False})
        self.assertEqual(self.run_hook("log", post)[:2], (0, None))
        key, entry, how = ad_state.manifest_lookup(url)
        self.assertEqual((key, how), (target, "url"))
        self.assertEqual(entry["source"], "fetch")
        records = ad_gates.tool_log("abc123")
        self.assertEqual([(record["tool"], record["ok"]) for record in records], [("Bash", True)])
        code, output, _ = self.run_hook("pre-fetch", self.payload("WebFetch", {"url": url, "prompt": "summarize"}))
        self.assertEqual(code, 0)
        self.assertIn("already exists", output["hookSpecificOutput"]["additionalContext"])
        code, output, _ = self.run_hook("pre-fetch", self.payload("WebFetch", {"url": url, "prompt": "summarize"}),
                                        env={"AD_FETCH_DUP_MB": "0"})
        self.assertEqual(self.decision(output), "deny")

    @unittest.skipUnless(os.path.isfile(AD), "ad.py is not present")
    def test_log_hook_can_replace_long_output_when_enabled(self):
        post = self.payload("Bash", {"command": "seq 1 5000"}, event="PostToolUse",
                            tool_response={"stdout": "\n".join(str(n) for n in range(5000)), "stderr": "",
                                           "interrupted": False, "isImage": False})
        self.assertEqual(self.run_hook("log", post)[:2], (0, None))
        code, output, _ = self.run_hook("log", post, env={"AD_TRIM_HOOK": "1", "AD_TRIM_CHARS": "1000"})
        self.assertEqual(code, 0)
        replacement = output["hookSpecificOutput"]["updatedToolOutput"]
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertEqual(sorted(replacement), ["interrupted", "isImage", "stderr", "stdout"])
        self.assertLess(len(replacement["stdout"]), 3000)

    @unittest.skipUnless(os.path.isfile(AD), "ad.py is not present")
    def test_hooks_never_exit_non_zero_on_bad_input(self):
        for name in ("pre-bash", "pre-write", "pre-fetch", "log"):
            for raw in (b"", b"not json", b"[]", b'{"tool_input": 5}', b'{"tool_name": "Bash", "tool_input": {}}'):
                with self.subTest(name=name, raw=raw):
                    completed = subprocess.run([sys.executable, AD, "hook", name], input=raw, stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE, env=dict(os.environ), cwd=self.tmp, timeout=60)
                    self.assertEqual(completed.returncode, 0)
                    self.assertNotIn(b"Traceback", completed.stderr)

    def test_fence_fails_closed_only_for_destructive_looking_commands(self):
        original = ad_guards.scope_fence_decide

        def broken(_inp):
            raise RuntimeError("boom")

        ad_guards.scope_fence_decide = broken
        self.addCleanup(setattr, ad_guards, "scope_fence_decide", original)
        reason = ad_guards._fence_or_fail_closed({}, "rm -rf / --no-preserve-root")
        self.assertIn("internal error; blocking because the command looks destructive", reason)
        self.assertIsNone(ad_guards._fence_or_fail_closed({}, "ls -la"))


if __name__ == "__main__":
    unittest.main()
