"""Tests for utils/gguf.py: reading a model's header and the memory it needs.

The fixtures (tests/fixtures/*-shape.gguf) were written by llama.cpp's own `gguf` package
(tests/fixtures/make_gguf_fixtures.py), so the reader is checked against the reference writer, not against itself.
"""
import io
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "utils"))
import gguf  # noqa: E402

FIX = HERE / "fixtures"
MB = 1048576


class CountingStream(io.BytesIO):
    """A stream that records how many bytes were read from it (a network read should stop early)."""
    def __init__(self, data):
        super().__init__(data)
        self.taken = 0

    def read(self, n=-1):
        out = super().read(n)
        self.taken += len(out)
        return out


class TestReadHeader(unittest.TestCase):
    def test_reads_the_shape_the_reference_writer_wrote(self):
        meta = gguf.read_file(FIX / "llama-shape.gguf")
        self.assertEqual(meta["general.architecture"], "llama")
        self.assertEqual(meta["general.name"], "Tiny Llama Shape")
        self.assertEqual(meta["llama.block_count"], 32)
        self.assertEqual(meta["llama.attention.head_count_kv"], 8)
        self.assertEqual(meta["llama.context_length"], 131072)
        self.assertIs(meta["tokenizer.ggml.add_bos_token"], True)
        self.assertIsNone(meta["tokenizer.ggml.tokens"], "a 5000-word vocabulary is read past, not kept")
        self.assertAlmostEqual(meta["llama.rope.freq_base"], 500000.0)

    def test_shape(self):
        s = gguf.shape(gguf.read_file(FIX / "llama-shape.gguf"))
        self.assertEqual((s["arch"], s["n_layer"], s["n_embd"]), ("llama", 32, 4096))
        self.assertEqual(s["n_head_kv"], [8] * 32)
        self.assertEqual((s["k_len"], s["v_len"]), (128, 128), "no key_length key: n_embd / n_head")
        self.assertEqual(s["train_ctx"], 131072)
        self.assertEqual(s["notes"], [])

    def test_per_layer_head_counts_are_summed_and_layers_without_attention_cost_nothing(self):
        s = gguf.shape(gguf.read_file(FIX / "per-layer-shape.gguf"))
        self.assertEqual(s["n_head_kv"], [2, 4, 0, 0])
        # (2 + 4) heads x (64 + 64) values x 2 bytes (f16) per token
        self.assertEqual(gguf.kv_cache_bytes(s, 1), 6 * 128 * 2)

    def test_sliding_window_models_are_an_upper_bound(self):
        s = gguf.shape(gguf.read_file(FIX / "gemma3-shape.gguf"))
        self.assertEqual((s["k_len"], s["v_len"]), (256, 256), "key_length given: used, not n_embd / n_head")
        self.assertIn("sliding", s["notes"])
        e = gguf.estimate(s, 2 * 1024 * MB, 8192)
        self.assertEqual(e["bound"], "at_most")
        self.assertIn("window", gguf.NOTE_TEXT["sliding"])

    def test_a_network_read_stops_before_the_vocabulary(self):
        data = (FIX / "llama-shape.gguf").read_bytes()
        whole, early = CountingStream(data), CountingStream(data)
        gguf.read_header(whole)
        meta = gguf.read_header(early, stop_at_tokenizer=True)
        self.assertTrue(meta.get("__partial__"))
        self.assertEqual(gguf.shape(meta)["n_layer"], 32)
        self.assertLess(early.taken, whole.taken // 10, (early.taken, whole.taken))

    def test_stop_at_tokenizer_keeps_reading_while_the_shape_is_unknown(self):
        """A file that puts tokenizer keys first must still be read until the shape is known."""
        def s(text):
            b = text.encode()
            return struct.pack("<Q", len(b)) + b
        kvs = [(s("tokenizer.ggml.model"), struct.pack("<I", 8) + s("gpt2")),
               (s("general.architecture"), struct.pack("<I", 8) + s("llama")),
               (s("llama.block_count"), struct.pack("<I", 4) + struct.pack("<I", 2)),
               (s("llama.embedding_length"), struct.pack("<I", 4) + struct.pack("<I", 64)),
               (s("llama.attention.head_count"), struct.pack("<I", 4) + struct.pack("<I", 4))]
        blob = b"GGUF" + struct.pack("<IQQ", 3, 0, len(kvs)) + b"".join(k + v for k, v in kvs)
        meta = gguf.read_header(io.BytesIO(blob), stop_at_tokenizer=True)
        self.assertEqual(meta["tokenizer.ggml.model"], "gpt2")
        self.assertEqual(gguf.shape(meta)["n_layer"], 2)

    def test_bad_files_say_what_is_wrong(self):
        data = (FIX / "llama-shape.gguf").read_bytes()
        cases = {b"PK\x03\x04" + data[4:]: "not a GGUF file", b"x": "not a GGUF file", b"": "not a GGUF file",
                 data[:4] + struct.pack("<I", 99) + data[8:]: "version 99",
                 data[:200]: "ends inside its header"}
        for blob, want in cases.items():
            with self.assertRaises(gguf.GGUFError) as cm:
                gguf.read_header(io.BytesIO(blob))
            self.assertIn(want, str(cm.exception))

    def test_a_huge_length_is_refused_without_allocating_it(self):
        # first key's length claims 2**62 bytes: must fail cleanly, not try to read (or allocate) that much
        blob = b"GGUF" + struct.pack("<IQQ", 3, 0, 1) + struct.pack("<Q", 2 ** 62)
        with self.assertRaises(gguf.GGUFError) as cm:
            gguf.read_header(io.BytesIO(blob))
        self.assertIn("larger than", str(cm.exception))

    def test_odd_values_in_a_header_give_no_shape_instead_of_an_exception(self):
        """Review finding: block_count stored as a string raised ValueError out of describe() and took
        /api/models down; a list raised TypeError; a huge count built an enormous list."""
        base = {"general.architecture": "llama", "llama.embedding_length": 64, "llama.attention.head_count": 4}
        for bad in ("32", [32], 10 ** 12, -1, None):
            with self.subTest(block_count=bad):
                self.assertIsNone(gguf.shape(dict(base, **{"llama.block_count": bad})))
        self.assertIsNone(gguf.shape(dict(base, **{"llama.block_count": 2, "llama.attention.head_count_kv": "8"})))
        self.assertIsNone(gguf.shape(dict(base, **{"llama.block_count": 2, "llama.context_length": "x"})))

    def test_describe_never_raises_on_a_strange_header(self):
        def s(text):
            b = text.encode()
            return struct.pack("<Q", len(b)) + b
        kvs = [(s("general.architecture"), struct.pack("<I", 8) + s("llama")),
               (s("llama.block_count"), struct.pack("<I", 8) + s("thirty-two")),
               (s("llama.embedding_length"), struct.pack("<I", 4) + struct.pack("<I", 64)),
               (s("llama.attention.head_count"), struct.pack("<I", 4) + struct.pack("<I", 4))]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "odd.gguf")
            p.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, len(kvs)) + b"".join(k + v for k, v in kvs))
            self.assertIn("error", gguf.describe(p))

    def test_a_file_without_layers_has_no_shape(self):
        self.assertIsNone(gguf.shape({"general.architecture": "clip"}))
        self.assertIsNone(gguf.shape({}))


