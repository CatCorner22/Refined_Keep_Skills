# Agent-discipline skills

Version 2.0.0.

## 1. What this repository is

This repository holds 17 agent skills for Claude. Each skill is a folder with a `SKILL.md` file that tells Claude how to keep one part of its work checkable: what it read, what the user allowed, what it changed, and what evidence supports a claim that work is done.

11 of the 17 skills carry a small command-line tool (the CLI, `ad.py`) that stores state on disk. 5 skills are instructions only. 1 skill (`living-reference`) carries its own 2 scripts.

The repository serves 3 surfaces from 1 set of files:

| Surface | What you install | Hooks |
|---|---|---|
| claude.ai account | 1 zip for each skill, from `dist/` | none |
| Claude Code project skills, cloud sessions included | the folders under `.claude/skills/` | none by default |
| Claude Code plugin, local terminal sessions (optional) | this repository as a plugin | yes |

Every skill works with no hooks. The hooks add enforcement. No skill needs them.

### Layout

```
README.md, CHANGELOG.md, .gitignore
.claude/skills/<name>/SKILL.md      the 17 skills
.claude/skills/<name>/scripts/      generated copy of lib/ (11 scripted skills)
lib/                                the only hand-edited copy of the CLI library (8 files)
hooks/hooks.json                    the plugin hooks
docs/hooks-settings-example.json    the same hooks for a project settings file
.claude-plugin/plugin.json          the plugin manifest
.claude-plugin/marketplace.json     a marketplace with this 1 plugin
tools/build.py                      sync, check, validate, zip
tests/                              the test suite
dist/<name>.zip                     the 17 upload packages for claude.ai (generated)
```

## 2. The 17 skills

| Skill | What it prevents | Form |
|---|---|---|
| `ask-or-assume` | A question that interrupts the user for no reason, and a silent guess that is expensive to undo | instructions only |
| `autonomy-ledger` | Asking again for a permission the user already gave, and acting on a permission the user never gave | scripted |
| `claim-evidence-pairing` | A claim in a deliverable with no source, no quote and no stated confidence | scripted |
| `completion-evidence-gate` | A statement that work is done with no command, no output and no diff behind it | scripted |
| `context-budget-governor` | Losing the goal, the decisions and the next step when the conversation is compacted | scripted |
| `inventory-before-fetch` | Downloading or requesting a file that is already available | scripted |
| `living-reference` | A reference document whose sources, dates and confidence levels go stale without notice | own scripts |
| `model-sanity-regression` | Confusing a change in the model with a change in your own prompts and rules | scripted |
| `narrow-read-discipline` | Reading a whole file, log or test output when a small part answers the question | instructions only |
| `negative-constraint-compiler` | Relying on a written "never" rule that nothing enforces | scripted |
| `premise-check` | Building on a fact or diagnosis in the request that the evidence contradicts | instructions only |
| `read-manifest` | Reading the same unchanged file again after its content left the context | scripted |
| `retrieval-verification-gate` | Saying that a document says something when the document was only listed or partly retrieved | instructions only |
| `rules-hygiene` | A rules file that is long, vague, duplicated or out of date | scripted |
| `scope-and-blast-radius-check` | A destructive or wide-reaching action on the wrong target, or with no go-ahead from the user | scripted |
| `test-impact-selector` | Running the full test suite when a small subset covers the change, and reporting "tests pass" without saying which tests ran | scripted |
| `tool-call-validator` | A tool call with a wrong directory or wrong arguments, and the same failing call repeated unchanged | instructions only |

"Scripted" means that the skill folder holds `scripts/`, a byte-identical copy of the 8 files in `lib/`.

## 3. How the skills load on each surface

Use 1 route in each environment. A skill installed through 2 routes loads 2 times in the same Claude Code session: once under its short name and once under a namespaced name (`/agent-discipline:<name>` from the plugin, `/anthropic-skills:<name>` from the claude.ai account).

### 3.1 Project skills in `.claude/skills/` (Claude Code, cloud sessions included)

This is the route for a repository that you work on with Claude Code.

