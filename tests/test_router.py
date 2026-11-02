"""Tests for utils/router.py: every downloaded model behind one address, with llama-server's router mode.

llama-server started without -m and with --models-preset INI loads the model a request names, on demand
(llama.cpp tools/server/README.md, "Using multiple models"). The INI lists each model with its file (and projector).
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "utils"))
import router  # noqa: E402

HELP = (HERE / "fixtures" / "llama_server_help.txt").read_text(encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dir = self.tmp / "models"
        self.dir.mkdir()

    def put(self, name, source=None):
        (self.dir / name).write_bytes(b"x")
        if source:
            (self.dir / (name + ".source")).write_text(source, encoding="utf-8")


class TestEntries(Base):
    def test_each_complete_model_once_with_its_projector(self):
        self.put("gemma-3-4b-it-Q4_K_M.gguf", "ggml-org/gemma-3-4b-it-GGUF")
        self.put("mmproj-model-f16.gguf", "ggml-org/gemma-3-4b-it-GGUF")
        for i in (1, 2):
            self.put(f"Big-Q4-{i:05d}-of-00002.gguf")
        self.put("half-00001-of-00002.gguf")
        self.put("x.gguf.part")
        e = router.entries(self.dir)
        self.assertEqual([x["name"] for x in e], ["Big-Q4", "gemma-3-4b-it-Q4_K_M"])
        self.assertEqual(e[0]["model"], str(self.dir / "Big-Q4-00001-of-00002.gguf"), "a split model loads from part 1")
        self.assertEqual(e[1]["mmproj"], str(self.dir / "mmproj-model-f16.gguf"))
        self.assertEqual(e[0]["mmproj"], "")

    def test_names_are_safe_and_unique(self):
        self.put("a b[1].gguf")
        self.put("a_b_1_.gguf")
        names = [x["name"] for x in router.entries(self.dir)]
        self.assertEqual(len(set(names)), 2, names)
        self.assertTrue(all(router.SAFE_NAME.fullmatch(n) for n in names), names)


class TestPresetFile(Base):
    def test_ini_lists_each_model_and_the_shared_settings(self):
        text = router.preset_ini([{"name": "A", "model": "/m/a.gguf", "mmproj": ""},
                                  {"name": "B", "model": "/m/b.gguf", "mmproj": "/m/p.gguf"}], {"c": 4096})
        self.assertEqual(text, "version = 1\n\n[*]\nc = 4096\n\n[A]\nmodel = /m/a.gguf\n\n[B]\nmodel = /m/b.gguf\n"
                               "mmproj = /m/p.gguf\n")

    def test_a_path_with_a_newline_cannot_add_settings(self):
        with self.assertRaises(ValueError):
            router.preset_ini([{"name": "A", "model": "/m/a.gguf\nmodels-max = 99", "mmproj": ""}], {})

    def test_write_replaces_the_file_whole(self):
        path = self.tmp / ".launchpad-models.ini"
        router.write_preset(path, "one\n")
        router.write_preset(path, "two\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "two\n")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), [".launchpad-models.ini", "models"])


class TestArgs(unittest.TestCase):
    def test_router_arguments_only_when_this_llama_server_has_router_mode(self):
        import chat_server
        flags = chat_server.server_flags(HELP)
        self.assertEqual(router.router_args("/p/x.ini", flags), (["--models-preset", "/p/x.ini", "--models-max", "1"], ""))
        args, why = router.router_args("/p/x.ini", {"--port"})
        self.assertEqual(args, [])
        self.assertIn("--models-preset", why)


if __name__ == "__main__":
    unittest.main()
