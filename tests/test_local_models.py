"""Tests for utils/local_models.py: what is in the models folder, and deleting a model from it.

Deleting is the one destructive thing the setup page can do, so the rules are tested here and audited in
test_source_audit.py: only names this module listed itself, only inside the models folder, never a path from outside.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "utils"))
import local_models as lm  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dir = self.tmp / "models"
        self.dir.mkdir()

    def put(self, name, size=10, source=None):
        p = self.dir / name
        p.write_bytes(b"x" * size)
        if source:
            (self.dir / (name + ".source")).write_text(source, encoding="utf-8")
        return p

    def by_id(self):
        return {e["id"]: e for e in lm.scan(self.dir)}


class TestScan(Base):
    def test_lists_models_with_size_and_where_they_came_from(self):
        self.put("gemma-3-4b-it-Q4_K_M.gguf", 100, source="ggml-org/gemma-3-4b-it-GGUF")
        self.put("notes.txt")
        e = self.by_id()
        self.assertEqual(list(e), ["gemma-3-4b-it-Q4_K_M.gguf"])
        m = e["gemma-3-4b-it-Q4_K_M.gguf"]
        self.assertEqual((m["kind"], m["size"], m["repo"]), ("model", 100, "ggml-org/gemma-3-4b-it-GGUF"))
        self.assertEqual(m["files"], ["gemma-3-4b-it-Q4_K_M.gguf", "gemma-3-4b-it-Q4_K_M.gguf.source"])

    def test_a_split_model_is_one_entry_and_an_incomplete_set_says_so(self):
        for i in (1, 2):
            self.put(f"big-Q4-{i:05d}-of-00002.gguf", 50)
        self.put("half-Q4-00001-of-00003.gguf", 5)
        e = self.by_id()
        self.assertEqual(e["big-Q4-00001-of-00002.gguf"]["size"], 100)
        self.assertEqual(e["big-Q4-00001-of-00002.gguf"]["kind"], "model")
        self.assertEqual(len(e["big-Q4-00001-of-00002.gguf"]["files"]), 2)
        self.assertNotIn("big-Q4-00002-of-00002.gguf", e)
        self.assertEqual(e["half-Q4-00001-of-00003.gguf"]["kind"], "incomplete")

    def test_projectors_and_unfinished_downloads_are_listed_as_such(self):
        self.put("ggml-org--gemma-3-4b-it-GGUF--mmproj-model-f16.gguf", 7, source="ggml-org/gemma-3-4b-it-GGUF")
        self.put("mmproj-other.gguf", 3)
        self.put("qwen.gguf.part", 42)
        e = self.by_id()
        self.assertEqual(e["ggml-org--gemma-3-4b-it-GGUF--mmproj-model-f16.gguf"]["kind"], "projector")
        self.assertEqual(e["mmproj-other.gguf"]["kind"], "projector")
        self.assertEqual((e["qwen.gguf.part"]["kind"], e["qwen.gguf.part"]["size"]), ("partial", 42))

    def test_a_missing_folder_is_empty_not_an_error(self):
        self.assertEqual(lm.scan(self.tmp / "nope"), [])


class TestDelete(Base):
    def test_deletes_the_model_and_its_record(self):
        self.put("a.gguf", source="o/A-GGUF")
        self.put("b.gguf")
        removed, error = lm.delete(self.dir, "a.gguf")
        self.assertEqual(error, "")
        self.assertEqual(sorted(removed), ["a.gguf", "a.gguf.source"])
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["b.gguf"])

    def test_deletes_every_part_of_a_split_model(self):
        for i in (1, 2, 3):
            self.put(f"s-{i:05d}-of-00003.gguf")
        lm.delete(self.dir, "s-00001-of-00003.gguf")
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_only_names_it_listed_itself(self):
        outside = self.put("../outside.gguf")
        self.put("a.gguf")
        for bad in ("../outside.gguf", str(outside), "a.gguf/../../outside.gguf", "", "nope.gguf", "a.gguf.source"):
            with self.subTest(id=bad):
                removed, error = lm.delete(self.dir, bad)
                self.assertEqual(removed, [])
                self.assertIn("not in the models folder", error)
        self.assertTrue(outside.exists())
        self.assertTrue((self.dir / "a.gguf").exists())

    def test_a_link_to_a_file_elsewhere_removes_the_link_not_the_file(self):
        target = self.tmp / "elsewhere.gguf"
        target.write_bytes(b"keep me")
        try:
            os.symlink(target, self.dir / "linked.gguf")
        except OSError as e:                 # Windows without Developer Mode refuses to create links
            self.skipTest(f"this OS user cannot create symbolic links ({e})")
        removed, error = lm.delete(self.dir, "linked.gguf")
        self.assertEqual((removed, error), (["linked.gguf"], ""))
        self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