1. Copy the skill folders that you want from this repository's `.claude/skills/` into `.claude/skills/` of your own repository. Copy each folder whole, `scripts/` included.
2. Commit the folders.
3. Start Claude Code in that repository. Claude Code loads every folder under `.claude/skills/` that holds a `SKILL.md`.
4. If the session was already running when you created `.claude/skills/` for the first time, run `/reload-skills`. Claude Code watches a skills directory that existed at session start and picks up later changes without a restart. It does not yet watch a top-level skills directory that was created during the session.
5. Add `.agent/` to the `.gitignore` of your repository. The CLI also writes a `.gitignore` inside the state directory, so this step is a second safeguard.

In a cloud session:

- The session clones your repository, so the committed `.claude/skills/` folders load.
- The session also loads the skills that are enabled for your claude.ai account.
- The session does not load `~/.claude/skills/` from your machine, and it does not install plugins that the repository declares.
- In a cloud thread that belongs to a project, skills committed to `.claude/skills/` are not available. Only the skills enabled for the claude.ai account load there. Use route 3.2 for that case.

The project-skills route installs no hooks. Section 8.2 shows how to add them through a project settings file.

### 3.2 Upload to a claude.ai account

This is the route for claude.ai chat and Cowork. Skills that you enable there also load in Claude Code when you sign in with the same account, and in every cloud session.

`dist/` holds 1 zip for each skill. Each zip contains 1 top-level folder named after the skill, which is the layout that the upload requires.

1. On an individual plan, open Settings > Capabilities and make sure that "Code execution and file creation" is enabled. The updated Settings layout calls it "Create and edit files".
2. Open Customize > Skills.
3. Click the "+" button, then "+ Create skill".
4. Select "Upload a skill".
5. Upload `dist/<name>.zip`. Upload 1 zip for each skill that you want.
6. Use the switch next to each skill to turn it on or off.

What differs on this surface:

- No hook runs. Every skill is advisory.
- claude.ai chat does not fill in the `${CLAUDE_SKILL_DIR}` placeholder that the command examples use. Each scripted skill tells Claude to replace the placeholder with the folder that holds its `SKILL.md`.
- The state directory lives in the sandbox of that conversation. Do not expect it to carry over to another conversation.
- Claude Code downloads account skills and never uploads them. To change an uploaded skill, upload a new zip.

### 3.3 Plugin (optional, local terminal sessions)

The plugin delivers the same 17 skills plus the hooks in `hooks/hooks.json`. The plugin skills are namespaced: `/agent-discipline:<name>`.

From a Claude Code session:

```
/plugin marketplace add CatCorner22/Refined_Keep_Skills
/plugin install agent-discipline@refined-keep-skills
```

From a shell:

```
claude plugin marketplace add CatCorner22/Refined_Keep_Skills
claude plugin install agent-discipline@refined-keep-skills
```

For 1 session only, with no marketplace, from a local clone:

```
claude --plugin-dir /path/to/Refined_Keep_Skills
```

Notes:

- Add the marketplace in the `owner/repo` form shown above. The plugin entry uses the relative source `./`, which needs the whole repository. A bare URL to `marketplace.json` downloads only that file, and the install then fails.
- `plugin.json` sets `"version": "2.0.0"`. Claude Code keeps an installed plugin on that version until the string changes. A release therefore changes the version in `plugin.json`, in `lib/ad_core.py` and in every `SKILL.md`. `tools/build.py check` fails when they differ.
- A cloud session does not install a plugin that a repository declares, and it does not load a plugin that is enabled only in your user settings. For hooks in a cloud session, use section 8.2.
- If you work inside a clone of this repository with the plugin enabled, each skill loads 2 times: once as a project skill and once as a plugin skill.
- The repository has no LICENSE file. The owner has not chosen a license.

## 4. How to keep the skill menu short

Claude Code shows Claude a listing of skill names and descriptions. The listing has a character budget of 1% of the context window. When the listing overflows, Claude Code drops descriptions, starting with the skills that you invoke least. Claude then sees only the name of such a skill.

