"""Tests for utils/hf_discover.py and `model-setup --discover`. No network, GPU or llama.cpp needed:
the Hugging Face API is faked, as in test_model_setup.py. Run: python3 -m unittest discover -s tests -v
"""
import json
import sys
import unittest
import unittest.mock
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "utils"))
sys.path.insert(0, str(HERE))
import hf_discover as hd  # noqa: E402
import test_model_setup as tms  # noqa: E402  (module import: its test classes are not collected twice)
import model_setup as ms  # noqa: E402

GB = 1073741824
MB = 1048576


def sib(name, size):
    return {"rfilename": name, "size": size}


def detail(files, arch="llama", total=None, **extra):
    d = {"gated": False, "private": False, "downloads": 1000, "likes": 5, "lastModified": "2026-09-01T00:00:00.000Z",
         "gguf": {"architecture": arch, "context_length": 32768, **({"total": total} if total else {})},
         "siblings": [sib(*f) for f in files]}
    d.update(extra)
    return d


def tps_for(hw):
    return lambda size, mode: ms.est_tps(size, mode, hw)


class TestNames(unittest.TestCase):
    def test_params(self):
        self.assertEqual(hd.parse_params_b("Qwen3-Coder-30B-A3B-Instruct-GGUF"), 30.0)
        self.assertEqual(hd.parse_params_b("Llama-3.2-1B-Instruct"), 1.0)
        self.assertEqual(hd.parse_params_b("gemma-3-4b-it"), 4.0)
        self.assertEqual(hd.parse_params_b("LFM2.5-230M"), None)
        self.assertEqual(hd.parse_active_b("Qwen3-Coder-30B-A3B-Instruct-GGUF"), 3.0)
        self.assertIsNone(hd.parse_active_b("Llama-3.2-1B"))

    def test_quant_names(self):
        for name, want in [("Model-Q4_K_M.gguf", "Q4_K_M"), ("dir/Model-UD-Q4_K_XL.gguf", "Q4_K_XL"),
                           ("m-q8_0.gguf", "Q8_0"), ("m-IQ4_XS.gguf", "IQ4_XS"), ("m-BF16.gguf", "BF16"),
                           ("m.F16.gguf", "F16"), ("Qwen3-4B.gguf", ""), ("m-Q6_K-00001-of-00002.gguf", "Q6_K")]:
            self.assertEqual(hd.quant_of(name), want, name)

    def test_bits_rank_quality(self):
        order = ["IQ2_XS", "Q3_K_M", "Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0", "F16"]
        bits = [hd.quant_bits(q) for q in order]
        self.assertEqual(bits, sorted(bits))
        self.assertLess(hd.quant_bits("IQ1_S"), 3)


class TestFiles(unittest.TestCase):
    def test_singles_shards_and_junk(self):
        g = hd.group_files([
            sib("README.md", 9000), sib("M-Q4_K_M.gguf", 2 * GB), sib("mmproj-M-f16.gguf", 800 * MB),
            sib("M-imatrix.gguf", 900 * MB), sib("tiny-Q4_0.gguf", 100 * MB),
            sib("big/M-Q8_0-00001-of-00002.gguf", 5 * GB), sib("big/M-Q8_0-00002-of-00002.gguf", 4 * GB),
            sib("broken-Q6_K-00001-of-00003.gguf", 3 * GB), sib("broken-Q6_K-00003-of-00003.gguf", 3 * GB)])
        self.assertEqual([(x["quant"], x["size"], len(x["files"])) for x in g],
                         [("Q4_K_M", 2 * GB, 1), ("Q8_0", 9 * GB, 2)])
        self.assertEqual(g[1]["files"][0][0], "big/M-Q8_0-00001-of-00002.gguf")   # first shard is what llama.cpp loads


