"""Tests for tools/docs-media/capture.py: the tool that makes the documentation's screenshots, GIFs and videos.

Its job is to show the real program, so most of these tests are about refusing to publish anything else: the test
suite's fake llama-server, a run without machine details, a sped-up clip that does not say it was sped up.
The ffmpeg command lines are checked as lists (never a shell string; CLAUDE.md rule 6 and the source audit).
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path, PureWindowsPath

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "utils"))
sys.path.insert(0, str(ROOT / "tools" / "docs-media"))
import capture  # noqa: E402
import hardware  # noqa: E402

REAL = "version: 7120 (5ce06fc7)\nbuilt with cc (Ubuntu 13.3.0-6ubuntu2~24.04) 13.3.0 for x86_64-linux-gnu"
FAKE = "version: 4242 (abc1234)\nbuilt with fake-cc for test"            # tests/fake_llama_server.py --version


def run_record(**over):
    run = {"date": "2026-11-05", "launchpad_commit": "89d7817",
           "machine": {"os": "Linux 6.8", "arch": "x86_64", "cpu": "AMD EPYC", "threads": 4, "ram_gb": 15.6,
                       "gpu": "none"},
           "llama_server": {"version": REAL, "path": "bin/llama-server"},
           "models": [{"file": "gemma-3-1b-it-Q4_K_M.gguf", "repo": "ggml-org/gemma-3-1b-it-GGUF",
                       "sha256": "a" * 64, "bytes": 806058272}]}
    run.update(over)
    return run


class TestRealLlamaServerOnly(unittest.TestCase):
    def test_a_real_build_passes(self):
        self.assertEqual(capture.llama_problem("/opt/llama/llama-server", REAL), "")

    def test_the_test_suites_fake_is_refused_by_its_banner(self):
        self.assertIn("fake", capture.llama_problem("/somewhere/llama-server", FAKE))

    def test_the_fake_is_refused_by_where_it_lives_too(self):
        path = str(ROOT / "tests" / "bin" / "llama-server")
        self.assertIn("tests", capture.llama_problem(path, REAL))

    def test_no_server_or_no_version_is_named(self):
        self.assertIn("no llama-server", capture.llama_problem("", ""))
        self.assertIn("did not print a version", capture.llama_problem("/opt/llama-server", "error: bad"))

    def test_publishing_into_docs_media_needs_a_real_server(self):
        media = ROOT / "docs" / "media"
        self.assertIn("refusing", capture.publish_problem(media, "llama-server is the test suite's fake"))
        self.assertIn("refusing", capture.publish_problem(media / "sub", "llama-server is the test suite's fake"))
        self.assertEqual(capture.publish_problem(media, ""), "")

    def test_a_trial_run_elsewhere_may_use_the_fake(self):
        # Trying the scenes out against the fake is how the tool itself is developed; it just never lands in docs/.
        self.assertEqual(capture.publish_problem(Path(tempfile.gettempdir()) / "try", "fake"), "")


class TestEntryProblems(unittest.TestCase):
    def entry(self, **over):
        e = {"file": "setup-home.png", "kind": "screenshot", "shows": "The first screen of the setup page", "run": "r1"}
        e.update(over)
        return e

    def test_a_complete_entry_has_no_problems(self):
        self.assertEqual(capture.entry_problems(self.entry(), {"r1": run_record()}), [])

    def test_each_missing_field_is_named(self):
        problems = capture.entry_problems(self.entry(shows="", kind="painting", run="nope"), {"r1": run_record()})
        text = "\n".join(problems)
        for word in ("shows", "kind", "nope"):
            self.assertIn(word, text)

    def test_a_run_with_the_fake_server_is_refused(self):
        run = run_record(llama_server={"version": FAKE, "path": "x"})
        self.assertTrue(any("fake" in p for p in capture.entry_problems(self.entry(), {"r1": run})))

    def test_a_run_without_machine_details_is_refused(self):
        for key in ("os", "cpu", "ram_gb", "gpu"):
            machine = dict(run_record()["machine"])
            del machine[key]
            problems = capture.entry_problems(self.entry(), {"r1": run_record(machine=machine)})
            self.assertTrue(any(key in p for p in problems), key)

    def test_a_model_without_its_checksum_or_source_is_refused(self):
        run = run_record(models=[{"file": "m.gguf", "repo": "", "sha256": "abc", "bytes": 1}])
        text = "\n".join(capture.entry_problems(self.entry(), {"r1": run}))
        self.assertIn("sha256", text)
        self.assertIn("repo", text)

    def test_a_sped_up_clip_must_say_how_much(self):
        problems = capture.entry_problems(self.entry(file="walk.mp4", kind="video", speedup=[{"from_s": 3}]),
                                          {"r1": run_record()})
        self.assertTrue(any("speed" in p for p in problems))
        ok = self.entry(file="walk.mp4", kind="video", speedup=[{"what": "download", "real_s": 192, "factor": 8}])
        self.assertEqual(capture.entry_problems(ok, {"r1": run_record()}), [])


class TestMachineRecord(unittest.TestCase):
    def test_hardware_facts_only(self):
        hw = hardware.Hw(ram_mb=16000, cores=8, gpu_kind="nvidia", gpu_name="NVIDIA GeForce RTX 4060", vram_mb=8188,
                         gpu_usable=True)
        m = capture.machine(hw, "Linux 6.8.0", "x86_64", "AMD Ryzen 7 7700")
        self.assertEqual(m, {"os": "Linux 6.8.0", "arch": "x86_64", "cpu": "AMD Ryzen 7 7700", "threads": 8,
                             "ram_gb": 15.6, "gpu": "NVIDIA GeForce RTX 4060, 8.0 GB, used by llama.cpp"})

    def test_no_gpu_and_unused_gpu_are_told_apart(self):
        self.assertEqual(capture.machine(hardware.Hw(ram_mb=8192), "Linux", "x86_64", "cpu")["gpu"], "none")
        hw = hardware.Hw(ram_mb=8192, gpu_kind="nvidia", gpu_name="GTX 1050", vram_mb=2048, gpu_usable=False)
        self.assertIn("not used by this llama.cpp build", capture.machine(hw, "Linux", "x86_64", "cpu")["gpu"])

    def test_one_line_caption(self):
        self.assertEqual(capture.caption(run_record()),
                         "Recorded 2026-11-05 on Linux 6.8 (AMD EPYC, 4 threads, 15.6 GB RAM, no GPU) with "
                         "llama.cpp 7120 and gemma-3-1b-it-Q4_K_M.gguf.")


class TestFfmpegArgs(unittest.TestCase):
    def test_mp4_plays_everywhere(self):
        args = capture.mp4_args("in.webm", "out.mp4")
        self.assertEqual(args[0], "ffmpeg")
        for part in ("libx264", "yuv420p", "+faststart"):
            self.assertIn(part, args)
        self.assertIn("-an", args)                                 # no audio track: there is no narration
        self.assertEqual(args[-1], "out.mp4")

    def test_gif_uses_its_own_palette(self):
        args = capture.gif_args("in.webm", "out.gif", fps=10, width=960)
        graph = args[args.index("-filter_complex") + 1]
        self.assertIn("fps=10", graph)
        self.assertIn("scale=960:-1", graph)
        self.assertIn("palettegen", graph)
        self.assertIn("paletteuse", graph)

    def test_a_segment_is_cut_and_sped_up_exactly(self):
        args = capture.segment_args("in.webm", "out.mp4", 3.0, 10.5, 8, size=(1280, 800))
        self.assertEqual(args[args.index("-ss") + 1], "3.000")
        self.assertEqual(args[args.index("-t") + 1], "7.500")              # a duration, not an end time
        graph = args[args.index("-filter:v") + 1]
        self.assertIn("setpts=(PTS-STARTPTS)/8", graph)
        self.assertIn("scale=1280:800", graph)
        normal = capture.segment_args("in.webm", "out.mp4", 0, 2, 1, size=(1280, 800))
        self.assertIn("setpts=PTS-STARTPTS,", normal[normal.index("-filter:v") + 1])

    def test_segments_share_one_format_so_they_can_be_joined(self):
        cut = capture.segment_args("in.webm", "a.mp4", 0, 2, 1, size=(1280, 800))
        card = capture.card_args("card.png", 2.5, "b.mp4", size=(1280, 800))
        for args in (cut, card):
            for part in ("libx264", "yuv420p", "-r"):
                self.assertIn(part, " ".join(args))
        self.assertIn("-loop", card)
        self.assertEqual(card[card.index("-t") + 1], "2.5")

    def test_plan_speeds_up_only_long_waits(self):
        plan = capture.plan_segments(40.0, [{"what": "Downloading", "start": 5.0, "end": 30.0},
                                            {"what": "Loading", "start": 32.0, "end": 34.0}], target_s=4)
        self.assertEqual(plan, [{"start": 0.0, "end": 5.0, "factor": 1},
                                {"start": 5.0, "end": 30.0, "factor": 7, "what": "Downloading"},
                                {"start": 30.0, "end": 40.0, "factor": 1}])

    def test_concat_list_quotes_paths(self):
        text = capture.concat_list([Path("/tmp/a b/one.webm"), Path("/tmp/it's.webm")])
        self.assertEqual(text, "file '/tmp/a b/one.webm'\nfile '/tmp/it'\\''s.webm'\n")

    def test_concat_list_is_the_same_on_windows(self):
        # ffmpeg reads forward slashes on every OS; a backslash path would make the test (and the list) per-OS.
        self.assertEqual(capture.concat_list([PureWindowsPath(r"C:\work\a b\one.webm")]),
                         "file 'C:/work/a b/one.webm'\n")


class TestWords(unittest.TestCase):
    def test_duration_text(self):
        self.assertEqual(capture.duration_text(4.2), "4 s")
        self.assertEqual(capture.duration_text(192), "3 min 12 s")
        self.assertEqual(capture.duration_text(3600), "60 min 0 s")

    def test_speedup_note_states_the_real_time(self):
        self.assertEqual(capture.speedup_note("Downloading", 192, 8), "Downloading took 3 min 12 s. Shown 8x faster.")


class TestCast(unittest.TestCase):
    def test_asciicast_v2(self):
        cast = capture.Cast(100, 30, "serve")
        cast.add(0.0, "hello\r\n")
        cast.add(1.25, "\x1b[32mok\x1b[0m")
        lines = cast.text().splitlines()
        head = json.loads(lines[0])
        self.assertEqual((head["version"], head["width"], head["height"], head["title"]), (2, 100, 30, "serve"))
        self.assertEqual(json.loads(lines[1]), [0.0, "o", "hello\r\n"])
        self.assertEqual(json.loads(lines[2]), [1.25, "o", "\x1b[32mok\x1b[0m"])

    def test_events_never_go_back_in_time(self):
        cast = capture.Cast(80, 24, "t")
        cast.add(2.0, "a")
        cast.add(1.0, "b")
        self.assertEqual([json.loads(x)[0] for x in cast.text().splitlines()[1:]], [2.0, 2.0])

    def test_user_paths_are_replaced(self):
        # A recording on someone's own computer must not publish their user name.
        cast = capture.Cast(80, 24, "t", home="/home/alice")
        cast.add(0, "models in /home/alice/llama-cpp-launchpad/models\r\n")
        self.assertIn("~/llama-cpp-launchpad/models", cast.text())
        self.assertNotIn("alice", cast.text())
        self.assertTrue(cast.redacted, "the manifest must say the recording was changed")
        clean = capture.Cast(80, 24, "t", home="/home/alice")
        clean.add(0, "nothing personal\r\n")
        self.assertFalse(clean.redacted)


class TestWriteManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_a_new_run_replaces_the_files_it_made_and_keeps_the_rest(self):
        path = self.tmp / "manifest.json"
        capture.write_manifest(path, "r1", run_record(), [{"file": "a.png", "kind": "screenshot", "shows": "A"},
                                                          {"file": "b.png", "kind": "screenshot", "shows": "B"}])
        capture.write_manifest(path, "r2", run_record(date="2026-12-01"),
                               [{"file": "b.png", "kind": "screenshot", "shows": "B again"}])
        m = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual({c["file"]: c["run"] for c in m["captures"]}, {"a.png": "r1", "b.png": "r2"})
        self.assertEqual(sorted(m["runs"]), ["r1", "r2"])

    def test_a_run_nothing_uses_any_more_is_dropped(self):
        path = self.tmp / "manifest.json"
        capture.write_manifest(path, "r1", run_record(), [{"file": "a.png", "kind": "screenshot", "shows": "A"}])
        capture.write_manifest(path, "r2", run_record(), [{"file": "a.png", "kind": "screenshot", "shows": "A"}])
        self.assertEqual(sorted(json.loads(path.read_text(encoding="utf-8"))["runs"]), ["r2"])


if __name__ == "__main__":
    unittest.main()
