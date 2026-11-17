# coding

Version 2.0.0. A Claude Code plugin with 7 stack-agnostic software-craft skills. Claude loads each skill on its own when the task fits its description.

| Skill | Use it when |
|---|---|
| `coding-ecosystem-primer` | You want the router: it picks the smallest set of the skills below for a task |
| `deliverable-first` | A feature starts: define the finished artifact and its acceptance checklist before any code |
| `stable-architecture` | You structure a feature or review coupling: boundaries, dependency direction, replaceable adapters |
| `real-time-testing` | You implement: run the narrowest check after every slice, and never report done without fresh output |
| `clean-minimal-code` | You write or review code: fewer lines with the same behaviour, no premature abstraction |
| `ui-engineering` | You build UI components: composition, design tokens, responsive layout, accessible markup |
| `ux-engineering` | You design or review a screen: task flows, the 4 required states, accessibility, microcopy |

The build script generates these skills from `CatCorner22/Cursor_Skills`. `../README.md` lists every change that the build makes and says how to rebuild. To enforce the checks that these skills describe, install the `verified-build-loop` plugin of the same marketplace.