class TestFit(unittest.TestCase):
    def hw(self, ram=16384, vram=0, kind="none", usable=False):
        return ms.Hw(ram_mb=ram, cores=8, gpu_kind=kind, gpu_name="T", vram_mb=vram, gpu_usable=usable)

    def test_kv_cache_grows_with_model_and_context(self):
        small, big = hd.kv_cache_mb(1, 4096), hd.kv_cache_mb(70, 4096)
        self.assertTrue(100 < hd.kv_cache_mb(8, 4096) < 1000)
        self.assertGreater(big, small * 5)
        self.assertEqual(hd.kv_cache_mb(8, 4096), hd.kv_cache_mb(8, 8192, train_ctx=4096))   # capped by training length

    def test_place(self):
        gpu = self.hw(32768, 8192, "nvidia", True)
        self.assertEqual(hd.place(6000, gpu), ("gpu", 1.0))
        mode, share = hd.place(12000, gpu)
        self.assertEqual(mode, "partial")
        self.assertTrue(0.5 < share < 0.7)
        self.assertEqual(hd.place(30000, gpu)[0], "no")
        self.assertEqual(hd.place(12000, self.hw(32768, 8192, "nvidia", False)), ("cpu", 0.0))   # GPU unused by build
        self.assertEqual(hd.place(11000, self.hw(16384))[0], "tight")
        self.assertEqual(hd.place(9000, self.hw(16384))[0], "cpu")
        self.assertEqual(hd.place(8000, self.hw(16384, 0, "apple", True))[0], "gpu")

    def test_partial_speed_between_cpu_and_gpu(self):
        hw = self.hw(32768, 8192, "nvidia", True)
        f = tps_for(hw)
        size = 10 * GB
        part = hd.speed(size, "partial", 0.6, f)
        self.assertTrue(f(size, "cpu") < part < f(size, "gpu"))

    def test_budget_and_prefilter(self):
        cpu = self.hw(8192)
        self.assertTrue(hd.plausibly_fits("a/Tiny-1B-GGUF", cpu))
        self.assertTrue(hd.plausibly_fits("a/NoSizeInName-GGUF", cpu))
        self.assertFalse(hd.plausibly_fits("a/Huge-70B-GGUF", cpu))
        self.assertTrue(hd.plausibly_fits("a/Huge-70B-GGUF", self.hw(131072)))


class TestEvaluate(unittest.TestCase):
    hw = ms.Hw(ram_mb=16384, cores=8, gpu_kind="nvidia", gpu_name="T", vram_mb=12288, gpu_usable=True)

    def ev(self, repo, d, **kw):
        return hd.evaluate_repo(repo, d, self.hw, tps_for(self.hw), **kw)

    def test_picks_highest_quality_that_fits(self):
        d = detail([("M-Q2_K.gguf", 3 * GB), ("M-Q4_K_M.gguf", 5 * GB), ("M-Q6_K.gguf", 7 * GB),
                    ("M-Q8_0.gguf", 15 * GB)], total=8_000_000_000)
        r, why = self.ev("o/M-8B-GGUF", d)
        self.assertEqual((r["quant"], r["mode"], why), ("Q6_K", "gpu", ""))
        self.assertEqual(r["other_quants"], 2)
        self.assertEqual(r["compat"], "ok")

    def test_prefers_smaller_file_beyond_8_bit(self):
        d = detail([("M-F16.gguf", 3 * GB), ("M-Q8_0.gguf", 1600 * MB)], total=1_500_000_000)
        self.assertEqual(self.ev("o/M-1.5B-GGUF", d)[0]["quant"], "Q8_0")

    def test_split_model_is_summed_and_downloadable(self):
        d = detail([("M-Q4_K_M-00001-of-00002.gguf", 5 * GB), ("M-Q4_K_M-00002-of-00002.gguf", 4 * GB)])
        r, _ = self.ev("o/M-14B-GGUF", d)
        self.assertEqual((r["size"], len(r["files"]), r["mode"]), (9 * GB, 2, "gpu"))

    def test_reasons(self):
        big = detail([("M-Q4_K_M.gguf", 40 * GB)], total=70_000_000_000)
        self.assertEqual(self.ev("o/M-70B", big)[1], "too-big")
        self.assertEqual(self.ev("o/M", detail([("M-Q4_K_M.gguf", GB)], gated="auto"))[1], "gated")
        self.assertEqual(self.ev("o/M", detail([("README.md", 5)]))[1], "no-gguf")
        self.assertEqual(self.ev("o/M", detail([("m-F16.gguf", GB)], arch="bert"))[1], "not-chat")
        self.assertEqual(self.ev("o/M", None)[1], "unreadable")
        # fits in RAM but the speed estimate is below the floor
        cpu_hw = ms.Hw(ram_mb=32768, cores=8)
        slow = detail([("M-Q4_K_M.gguf", 14 * GB)], total=24_000_000_000)
        self.assertEqual(hd.evaluate_repo("o/M-24B", slow, cpu_hw, tps_for(cpu_hw), min_tps=5)[1], "too-slow")

    def test_unknown_architecture_is_flagged_not_dropped(self):
        r, _ = self.ev("o/M-3B", detail([("M-Q4_K_M.gguf", 2 * GB)], arch="brandnewarch"))
        self.assertEqual(r["compat"], "unverified")

    def test_moe_is_faster_than_dense_of_same_size(self):
        files = [("M-Q4_K_M.gguf", 9 * GB)]
        dense, _ = self.ev("o/Dense-14B", detail(files, total=14_000_000_000))
        moe, _ = self.ev("o/Moe-14B-A2B", detail(files, total=14_000_000_000))
        self.assertTrue(moe["moe"])
        self.assertGreater(moe["tps"], dense["tps"])

    def test_context_changes_the_answer(self):
        d = detail([("M-Q4_K_M.gguf", 4 * GB)], total=7_000_000_000)
        short, _ = self.ev("o/M-7B", d, ctx=2048)
        long, _ = self.ev("o/M-7B", d, ctx=16384)
        self.assertGreater(long["need_mb"], short["need_mb"])
        self.assertEqual(self.ev("o/M-7B", d, ctx=10_000_000)[0]["ctx"], 32768)        # capped by the model's own limit

    def test_low_bit_flag(self):
        r, _ = self.ev("o/M-14B", detail([("M-IQ1_S.gguf", 3 * GB)], total=14_000_000_000))
        self.assertTrue(r["low_quality"])


