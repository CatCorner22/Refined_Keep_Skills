# Claude Code plugins

## 1. What this folder is

This folder holds 3 Claude Code plugins, the script that builds them, their tests and their upload zips. Each plugin is a Claude Code build of skills that the owner already had in another form.

| Plugin | Version | Skills | Source | Why a Claude Code build |
|---|---|---|---|---|
| `coding` | 2.0.0 | `coding-ecosystem-primer`, `deliverable-first`, `stable-architecture`, `real-time-testing`, `clean-minimal-code`, `ui-engineering`, `ux-engineering` | `CatCorner22/Cursor_Skills`, commit `5cf5106`, `skills/coding/` | In the source, every skill carries `disable-model-invocation: true`. With that key, Claude Code never loads the skill on its own. |
| `plain-language` | 1.0.0 | `unambiguous-language`, `one-way-optimal-language` | `CatCorner22/Cursor_Skills`, commit `5cf5106`, `skills/legal/` | The same key. In addition, the copy of `one-way-optimal-language` in the owner's claude.ai account held no `scripts/` folder, so its checker step could not run. |
| `red-team` | 1.0.0 | `red-team-lead` | the owner's claude.ai account, as it was on 2026-11-17 | The skill worked, and no repository held it. |

The root marketplace file lists all 3. The 18 skills and the build tool at the root of the repository do not read this folder.

### Layout

```
README.md                          this file
<plugin>/.claude-plugin/plugin.json the plugin manifest
<plugin>/README.md                 what the plugin holds
<plugin>/skills/<skill>/           the skill: SKILL.md, and scripts/ and references/ where the source has them
tools/build_plugins.py             generates the skills of 2 plugins, and builds and checks the zips
tests/test_plugins.py              22 tests
dist/<plugin>-plugin.zip           the upload packages (generated)
```

## 2. How to install a plugin

Use 1 route in each environment. A skill installed through 2 routes loads 2 times.

| Route | Steps |
|---|---|
| Claude Code, from the marketplace | `/plugin marketplace add CatCorner22/Refined_Keep_Skills`, then `/plugin install coding@refined-keep-skills`, `/plugin install plain-language@refined-keep-skills` or `/plugin install red-team@refined-keep-skills` |
| claude.ai account, for cloud sessions | Upload `dist/<plugin>-plugin.zip` in the claude.ai settings. The zip holds 1 top folder with `.claude-plugin/plugin.json` in it. This repository has not verified the upload step. |

Before you install a plugin, remove the older copy of each of its skills from the same environment:

- `coding`: the claude.ai account held an upload named `coding`, built from `Cursor_Skills` at commit `6f3febc` (2026-08-30). Its skills carry `disable-model-invocation: true`.
- `plain-language`: the claude.ai account held `unambiguous-language` and `one-way-optimal-language` as single skills.
- `red-team`: the claude.ai account held `red-team-lead` as a single skill.

A plugin skill is namespaced. Claude loads it on its own when the task fits its description, and a person can invoke it by name, for example `/coding:deliverable-first`.

## 3. What the build changes

`tools/build_plugins.py generate` reads a checkout of `Cursor_Skills` at the pinned commit and writes the skills of `coding` and `plain-language`. It changes only what this section lists. Each replaced text must occur exactly 1 time in the source; if the source changed, the build stops and names the text.

**Every generated skill:**

1. The frontmatter keeps `name` and `description` exactly as the source has them.
2. The build drops `disable-model-invocation`. It also drops the source's `metadata` block where the source has one: the 7 coding skills have one (`priority` in all 7, `promptSignals` in `real-time-testing`, `pathPatterns` and `importPatterns` in `ui-engineering`), and the 2 legal skills have none. Claude Code ignores those `metadata` keys.
3. The build adds a `metadata` block with the plugin version and the source path and commit.
4. The build copies `scripts/` and `references/`. It copies nothing else; `evals/` stays in the source repository.

**Single skills:**

| Skill | Change | Reason |
|---|---|---|
| `coding-ecosystem-primer` | Adds 1 paragraph, "In Claude Code", after the first paragraph | The skill is a router. Its tables name skills of this plugin and of other packs. The paragraph names the 7 skills of this plugin, says how to load one, says that `verified-build-loop` is its own plugin in the same marketplace, and says what to do when the session does not list a skill of another pack. |
| The 6 other `coding` skills | Appends a section, "In Claude Code", with the same guidance | The same reason |
| `real-time-testing` | Replaces "Keep a watcher running in a **tmux** terminal while editing:" with text that tells Claude Code to start a watcher in the background | A watch command never exits, so a foreground command would hang |
| `unambiguous-language` | In "Maintaining the living list", steps 3 and 5 now say what to do when the session has no memory tool, or cannot write to the `Cursor_Skills` repository. Step 5 also says that this repository holds the master copy of the skill. | Those steps assumed the claude.ai app and a session with that repository |
| `one-way-optimal-language` | Verification step 1 now runs `python3 "${CLAUDE_SKILL_DIR}/scripts/active_voice_check.py" FILE`. The build appends a section, "Files in this skill". | The source named the script with no folder, so the command failed unless the working directory was the skill's `scripts/` folder. The source did not name its 4 reference files. |

