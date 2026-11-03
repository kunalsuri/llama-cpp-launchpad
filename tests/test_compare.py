"""Tests for utils/compare.py: the same prompts on two or three downloaded models, one after another.

llama-server is tests/fake_llama_server.py, a real process on a real port: it answers /v1/chat/completions with
"[model file] prompt" and llama-server's own timings object, so the whole run is exercised, not a mock of it.
"""
import io
import os
import sys
import time
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "utils"))
sys.path.insert(0, str(HERE))
import compare  # noqa: E402
import test_chat_server as tcs  # noqa: E402  (module import: its test classes are not collected twice)

PROMPTS = [("Say", "Say hello."), ("Count", "Count to three.")]


class Base(unittest.TestCase):
    def setUp(self):
        self.env = {"PORT": str(tcs.free_port()), "EXTRA_ARGS": ""}

    def make(self, models, prompts=PROMPTS, **kw):
        c = compare.Comparison(models, find_server=lambda: list(tcs.SERVER), prompts=prompts, environ=self.env,
                               system="Linux", **kw)
        self.addCleanup(c.stop)
        return c

    def wait(self, c, *states, timeout=60):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            s = c.status()
            if s["state"] in states:
                return s
            time.sleep(0.05)
        self.fail(f"never reached {states}: {c.status()}")


class TestComparison(Base):
    def test_each_model_answers_every_prompt_with_its_speed(self):
        c = self.make([(Path("/m/a.gguf"), "A"), (Path("/m/b.gguf"), "B")])
        c.start()
        s = self.wait(c, "done")
        self.assertEqual([m["title"] for m in s["models"]], ["A", "B"])
        for m, name in zip(s["models"], ("a.gguf", "b.gguf")):
            self.assertEqual(m["state"], "done", m)
            self.assertEqual([r["prompt"] for r in m["results"]], ["Say", "Count"])
            self.assertEqual(m["results"][1]["text"], f"[{name}] Count to three.")
            self.assertEqual((m["results"][0]["tps"], m["results"][0]["first_ms"], m["results"][0]["tokens"]), (40.0, 12.5, 7))
            self.assertGreater(m["load_s"], 0)
            self.assertEqual(m["tps"], 40.0, "the model's speed is the mean over its prompts")
        self.assertIsNone(c.servers_running(), "every server it started is stopped again")

    def test_one_model_at_a_time_with_the_same_settings(self):
        c = self.make([(Path("/m/a.gguf"), "A"), (Path("/m/b.gguf"), "B")], settings=["-c", "4096"])
        c.start()
        s = self.wait(c, "done")
        for m in s["models"]:
            self.assertIn("-c 4096", m["cmd"])
        self.assertLess(s["models"][0]["finished"], s["models"][1]["started"], "the second starts after the first ends")

    def test_a_model_that_does_not_load_is_reported_and_the_next_one_still_runs(self):
        c = self.make([(Path("/m/a.gguf"), "A"), (Path("/m/b.gguf"), "B")])
        with unittest.mock.patch.dict(os.environ, {"FAKE_LLAMA_EXIT": "1"}):
            c.start()
            self.wait(c, "done")
        s = c.status()
        self.assertEqual([m["state"] for m in s["models"]], ["failed", "failed"])
        self.assertIn("failed to load model", s["models"][0]["error"] + "\n".join(s["models"][0]["log"]))

    def test_stop_ends_the_run_and_its_server(self):
        c = self.make([(Path("/m/a.gguf"), "A"), (Path("/m/b.gguf"), "B")])
        with unittest.mock.patch.dict(os.environ, {"FAKE_LLAMA_REPLY_S": "5"}):
            c.start()
            end = time.monotonic() + 30
            while c.status()["models"][0]["state"] != "asking" and time.monotonic() < end:
                time.sleep(0.05)
            s = c.stop()
        self.assertEqual(s["state"], "stopped")
        self.assertIsNone(c.servers_running())

    def test_two_or_three_models(self):
        for models in ([], [(Path("/m/a.gguf"), "A")], [(Path(f"/m/{i}.gguf"), str(i)) for i in range(4)]):
            with self.assertRaises(ValueError):
                compare.Comparison(models, find_server=lambda: list(tcs.SERVER))

    def test_without_llama_server_nothing_starts(self):
        c = compare.Comparison([(Path("/m/a.gguf"), "A"), (Path("/m/b.gguf"), "B")], find_server=lambda: [])
        self.assertIn("llama-server was not found", c.start()["error"])
        self.assertEqual(c.status()["state"], "idle")


class TestCommandLine(Base):
    def test_prints_the_answers_side_by_side_and_a_speed_table(self):
        out = io.StringIO()
        with redirect_stdout(out), unittest.mock.patch.object(compare, "find_llama_server", return_value=""), \
                unittest.mock.patch.object(compare, "server_argv", return_value=list(tcs.SERVER)), \
                unittest.mock.patch.dict(os.environ, self.env):
            rc = compare.main(["/m/a.gguf", "/m/b.gguf", "--prompt", "Say hello."])
        text = out.getvalue()
        self.assertEqual(rc, 0, text)
        self.assertIn("[a.gguf] Say hello.", text)
        self.assertIn("[b.gguf] Say hello.", text)
        self.assertRegex(text, r"a\.gguf\s.*40\.0 tokens/s")


if __name__ == "__main__":
    unittest.main()