class TestRank(unittest.TestCase):
    rows = [{"repo": "slow-pop", "tps": 4, "size": 9, "downloads": 9000, "likes": 0},
            {"repo": "fast", "tps": 40, "size": 1, "downloads": 10, "likes": 0},
            {"repo": "pop", "tps": 12, "size": 5, "downloads": 500, "likes": 10}]

    def test_orders(self):
        names = lambda s: [r["repo"] for r in hd.rank(self.rows, s)]   # noqa: E731
        self.assertEqual(names("popular"), ["pop", "fast", "slow-pop"])    # usable first, then popularity
        self.assertEqual(names("size"), ["pop", "fast", "slow-pop"])
        self.assertEqual(names("speed"), ["fast", "pop", "slow-pop"])

    def test_list_urls_and_parse(self):
        urls = hd.list_urls("https://huggingface.co/api", "trending", "coder x", [], ["a", "b"])
        self.assertEqual(len(urls), 3)
        self.assertIn("sort=trendingScore", urls[0])
        self.assertIn("search=coder%20x", urls[0])
        self.assertIn("author=a", urls[1])
        self.assertEqual(len(hd.list_urls("https://huggingface.co/api", authors=["me"], default_authors=["a"])), 1)
        got = hd.parse_list([{"id": "a/b", "downloads": 3}, {"id": "c/d", "private": True}, {"nope": 1}])
        self.assertEqual(got, [{"id": "a/b", "downloads": 3, "likes": 0}])
        self.assertEqual(hd.parse_list(None), [])