`red-team-lead` is not generated. It is a byte-for-byte copy of the account's copy.

## 4. How to rebuild

1. Check out `CatCorner22/Cursor_Skills` at the commit that `SOURCE_COMMIT` in `tools/build_plugins.py` names. The script looks for the checkout next to this repository; `--source DIR` names another place. The build stops if the checkout is at another commit, or if its `skills/coding/` or `skills/legal/` folder holds an uncommitted change or an untracked file.
2. Run `python3 plugins/tools/build_plugins.py generate`.
3. Run `python3 plugins/tools/build_plugins.py zip`.
4. Run `python3 -B -m unittest discover -s plugins/tests`. 1 test rebuilds the skills into a temporary folder and compares them with the committed skills; it skips when no checkout at the pinned commit is present.
5. Run `claude plugin validate plugins/<plugin>` for each plugin.

To take a newer version of a source skill: read the changes in the source, update `SOURCE_COMMIT`, update `PATCHES` if a replaced text changed, update `FOOTERS` if the bundled files of `one-way-optimal-language` changed, raise the version in `GENERATED` and in the plugin's `plugin.json`, then run steps 2 through 5.

The master copy of each generated skill stays in `Cursor_Skills`. Change a skill there, then rebuild here. A change made only here disappears at the next `generate`.

## 5. What these plugins do not hold, and why

| Skill | Where it is | Why this folder has no copy |
|---|---|---|
| `adams-plain-grade`, `adams-smart-brevity` | `CatCorner22/Claude_Skills_2`, plugin `writing-skills` | They already are Claude Code plugin skills there, with their reference files. A copy here would be a second version to keep in step. |
| `mscd-contracts` | `CatCorner22/Cursor_Skills`, `skills/legal/` | The claude.ai account's copy arrived whole (44 files) and its lint script runs in a Claude Code cloud session. It depends on the `docx` skill. |
| The coding skills of `coding-agent-skills` and `full-stack-dev-skills` | `CatCorner22/Claude_Skills_2` | They already are Claude Code plugins there. |
| `verified-build-loop` | `verified-build-loop/` in this repository | It is its own plugin. |

## 6. Open points for the owner

These points need a decision by the owner. The build did not change them.

1. **`unambiguous-language` and `mscd-contracts` disagree on a counterparty's draft.** `unambiguous-language`, List B, replaces "represents and warrants" with "states", and its section "When this skill applies" says "If two skills conflict, the stricter rule controls." `mscd-contracts` (`Cursor_Skills`, `skills/legal/mscd-contracts/SKILL.md`, line 67) says "on the other side's draft, keep their *represents and warrants*".
2. **`unambiguous-language` and the 2 Adams skills disagree on "hold harmless".** `unambiguous-language`, List B, replaces "indemnify and hold harmless" with "indemnify". `adams-plain-grade` and `adams-smart-brevity` (`Claude_Skills_2`, plugin `writing-skills`) treat risk-allocation clauses as a carve-out, and `adams-smart-brevity` lists "Cutting 'indemnify, defend, and hold harmless' down to 'indemnify'" as a mistake.
3. **`adams-plain-grade` disagrees with itself.** Its reference file `grade-targets-and-checks.md`, line 48, lists "indemnify and hold harmless" among the phrases to replace. Its `SKILL.md` carves risk-allocation clauses out of every rewrite.
4. **`unambiguous-language` says that it applies to every reply.** A skill loads only when Claude judges that its description fits the task. To apply a rule in every session, put the rule in the instructions that the session always loads (a `CLAUDE.md` file, or the personal preferences of the claude.ai profile).
5. **The `coding` skills name skills of other packs** (`nextjs`, `shadcn`, `react-best-practices`, `verification`, `playwright-cli`, `loop-on-ci`, `fix-ci`, `ooda-lean-loop`, `workspace-mise-en-place`, `prompt-optimizer`, `ai-transfer-ecosystem-primer`, `proactive-agency`, `appbuilder-testing`, `walkthrough-artifacts`, and the pack name `cursor-team-kit`). The build tells Claude to continue without a skill that the session does not list. The owner might prefer to remove those names from the source.