class TestMemory(unittest.TestCase):
    def setUp(self):
        self.s = gguf.shape(gguf.read_file(FIX / "llama-shape.gguf"))

    def test_llama_8b_shape_needs_one_gigabyte_of_cache_at_8k_in_f16(self):
        # 32 layers x 8 heads x (128 + 128) x 2 bytes = 128 KiB per token; x 8192 tokens = 1 GiB
        self.assertEqual(gguf.kv_cache_bytes(self.s, 8192), 1024 * MB)

    def test_quantized_cache_is_smaller_by_its_block_size(self):
        self.assertEqual(gguf.kv_cache_bytes(self.s, 8192, "q8_0", "q8_0"), 1024 * MB * 34 // 64)
        self.assertEqual(gguf.kv_cache_bytes(self.s, 8192, "q8_0", "f16"), 512 * MB + 512 * MB * 34 // 64)
        with self.assertRaises(ValueError):
            gguf.kv_cache_bytes(self.s, 8192, "q3_k")

    def test_context_zero_means_the_trained_context_as_llama_server_does(self):
        e = gguf.estimate(self.s, 4 * 1024 * MB, 0)
        self.assertEqual(e["ctx"], 131072)
        self.assertEqual(e["kv_mb"], 16384)
        self.assertEqual(e["need_mb"], 4096 + 16384 + gguf.OVERHEAD_MB)
        self.assertEqual(e["bound"], "exact")

    def test_compressed_and_recurrent_models_are_labelled(self):
        meta = {"general.architecture": "deepseek2", "deepseek2.block_count": 2, "deepseek2.embedding_length": 64,
                "deepseek2.attention.head_count": 4, "deepseek2.attention.kv_lora_rank": 16}
        self.assertEqual(gguf.estimate(gguf.shape(meta), 0, 10)["bound"], "at_most")
        meta = {"general.architecture": "jamba", "jamba.block_count": 2, "jamba.embedding_length": 64,
                "jamba.attention.head_count": 4, "jamba.ssm.state_size": 16}
        s = gguf.shape(meta)
        self.assertEqual(s["notes"], ["recurrent"])
        self.assertEqual(gguf.estimate(s, 0, 10)["bound"], "at_least", "the recurrent state is not counted")


class TestFiles(unittest.TestCase):
    def test_a_split_model_weighs_all_its_parts(self):
        with tempfile.TemporaryDirectory() as d:
            for i, n in ((1, 100), (2, 50), (3, 25)):
                Path(d, f"m-Q4-{i:05d}-of-00003.gguf").write_bytes(b"x" * n)
            Path(d, "single.gguf").write_bytes(b"x" * 7)
            self.assertEqual(gguf.weights_bytes(Path(d, "m-Q4-00001-of-00003.gguf")), 175)
            self.assertEqual(gguf.weights_bytes(Path(d, "single.gguf")), 7)

    def test_describe_reports_unreadable_files_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d, "bad.gguf")
            bad.write_bytes(b"nope")
            self.assertIn("not a GGUF file", gguf.describe(bad)["error"])
            self.assertIn("error", gguf.describe(Path(d, "missing.gguf")))
        good = gguf.describe(FIX / "llama-shape.gguf")
        self.assertNotIn("error", good)
        self.assertEqual(good["weights_bytes"], (FIX / "llama-shape.gguf").stat().st_size)

    def test_command_line(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = gguf.main([str(FIX / "llama-shape.gguf"), "--ctx", "8192"])
        self.assertEqual(rc, 0)
        self.assertIn("32 layers", out.getvalue())
        self.assertIn("context cache 1024 MB (8192 tokens", out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            rc = gguf.main([str(FIX / "gemma3-shape.gguf"), "--ctx", "4096"])
        self.assertEqual(rc, 0)
        self.assertIn("at most", out.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(gguf.main([str(FIX / "make_gguf_fixtures.py")]), 1)


if __name__ == "__main__":
    unittest.main()