What this repository does about it: every description is at most 400 characters and puts the key use case first.

What you can do:

- Install only the skills that you use.
- In Claude Code, open `/skills`, highlight a skill, press `Space` to cycle its state, then press `Esc` to save. Claude Code writes the choice to `skillOverrides` in `.claude/settings.local.json`. The 4 states are:

  | Value | Listed to Claude | In the `/` menu |
  |---|---|---|
  | `"on"` | name and description | yes |
  | `"name-only"` | name only | yes |
  | `"user-invocable-only"` | hidden | yes |
  | `"off"` | hidden | hidden |

  You can also write the setting by hand:

  ```json
  {
    "skillOverrides": {
      "model-sanity-regression": "user-invocable-only",
      "living-reference": "name-only"
    }
  }
  ```

- On claude.ai, turn a skill off with its switch under Customize > Skills. Claude Code and cloud sessions load the account skills that are enabled there.

## 5. How the CLI works

Each scripted skill runs the same CLI from its own folder:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" <sub-command>
```

Claude Code replaces `${CLAUDE_SKILL_DIR}` with the directory that contains the skill's `SKILL.md`. The CLI needs Python 3.8 or later and uses the standard library only. It runs from any working directory.

When you work in this repository itself, run `python3 lib/ad.py <sub-command>`.

### 5.1 Where the state directory is

The state directory is a directory named `.agent/`. The CLI finds it in this order:

1. If the environment variable `AGENT_STATE_DIR` is set, the CLI uses that path. A relative value resolves against the start directory.
2. Otherwise the CLI walks upward from the start directory. At each directory it uses `<directory>/.agent` if that directory already holds the marker file `.agent/.ad-state`, or if that directory holds a `.git` entry. The CLI stops at the first hit.
3. Otherwise the CLI uses `<start directory>/.agent`.

The start directory is the current working directory for a CLI call. For a hook it is the `cwd` field of the hook input, then `CLAUDE_PROJECT_DIR`, then the current working directory.

The result: inside a git repository, every call uses 1 state directory at the repository root, whatever subdirectory the call runs in.

When the CLI creates the state directory, it writes the marker file `.ad-state` and a `.gitignore` that contains `*`, so git never stages anything in the state directory. The directory has mode 0700 and its files have mode 0600. Read-only sub-commands (`show`, `check`, `report`) do not create the state directory. They report that the state is empty.

### 5.2 The state files

| File | Content | Written by |
|---|---|---|
| `manifest.json` | The read manifest: each file read or fetched, with its size, fingerprint, line ranges, summary, and the session that read it. At most 500 entries. | `manifest record`, the Read hooks, the log hook for a fetch |
| `ledger.md` | The ledger: dated entries of kind GRANT, FORBID, STOP, ACCEPT, SCOPE or NOTE, in the user's words. 1 line for each entry. | `ledger add` |
| `approvals.json` | Each approval: the SHA-256 hash of 1 exact command, a redacted preview, the creation time and the expiry time. | `approve` |
| `scope.json` | The declared roots and the optional `allow` patterns. | `scope set`, `scope add` |
| `CHECKPOINT.md` | The checkpoint: goal, acceptance criteria, decisions, done, open, constraints, assumptions. | `checkpoint write` |
| `toollog.jsonl` | The tool log: 1 line for each logged tool call, with secrets redacted. The log rotates at 1 MB. | the log hooks only |
| `outputs/` | Full tool outputs that the optional trim hook stored. At most 200 files. | the log hook, only with `AD_TRIM_HOOK=1` |
| `provenance.jsonl` | Source rows for sections of a document: section, source, quote, confidence. | `provenance add` |
| `regress/` | The regression set (`set.json`, which you may edit) and the dated results. | `regress init`, `regress record` |
| `.ad-state`, `.gitignore`, `.lock` | The marker file, the ignore rule, and the lock file for concurrent writes. | the CLI |

The CLI refuses to read or write a state file that is a symbolic link.

### 5.3 Sub-commands and exit codes

General rule: exit code 0 means success, or that a check allowed or passed. Exit code 1 means that a check said no. Exit code 2 means a usage error or an input error, with a message that starts with `error:`.

| Sub-command | What it does | Exit codes |
|---|---|---|
| `version` | Prints `agent-discipline 2.0.0`. | 0 |
| `manifest record PATH [--range A-B]... [--summary TEXT] [--url URL]` | Records a read or a fetch in the read manifest. | 0; 2 if the file does not exist and no `--url` is given |
| `manifest check PATH` | Prints 1 status line for the file: `UNCHANGED`, `CHANGED`, `MISSING` or `NOT IN MANIFEST`. | 0 for `UNCHANGED`; 1 otherwise |
| `manifest show` | Prints the read manifest. | 0 |
| `ledger add KIND TEXT...` | Adds 1 entry to the ledger. KIND is GRANT, FORBID, STOP, ACCEPT, SCOPE or NOTE. | 0; 2 for an unknown kind |
| `ledger check ACTION...` | Prints the most recent GRANT or FORBID entry that shares keywords with the action. A match is a keyword match: read the entry before you rely on it. | 0 for a GRANT match; 1 for a FORBID match; 3 for no match |
| `ledger show` / `ledger clear` | Prints the ledger, or moves it aside to a dated file. | 0 |
| `checkpoint write [TEXT...]` / `checkpoint show` | Writes the checkpoint (from standard input when no text is given), or prints it. | 0 |
| `reinject [--full]` | Prints the reinjection: ledger, checkpoint and read manifest, within a character budget. | 0 |
| `scope set ROOT... [--allow REGEX]...` / `scope add ROOT` / `scope show` | Sets, extends or prints the declared roots. | 0 |
| `approve [--minutes N] [--note TEXT] -- COMMAND...` | Records an approval for 1 exact command. | 0 |
| `approvals show` / `approvals clear` | Prints or removes the approvals. | 0 |
| `fence-check COMMAND...` | Runs the scope fence on a command without running the command. Prints `ALLOW`, or `BLOCK` with the label and the reason. | 0 for ALLOW; 1 for BLOCK |
| `fetch-check COMMAND...` | Runs the fetch guard on a command without running the command. | 0 for ALLOW; 1 for BLOCK |
| `gate [TEXT...] [--file PATH] [--lenient]` | Checks a message for a completion claim and for the evidence block. Prints `PASS` or the reason. | 0 for PASS; 1 otherwise |
| `trim FILE` or `trim -` | Prints a shortened view of a long output (`-` reads standard input). It stores nothing. | 0 |
| `provenance add SECTION SOURCE [--quote Q] [--confidence C]` / `provenance show [SECTION]` | Records or prints source rows. | 0 |
| `provenance audit FILE` | Lists the headings of a document that have no source row. | 0 when every heading has a row; 1 otherwise |
| `rules lint [ROOT]` | Lists findings in rules files such as CLAUDE.md and AGENTS.md. | 0 when there are no findings; 1 otherwise |
| `rules rewrite FILE` | Prints a fill-in template for each negative rule. | 0 |
| `rules compile [ROOT] [--script-path P]` | Prints `permissions.deny` entries and a hook fragment for the rules that a command pattern can block. | 0 |
| `test-impact [--base REF] [--root DIR]` | Maps changed files to the tests to run first. | 0; 2 outside a git repository or for a bad `--base` |
| `regress init [--force]` / `regress show` / `regress record ID RESULT MODEL [--note N] [--force]` / `regress report` | Creates, prints, records against and summarizes the regression set. | 0; 2 for an unknown ID without `--force` |
| `deny-regex PATTERN...` | Hook form: denies a shell command that matches a pattern. | 0 |
| `hook NAME` | Hook entry point. NAME is 1 of `session-start`, `pre-bash`, `pre-write`, `pre-fetch`, `read-cache`, `record-read`, `log`, `log-failure`, `completion-gate`. | always 0 |

`hook NAME` also accepts the version 1 names `reinject`, `fetch-guard`, `scope-fence`, `validate-call` and `log-trim`.

### 5.4 Settings through environment variables

| Variable | Default | Effect |
|---|---|---|
| `AGENT_STATE_DIR` | not set | Path of the state directory |
| `AD_APPROVAL_MINUTES` | 30 | Lifetime of an approval; the maximum is 1440 |
| `AD_PROTECTED_BRANCHES` | `main,master` | Branches that the scope fence treats as protected |
| `AD_FETCH_DUP_MB` | 5 | Size from which the fetch guard blocks a duplicate fetch |
| `AD_BIG_EXT` | a list of large data and disk-image extensions | File types that need an inventory line and an approval before a fetch |
| `AD_RETRY_LIMIT` | 2 | Identical failures in a row before the retry rule blocks; 0 turns the rule off |
| `AD_HASH_MAX_MB` | 64 | Size up to which the read manifest hashes the whole file |
| `AD_GATE` | on | `off` turns the completion gate off |
| `AD_GATE_STRICT` | 1 | `0` stops the gate from comparing the `Command:` line with the tool log |
| `AD_TRIM_HOOK` | off | `1` lets the log hook replace a long shell output with a trimmed view |
| `AD_TRIM_CHARS` | 6000 | Length from which the trim applies |

A value that does not parse falls back to the default.

## 6. Approvals and the scope fence

The scope fence is the check that classifies a shell command as destructive, or as writing outside the declared roots. It runs in 2 ways: as the `fence-check` sub-command, which any surface can use, and as the `pre-bash` and `pre-write` hooks, which only run where hooks are installed.

How it decides:

1. It parses the command into segments, so that it inspects commands and not text inside quotes. `echo "rm -rf /"` is an `echo`.
2. It labels a destructive segment. The labels are: recursive delete, find delete, force push, push to protected branch, discards uncommitted work, history rewrite, destructive SQL, production data, infrastructure delete, publish or deploy, system destructive, inline delete code.
3. It collects the write targets of the command (redirection targets and the operands that tools such as `rm`, `mv`, `cp`, `tee` and `sed -i` write to) and resolves each one to a real path.
4. It blocks a command that carries a destructive label, unless an approval for that exact command exists.
5. It blocks a write target that lies outside the declared roots. The system temporary directories and the session scratchpad are always allowed.
6. It blocks any write to `approvals.json`, `scope.json` or `ledger.md` that does not go through the CLI.

The declared roots default to the git root of the project. Change them with `scope set` or `scope add`.

An approval is a time-limited permission for 1 exact command:

1. The scope fence blocks a command and prints the reason.
2. Claude shows you the exact command and asks.
3. After you say yes, Claude runs `python3 "${CLAUDE_SKILL_DIR}/scripts/ad.py" approve -- '<exact command>'`. No skill pre-approves this sub-command, so Claude Code asks you for permission to run it. That prompt is your second look at the command.
4. Claude runs the identical command again. The approval matches by hash, so any change to the command needs a new approval.
5. The approval expires after 30 minutes by default.

The ledger never unlocks the scope fence. A GRANT entry records what you said. Only an approval lets a blocked command through.

The same approval mechanism serves the fetch guard, which blocks a duplicate fetch of a large file that the read manifest already lists, and a fetch of a large file type with no approval.

## 7. Which skills pre-approve which commands

A scripted skill lists its own read-only and bookkeeping sub-commands in `allowed-tools`, so Claude Code does not prompt for them during the turn that invokes the skill. `allowed-tools` grants permission. It does not restrict which tools Claude can use. The grant ends with your next message.

No skill pre-approves `approve`, `approvals clear`, `scope set` or `scope add`. `tools/build.py check` fails if one does.

## 8. The optional hooks

### 8.1 What each hook does

| Event | Tools | Hook name | What it does |
|---|---|---|---|
| SessionStart | | `session-start` | After a resume or a compaction, it adds the reinjection to the context. At startup, it adds 1 line that says what state exists. It adds nothing when no state exists. |
| PreToolUse | Bash, PowerShell | `pre-bash` | Runs the fetch guard, the scope fence and the retry rule, in that order. The first denial wins. |
| PreToolUse | Write, Edit, NotebookEdit | `pre-write` | Runs the scope fence on the file path. It never reads the file content. |
| PreToolUse | WebFetch | `pre-fetch` | Runs the duplicate rule of the fetch guard on the URL. |
| PreToolUse | Read | `read-cache` | Never blocks. When the same session reads the same unchanged lines again, it adds a note with the recorded summary. |
| PostToolUse | Read | `record-read` | Records the file and the line range in the read manifest. |
| PostToolUse | Bash, PowerShell, Write, Edit, NotebookEdit, WebFetch | `log` | Appends 1 line to the tool log. Records a fetched file in the read manifest. |
| PostToolUseFailure | Bash, PowerShell | `log-failure` | Appends the failed call and its exit code to the tool log. |
| Stop | | `completion-gate` | When the last message claims completion with no evidence block, it prompts once for the block. It does not prompt a second time for the same stop attempt. |

Properties of every hook:

- Each hook entry uses the exec form (`"command": "python3"` plus `"args"`), so no shell parses the script path.
- Each entry starts a short bootstrap that exits 0 when the script file is missing. A missing file therefore never blocks a tool call.
- A hook that fails internally lets the tool call proceed. There is 1 exception: when the scope fence fails on a command that looks destructive, it blocks the command.
- A denial reaches Claude as a `permissionDecision` of `deny` with the reason and the next step. `ad.py hook` always exits 0.
- The hooks need a `python3` executable on `PATH`.

### 8.2 Enable the hooks through a project settings file

This is the route that works in cloud sessions, because a cloud session runs the hooks from the `.claude/settings.json` of the repository.

1. Install the `read-manifest` skill as a project skill (section 3.1). The hooks run the copy of the CLI in `.claude/skills/read-manifest/scripts/`.
2. Open `docs/hooks-settings-example.json`.
3. Copy its `"hooks"` object into `.claude/settings.json` of your repository. If that file already has a `"hooks"` object, merge the event lists.
4. Commit `.claude/settings.json`.

Limits of this route in a cloud session:

- It works in a session with 1 repository. A session with several repositories loads hooks from none of them.
- It does not work in a cloud thread that belongs to a project.

### 8.3 Enable the hooks as a plugin

Install the plugin (section 3.3). Claude Code loads `hooks/hooks.json` with the plugin. To turn the hooks off, disable the plugin.

Do not enable both routes in 1 project. Both sets of hooks would then run on every tool call.

## 9. Limits

- The scope fence is a seatbelt, not a sandbox. It recognizes the command forms that Claude usually writes. A command that hides its effect (a script file that deletes, an unusual tool, an encoded string) passes. For a real boundary, use the permission settings and the sandbox of the host.
- The checks are heuristics. The completion gate recognizes common completion phrases and can miss a claim or flag ordinary prose. `ledger check` matches keywords. `test-impact` maps files to tests by name and by text reference. `rules lint` matches phrases.
- Planted state. A repository can ship its own `.agent/` directory, with a ledger and a checkpoint that someone else wrote. The mitigations: an approval expires and matches 1 exact command; the reinjection labels its entries as records, not instructions; at session startup the hook adds only a 1-line summary. Treat a state directory that you did not create as untrusted, and delete it.
- Without hooks, every skill is advisory. Claude follows the procedure in the skill or it does not. This is the case on claude.ai, and in Claude Code unless you enable the hooks.
- A denial needs someone to answer. In an unattended run, a blocked command stays blocked.
- Windows. The hook matchers cover the PowerShell tool, and the fence parses commands with shell rules. PowerShell-specific destructive commands are not classified. The hooks have not been tested on Windows.
- State is local. The state directory belongs to 1 checkout or 1 sandbox. It does not sync between machines or between claude.ai conversations.
- The tool log holds command lines. The CLI redacts obvious secrets (authorization headers, `token=` and `password=` values, credentials in URLs) and git ignores the state directory. Do not rely on the redaction for a secret in an unusual form.

## 10. How to change a skill

To change the text of a skill:

1. Edit `.claude/skills/<name>/SKILL.md`.
2. Run `python3 tools/build.py all`.
3. Run `python3 -m unittest discover -s tests`.
4. Commit the skill folder and `dist/<name>.zip` together.

To change the CLI:

1. Edit the files in `lib/` only. Never edit a file under a skill's `scripts/`: the next sync overwrites it, and until then `check` fails.
2. Run `python3 tools/build.py all`. This copies `lib/` into the 11 scripted skills and rebuilds the zips.
3. Run `python3 -m unittest discover -s tests`.
4. Commit `lib/`, the generated copies and `dist/` together.

What `tools/build.py` does:

| Sub-command | What it does | Exit codes |
|---|---|---|
| `sync` | Copies every `lib/*.py` into `scripts/` of each scripted skill and removes any other entry there. | 0; 2 when `lib/` is missing |
| `check` | Lists every defect: a copy that differs from `lib/`; a `scripts/` directory in an instructions-only skill; a folder name that differs from the `name` in the frontmatter; a frontmatter key outside `name`, `description`, `compatibility`, `metadata`, `allowed-tools`; a description over 400 characters or with an angle bracket; a `SKILL.md` over 500 lines; a command that runs a script without the `${CLAUDE_SKILL_DIR}` prefix; a command example that names a sub-command that `ad.py` lacks; a sibling skill name that does not exist; a pre-approval of a sub-command that must prompt; versions that differ; a zip that differs from its folder. | 0 clean; 1 with findings |
| `validate` | Runs the checks of the claude.ai upload validator on every skill folder. With `--validator PATH` it also runs the real `quick_validate.py`. | 0 clean; 1 with findings |
| `zip` | Writes `dist/<name>.zip` for each skill whose zip is missing or stale. `--force` rewrites all of them. | 0 |
| `all` | Runs `sync`, `check`, `validate` and `zip`, then confirms the zips. It stops before `zip` when a check fails. | 0 clean; 1 with findings |

The zips are deterministic: sorted members, the fixed timestamp 1980-01-01, mode 0644 (0755 for `.py` files), no directory entries, and no `__pycache__`, `*.pyc`, `.DS_Store`, `tests/` or `.agent/` content. `check` compares each zip with its folder by member name, mode and content hash.

`build.py` needs only the standard library. When PyYAML is installed, `build.py` also parses each frontmatter with PyYAML and reports any disagreement. When PyYAML is missing, it prints a notice and skips that cross-check.

## 11. Tests

```
python3 -m unittest discover -s tests
```

The code targets Python 3.8 and later. The test matrix is Python 3.8, 3.9, 3.11, 3.12 and 3.13. To run the matrix:

```
for v in 3.8 3.9 3.11 3.12 3.13; do python$v -B -m unittest discover -s tests || break; done
```

The tests use temporary directories, inject the clock, and need no network. `tests/test_packaging.py` runs the `check` logic on this repository, so a stale copy or a stale zip fails the suite.

## 12. What changed from version 1

The details are in `CHANGELOG.md`. In summary:

- Approvals replace ledger matching. In version 1, a ledger line with similar words unlocked the scope fence. In version 2, only an approval for the exact command does.
- The scope fence parses commands. Version 1 matched text, so it blocked harmless commands that mentioned a destructive word and missed reordered flags.
- 1 state directory for each repository. Version 1 created a state directory in every working directory.
- The hooks cannot block by accident. A missing script exits 0, and the hooks use the exec form.
- The dead PostCompact hook is gone. The SessionStart hook covers compaction.
- The skills are portable: `${CLAUDE_SKILL_DIR}` in every command, only upload-safe frontmatter keys, least-privilege `allowed-tools`, and descriptions of at most 400 characters.
- 1 source for the library, with generated copies, a drift check and deterministic zips.
- A marketplace file, so that the plugin install commands work.
- Unverified statistics, incident stories and personal details are removed from the skill texts.