class TestDiscoverCommand(tms.Base):
    """End to end through model_setup.main with a fake Hub."""

    LIST = [
        {"id": "ggml-org/Small-3B-GGUF", "downloads": 9000, "likes": 30},
        {"id": "bartowski/Mid-8B-GGUF", "downloads": 20000, "likes": 50},
        {"id": "unsloth/Huge-70B-GGUF", "downloads": 90000, "likes": 500},
        {"id": "random/Hyped-7B-GGUF", "downloads": 80000, "likes": 800},
        {"id": "ggml-org/Locked-8B-GGUF", "downloads": 7000, "likes": 20},
        {"id": "bartowski/Odd-4B-GGUF", "downloads": 6000, "likes": 9},
        {"id": "ggml-org/Nobody-1B-GGUF", "downloads": 5, "likes": 0},
        {"id": "someone/Private-3B-GGUF", "downloads": 9999, "likes": 9, "private": True},
    ]
    DETAIL = {
        "ggml-org/Small-3B-GGUF": detail([("S-Q4_K_M.gguf", 2 * GB), ("S-Q8_0.gguf", 3400 * MB)], total=3_000_000_000),
        "bartowski/Mid-8B-GGUF": detail([("M-Q4_K_M.gguf", 5 * GB), ("M-Q6_K.gguf", 6600 * MB)], total=8_000_000_000),
        "random/Hyped-7B-GGUF": detail([("H-Q4_K_M.gguf", 4500 * MB)], total=7_000_000_000),
        "ggml-org/Locked-8B-GGUF": detail([("L-Q4_K_M.gguf", 5 * GB)], gated="manual"),
        "bartowski/Odd-4B-GGUF": detail([("O-Q4_K_M.gguf", 2500 * MB)], arch="newarch", total=4_000_000_000),
    }

    def setUp(self):
        super().setUp()
        self.fetched = []
        self.hw16 = ms.Hw(ram_mb=16384, cores=8, gpu_kind="nvidia", gpu_name="Test", vram_mb=8192, gpu_usable=True)
        p = unittest.mock.patch.object(ms, "detect_hw", lambda: self.hw16)
        p.start()
        self.addCleanup(p.stop)

    def fake_http_get(self, url, timeout=25):
        self.fetched.append(url)
        if getattr(self, "offline", False):
            raise urllib.error.URLError("offline")
        if "/models?" in url:
            return json.dumps(self.LIST)
        repo = url.split("/api/models/", 1)[1].split("?", 1)[0]
        if repo in self.DETAIL:
            return json.dumps(self.DETAIL[repo])
        raise urllib.error.HTTPError(url, 404, "nf", None, None)

    def models(self, argv):
        rc, out, _ = self.run_main(["--discover", "--json"] + argv)
        self.assertEqual(rc, 0)
        return json.loads(out)

    def test_json_default_is_trusted_and_fits(self):
        data = self.models([])
        repos = [m["repo"] for m in data["models"]]
        self.assertIn("bartowski/Mid-8B-GGUF", repos)
        self.assertIn("ggml-org/Small-3B-GGUF", repos)
        self.assertNotIn("random/Hyped-7B-GGUF", repos)            # unknown author
        self.assertNotIn("ggml-org/Locked-8B-GGUF", repos)         # gated
        self.assertEqual(data["skipped"].get("gated"), 1)
        self.assertEqual(data["hardware"]["vram_mb"], 8192)
        self.assertFalse(any("Huge-70B" in u and "blobs" in u for u in self.fetched), "hopeless repos are not fetched")
        self.assertFalse(any("Nobody-1B" in u and "blobs" in u for u in self.fetched), "low-download repos are not fetched")
        self.assertFalse(any("Private" in u and "blobs" in u for u in self.fetched))

    def test_all_includes_unknown_authors(self):
        self.assertIn("random/Hyped-7B-GGUF", [m["repo"] for m in self.models(["--all"])["models"]])

    def test_sort_and_top(self):
        data = self.models(["--sort", "size", "--top", "1"])
        self.assertEqual([m["repo"] for m in data["models"]], ["bartowski/Mid-8B-GGUF"])

    def test_table_output_and_flags(self):
        rc, out, _ = self.run_main(["--discover", "--list"])
        self.assertEqual(rc, 0)
        self.assertIn("bartowski/Mid-8B-GGUF", out)
        self.assertIn("architecture not in the known list", out)   # Odd-4B
        self.assertIn("Q6_K", out)

    def test_nothing_fits(self):
        self.hw16.ram_mb, self.hw16.gpu_kind, self.hw16.gpu_usable = 1024, "none", False
        rc, out, _ = self.run_main(["--discover", "--list"])
        self.assertEqual(rc, 1)
        self.assertIn("Nothing", out)

    def test_offline(self):
        self.offline = True
        rc, out, _ = self.run_main(["--discover", "--list"])
        self.assertEqual(rc, 1)
        self.assertIn("Could not reach Hugging Face", out)

    def test_download_pick_installs_and_records(self):
        calls = []
        unittest.mock.patch.object(ms, "download", lambda repo, f, size: calls.append((repo, f)) or (self.tmp / f)).start()
        unittest.mock.patch.object(ms, "check_model_speed", lambda *a: 0).start()
        self.addCleanup(unittest.mock.patch.stopall)
        rc, out, _ = self.run_main(["--discover", "--sort", "size"], stdin="1\n")
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [("bartowski/Mid-8B-GGUF", "M-Q6_K.gguf")])
        self.assertEqual(ms.state_get("installed_repo"), "bartowski/Mid-8B-GGUF")

    def test_no_prompt_default_is_skip(self):
        rc, _, _ = self.run_main(["--discover"], stdin="")
        self.assertEqual(rc, 0)
        self.assertEqual(ms.state_get("installed"), "")


if __name__ == "__main__":
    unittest.main()
