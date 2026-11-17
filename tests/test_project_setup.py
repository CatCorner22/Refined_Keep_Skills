"""This repository uses its own tools: the agent-discipline hooks and the verified build loop.

These tests keep the installed copies under ``.claude/`` equal to their sources, so that a change
to a source cannot leave this repository running an old copy.
"""
import importlib
import json
import os
import sys
import unittest

sys.dont_write_bytecode = True
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VBL_SKILL = os.path.join(REPO, "verified-build-loop", "plugin", "skills", "verified-build-loop")


def load(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
        return json.load(handle)


def read(*parts):
    with open(os.path.join(REPO, *parts), "rb") as handle:
        return handle.read()


class ProjectSetupTests(unittest.TestCase):
    def test_settings_hold_the_agent_discipline_hooks_then_the_build_loop_hooks(self):
        discipline = load("docs", "hooks-settings-example.json")["hooks"]
        loop = load("verified-build-loop", "plugin", "skills", "verified-build-loop", "templates",
                    "settings-hooks.json")["hooks"]
        expected = {event: list(groups) for event, groups in discipline.items()}
        for event, groups in loop.items():
            expected.setdefault(event, []).extend(groups)
        self.assertEqual(load(".claude", "settings.json"), {"hooks": expected})

    def test_installed_hook_scripts_equal_the_skill_s_scripts(self):
        names = sorted(name for name in os.listdir(os.path.join(VBL_SKILL, "scripts")) if name.endswith(".py"))
        installed = sorted(name for name in os.listdir(os.path.join(REPO, ".claude", "hooks"))
                           if name != "__pycache__")  # written when a hook imports vbl_common; git ignores it
        self.assertEqual(installed, names)
        for name in names:
            self.assertEqual(read(".claude", "hooks", name), read(VBL_SKILL, "scripts", name), name)

    def test_installed_reviewer_equals_the_template(self):
        self.assertEqual(read(".claude", "agents", "reviewer.md"), read(VBL_SKILL, "templates", "reviewer.md"))

    def test_verify_json_is_well_formed_and_names_commands_that_exist(self):
        sys.path.insert(0, os.path.join(VBL_SKILL, "scripts"))
        self.addCleanup(sys.path.remove, os.path.join(VBL_SKILL, "scripts"))
        vbl = importlib.import_module("vbl_common")
        config = load(".claude", "verify.json")
        self.assertEqual(vbl.config_shape_problems(config), [])
        self.assertTrue(config["fast_checks"])
        for check in config["fast_checks"]:
            for word in check["command"].split():
                if word.endswith(".py") or word in ("tests",) or "/tests" in word:
                    self.assertTrue(os.path.exists(os.path.join(REPO, word)), "%s: %s" % (check["name"], word))

    def test_the_lock_is_ignored_by_git(self):
        with open(os.path.join(REPO, ".gitignore"), encoding="utf-8") as handle:
            self.assertIn(".claude/verify-lock.json", handle.read().splitlines())


if __name__ == "__main__":
    unittest.main()
