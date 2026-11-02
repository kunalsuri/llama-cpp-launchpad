"""Make the small .gguf header fixtures in this folder with llama.cpp's own writer (the `gguf` package).

Not run by the tests: run it by hand after `pip install gguf` (any recent version), from the repo root:
    python tests/fixtures/make_gguf_fixtures.py
The files hold metadata only (no tensors), so they are a few kilobytes, and utils/gguf.py is checked against bytes
written by the reference implementation rather than by a writer of our own.
"""
from pathlib import Path

import gguf  # noqa: the reference writer, from llama.cpp's gguf-py

HERE = Path(__file__).resolve().parent


def write(name, arch, fill):
    w = gguf.GGUFWriter(str(HERE / name), arch)
    fill(w)
    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_tensors_to_file()
    w.close()


def llama(w):
    # Llama 3.1 8B's shape: 32 layers, 32 query heads, 8 key/value heads (GQA), 4096 wide, 128k context.
    w.add_name("Tiny Llama Shape")
    w.add_block_count(32)
    w.add_context_length(131072)
    w.add_embedding_length(4096)
    w.add_feed_forward_length(14336)
    w.add_head_count(32)
    w.add_head_count_kv(8)
    w.add_layer_norm_rms_eps(1e-5)
    w.add_rope_freq_base(500000.0)
    w.add_tokenizer_model("gpt2")
    w.add_token_list([f"tok{i}" for i in range(5000)])      # a vocabulary the reader must read past
    w.add_token_scores([0.0] * 5000)
    w.add_bool("tokenizer.ggml.add_bos_token", True)


def gemma3(w):
    # Gemma 3 4B's shape: 34 layers, 8 heads, 4 key/value heads of width 256, sliding-window layers.
    w.add_name("Tiny Gemma3 Shape")
    w.add_block_count(34)
    w.add_context_length(131072)
    w.add_embedding_length(2560)
    w.add_head_count(8)
    w.add_head_count_kv(4)
    w.add_key_length(256)
    w.add_value_length(256)
    w.add_sliding_window(1024)
    w.add_token_list([f"t{i}" for i in range(100)])


def per_layer(w):
    # A model whose key/value heads differ per layer (as OpenELM's do), and two layers without attention.
    w.add_name("Per Layer Heads")
    w.add_block_count(4)
    w.add_context_length(2048)
    w.add_embedding_length(1024)
    w.add_head_count([8, 8, 8, 8])
    w.add_head_count_kv([2, 4, 0, 0])
    w.add_key_length(64)
    w.add_value_length(64)


if __name__ == "__main__":
    write("llama-shape.gguf", "llama", llama)
    write("gemma3-shape.gguf", "gemma3", gemma3)
    write("per-layer-shape.gguf", "openelm", per_layer)
    print("wrote", sorted(p.name for p in HERE.glob("*.gguf")))
