# plain-language

Version 1.0.0. A Claude Code plugin with 2 writing skills in the Ken Adams (MSCD) tradition.

| Skill | Use it when |
|---|---|
| `unambiguous-language` | Claude writes for the owner: active voice, "might" for possibility, and a living list of ambiguous words with a precise replacement for each |
| `one-way-optimal-language` | You draft, review or rewrite medical, pharmacy or research text that a reader uses with no chance to ask a question |

`one-way-optimal-language` ships an active-voice checker, `scripts/active_voice_check.py`. The checker needs Python 3 and the standard library. If spaCy and the model `en_core_web_sm` are installed, the checker adds a dependency-parse pass.

The build script generates these skills from `CatCorner22/Cursor_Skills`. `../README.md` lists every change that the build makes, says how to rebuild, and lists 3 open points about `unambiguous-language` for the owner (points 1, 2 and 4 of its section 6).
