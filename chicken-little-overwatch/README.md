# Chicken Little Overwatch

Version 2.0.0.

This folder holds 1 plugin and 1 skill for Claude and Claude Code, the tools that build and check them, the packages that you install, and a backup of the 2 archives that they come from.

- **Overwatch** is the quality control. Claude checks a deliverable against its requirements and its evidence, and Claude holds prose to an active-voice, plain-language writing standard.
- **Chicken Little** is the red team. A swarm of up to 8 agents asks what is wrong now and what will fall later. Each agent must prove each alarm; a finding without evidence carries the label SPECULATION.

## 1. Layout

```
chicken-little-overwatch/                  this folder; also a local plugin marketplace
  README.md                                this file
  .claude-plugin/marketplace.json          the marketplace "chicken-little", with 1 plugin
  chicken-little-overwatch/                the plugin (the folder that you install)
    .claude-plugin/plugin.json             the plugin manifest
    README.md, CHANGELOG.md                the plugin's guide and its history
    skills/chicken-little-overwatch/       the skill: SKILL.md, references/ (4 files), scripts/ (2 scanners)
    agents/rt-*.md                         the 8 subagents (generated)
    commands/qc-review.md, red-team.md     the 2 slash commands
    tools/validate_package.py              the package check
  tools/build.py                           writes the agents and the zips, and checks them
  tests/test_package.py                    37 tests
  dist/                                    the packages (generated)
    chicken-little-overwatch-plugin.zip    the plugin, for Claude Code
    chicken-little-overwatch-skill.zip     the skill alone, for claude.ai
    SHA256SUMS                             the checksum of each zip
  backup/original-uploads/                 the 2 archives of version 1.0.0, unchanged, with their checksums
```

The skill inside the plugin and the skill in `chicken-little-overwatch-skill.zip` are the same files.

## 2. Which package goes where

| Surface | Package | What you get |
|---|---|---|
| Claude Code (terminal, desktop, IDE) | the plugin | The skill, the 8 subagents, the 2 slash commands |
| claude.ai chat and Cowork | the skill zip | The skill. No subagents: the skill runs each red-team charter as a separate pass and says so |
| Claude Code, with no plugin | the skill folder, copied into `.claude/skills/` of a repository or into `~/.claude/skills/` | The skill. For the swarm, Claude launches general subagents with each charter |

Use 1 route on each surface. A skill that you install through 2 routes appears 2 times in Claude Code.

claude.ai and Cowork can also install a plugin. This plugin meets the 1 layout rule that the Claude Code documentation states for that route: it has no top-level `bin/` folder. Nobody has tested that route with this plugin.

The plugin's own `README.md` gives the install commands, the slash commands, the 3 tiers, and the known limits.

## 3. Build and check

Run each command from this folder.

```bash
python3 tools/build.py all
```

```bash
python3 -m unittest discover -s tests
```

`build.py all` does 3 things in order: it writes the 8 agent files, it writes the 2 zips and `dist/SHA256SUMS`, and it runs the check. The check runs the plugin's validator, confirms that each agent file matches the build tool, and confirms that each zip matches its folder.

If the `claude` program is on your path, also run the official validator:

```bash
claude plugin validate ./chicken-little-overwatch
```

| Result | Meaning | What to do |
|---|---|---|
| `OK: validator passed, agents current, zips current` | The package is consistent | Nothing |
| `FAIL`, then a list | Each line names 1 defect and, where one exists, the command that repairs it | Repair each defect, then run `build.py all` again |
| `ERROR:` | The build cannot run, for example because the swarm file lacks a section | Read the message and restore the section |

## 4. How to change the package

| To change | Edit | Then |
|---|---|---|
| The workflow, the modes, or the output format | `skills/chicken-little-overwatch/SKILL.md` | `build.py all`, then the tests |
| A swarm rule, a lens, a Defender rule, the severity scale, or the finding format | `skills/chicken-little-overwatch/references/red-team-swarm.md` | `build.py all`: the tool copies the new wording into the agent files |
| An agent's charter, description, or tool list | The `AGENTS` table in `tools/build.py` | `build.py all` |
| A scanner | `scripts/av_scan.py` or `scripts/watchlist_scan.py`. The block between `# --- shared reader` and `# --- end of shared reader ---` must stay identical in both files | `build.py all`, then the tests |
| The version | `version` in `.claude-plugin/plugin.json`, `metadata.version` in `SKILL.md`, and a new entry at the top of `CHANGELOG.md`. The validator fails when the 3 differ | `build.py all` |

Never edit these files:

- `agents/rt-*.md`: the build tool overwrites them.
- `references/one-way-optimal-language.md` and `references/original-plugin.json`: they stay byte for byte, and the validator compares each one with its SHA-256.
- Anything in `dist/`: the build tool overwrites it.
- Anything in `backup/`: it is the record of version 1.0.0.

## 5. Restore version 1.0.0

`backup/original-uploads/` holds the 2 archives exactly as the owner supplied them. To confirm that they are intact, run this command from that folder:

```bash
sha256sum -c SHA256SUMS
```

To use version 1.0.0 again, unzip the archive that you need. Version 1.0.0 has the defects that `chicken-little-overwatch/CHANGELOG.md` lists under "Fixed".

## 6. Relation to the rest of this repository

This folder stands alone. The repository's own build tool (`tools/build.py` at the repository root) and its 18 agent-discipline skills do not read this folder, and this folder's tools do not read them.
