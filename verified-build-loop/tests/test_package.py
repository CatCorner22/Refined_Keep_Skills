"""Package tests: the upload zip must match the skill folder, and the skill's own tests must be in it."""
import importlib.util
import os
import sys
import unittest
import zipfile

sys.dont_write_bytecode = True
PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_build():
    spec = importlib.util.spec_from_file_location("vbl_build", os.path.join(PACKAGE, "tools", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackageTests(unittest.TestCase):
    def test_each_zip_matches_its_folder(self):
        self.assertEqual(load_build().check(), [])

    def test_the_zip_has_one_top_folder_with_the_skill_file(self):
        with zipfile.ZipFile(os.path.join(PACKAGE, "dist", "verified-build-loop.zip")) as archive:
            names = archive.namelist()
        self.assertIn("verified-build-loop/SKILL.md", names)
        self.assertEqual({name.split("/")[0] for name in names}, {"verified-build-loop"})
        for needed in ("scripts/stop_check.py", "scripts/plan_check.py", "templates/verify.json", "tests/test_vbl.py"):
            self.assertIn("verified-build-loop/" + needed, names)
        self.assertFalse([name for name in names if "__pycache__" in name or name.endswith(".pyc")])


class PluginZipTests(unittest.TestCase):
    def test_the_plugin_zip_has_one_top_folder_with_the_manifest_and_the_skill(self):
        with zipfile.ZipFile(os.path.join(PACKAGE, "dist", "verified-build-loop-plugin.zip")) as archive:
            names = archive.namelist()
        self.assertEqual({name.split("/")[0] for name in names}, {"verified-build-loop"})
        for needed in (".claude-plugin/plugin.json", "skills/verified-build-loop/SKILL.md",
                       "skills/verified-build-loop/scripts/stop_check.py"):
            self.assertIn("verified-build-loop/" + needed, names)
        self.assertFalse([name for name in names if "__pycache__" in name or name.endswith(".pyc")])


class PluginTests(unittest.TestCase):
    def test_the_plugin_manifest_and_the_skill_agree(self):
        import json
        with open(os.path.join(PACKAGE, "plugin", ".claude-plugin", "plugin.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["name"], "verified-build-loop")
        with open(os.path.join(PACKAGE, "plugin", "skills", "verified-build-loop", "SKILL.md"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn('version: "%s"' % manifest["version"], text)

    def test_the_root_marketplace_lists_this_plugin(self):
        import json
        root = os.path.dirname(PACKAGE)
        with open(os.path.join(root, ".claude-plugin", "marketplace.json"), encoding="utf-8") as handle:
            entries = {entry["name"]: entry["source"] for entry in json.load(handle)["plugins"]}
        self.assertEqual(entries.get("verified-build-loop"), "./verified-build-loop/plugin")
        self.assertTrue(os.path.isfile(os.path.join(root, "verified-build-loop", "plugin", ".claude-plugin", "plugin.json")))


if __name__ == "__main__":
    unittest.main()
