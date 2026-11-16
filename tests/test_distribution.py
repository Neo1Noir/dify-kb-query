import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class DistributionTests(unittest.TestCase):
    def test_install_preserves_files_and_refuses_overwrite(self):
        installer = module("install")
        with tempfile.TemporaryDirectory() as tmp:
            target = installer.install(Path(tmp) / "skills with spaces")
            self.assertTrue((target / "SKILL.md").is_file())
            marker = target / "local-marker.txt"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already exists"):
                installer.install(target.parent)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_zip_has_one_skill_root_and_is_reproducible(self):
        packer = module("package_skill")
        with tempfile.TemporaryDirectory() as tmp:
            a = packer.package(Path(tmp) / "a.zip")
            b = packer.package(Path(tmp) / "b.zip")
            self.assertEqual(a.read_bytes(), b.read_bytes())
            with zipfile.ZipFile(a) as archive:
                self.assertIn("dify-kb-query/SKILL.md", archive.namelist())
                self.assertIn("dify-kb-query/LICENSE.txt", archive.namelist())
                self.assertTrue(all(n.startswith("dify-kb-query/") for n in archive.namelist()))
                self.assertFalse(any("__pycache__" in n or "/tests/" in n for n in archive.namelist()))

    def test_zip_rejects_modified_local_configuration(self):
        packer = module("package_skill")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            (source / "scripts").mkdir(parents=True)
            (source / "scripts/config.json").write_text(json.dumps({"api_base_url":"https://actual.example/v1","required_tags":[]}), encoding="utf-8")
            with patch.object(packer, "SOURCE", source), self.assertRaisesRegex(ValueError, "Refusing"):
                packer.package(Path(tmp) / "bad.zip")


    def test_zip_rejects_secret_fields_empty_tags_and_changed_names(self):
        packer = module("package_skill")
        original = json.loads((packer.SOURCE / "scripts/config.json").read_text(encoding="utf-8"))
        for change in ["secret", "empty", "name"]:
            cfg = json.loads(json.dumps(original))
            if change == "secret": cfg["api_key"] = "test-only-secret"
            elif change == "empty": cfg["required_tags"] = []
            else: cfg["required_tags"][0]["name"] = "Private team"
            with tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "source"
                (source / "scripts").mkdir(parents=True)
                (source / "scripts/config.json").write_text(json.dumps(cfg), encoding="utf-8")
                with patch.object(packer, "SOURCE", source), self.assertRaisesRegex(ValueError, "Refusing"):
                    packer.package(Path(tmp) / "bad.zip")


if __name__ == "__main__":
    unittest.main()
