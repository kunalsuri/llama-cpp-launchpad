"""llama-cpp-launchpad: read a GGUF model's header, and work out how much memory it needs.

A .gguf file starts with a header of key/value metadata (spec: github.com/ggml-org/ggml, docs/gguf.md). It holds
exactly what the old estimate had to guess: how many layers the model has, how many key/value heads each layer
keeps and how wide they are, and the context it was trained on. With those, the context cache is arithmetic:

    cache bytes = context x sum over layers (kv_heads x (key_length + value_length)) x bytes per element

Some models keep less than that, and this file says so instead of pretending to be exact:
  - sliding-window attention (Gemma 2/3, ...): some layers only keep the last N tokens  -> "at most" figure
  - compressed attention (DeepSeek MLA): the cache is smaller than the plain formula       -> "at most" figure
  - recurrent layers (Mamba, RWKV, hybrids): a fixed-size state, not counted here         -> said so

Python standard library only. Reads files it is given and never writes. The network read (the first megabytes of
a file on Hugging Face, with an HTTP Range request) goes through model_setup.py, which owns all Hub traffic.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

MAGIC = b"GGUF"
MIB = 1048576
MAX_HEADER_BYTES = 64 * MIB          # a header bigger than this is not one we should be reading
OVERHEAD_MB = 600                    # compute buffers and runtime (as hf_discover.OVERHEAD_MB)
SMALL_ARRAY = 4096                   # arrays up to this length are kept (per-layer head counts); longer ones skipped

# GGUF value types (docs/gguf.md, enum gguf_metadata_value_type) -> struct format, size in bytes.
_SCALARS = {0: ("<B", 1), 1: ("<b", 1), 2: ("<H", 2), 3: ("<h", 2), 4: ("<I", 4), 5: ("<i", 4), 6: ("<f", 4),
            7: ("<?", 1), 10: ("<Q", 8), 11: ("<q", 8), 12: ("<d", 8)}
_STRING, _ARRAY = 8, 9

# Bytes per cached element for each llama-server --cache-type-k / --cache-type-v value. Quantized types store
# blocks of 32 values: q8_0 = 32 bytes + a 2-byte scale, q4_0 = 16 + 2, q4_1 = 16 + 2 + 2, q5_0 = 20 + 2, ...
CACHE_TYPES = {"f32": 4.0, "f16": 2.0, "bf16": 2.0, "q8_0": 34 / 32, "q4_0": 18 / 32, "q4_1": 20 / 32,
               "iq4_nl": 18 / 32, "q5_0": 22 / 32, "q5_1": 24 / 32}


class GGUFError(ValueError):
    """Not a GGUF file, a version this reader does not know, or a header that ends too early."""


class _Reader:
    def __init__(self, stream, limit: int):
        self.stream, self.limit, self.pos = stream, limit, 0

    def read(self, n: int) -> bytes:
        if n < 0 or self.pos + n > self.limit:
            raise GGUFError(f"the header is larger than {self.limit // MIB} MB, or a length in it is wrong")
        out = b""
        while len(out) < n:                                  # network streams can return less than asked
            chunk = self.stream.read(n - len(out))
            if not chunk:
                raise GGUFError("the file ends inside its header (it may be incomplete)")
            out += chunk
        self.pos += n
        return out

    def skip(self, n: int) -> None:
        while n > 0:
            step = min(n, MIB)
            self.read(step)
            n -= step

    def unpack(self, fmt: str, size: int):
        return struct.unpack(fmt, self.read(size))[0]

    def string(self) -> str:
        n = self.unpack("<Q", 8)
        return self.read(n).decode("utf-8", errors="replace")


def _value(r: _Reader, vtype: int):
    if vtype in _SCALARS:
        return r.unpack(*_SCALARS[vtype])
    if vtype == _STRING:
        return r.string()
    if vtype == _ARRAY:
        etype, count = r.unpack("<I", 4), r.unpack("<Q", 8)
        keep = count <= SMALL_ARRAY and etype != _ARRAY
        if etype in _SCALARS and not keep:                   # e.g. token scores: skip without decoding
            r.skip(_SCALARS[etype][1] * count)
            return None
        items = [_value(r, etype) for _ in range(count)]     # strings (vocabularies) must be read one by one
        return items if keep else None
    raise GGUFError(f"unknown value type {vtype} in the header")


def read_header(stream, limit: int = MAX_HEADER_BYTES, stop_at_tokenizer: bool = False) -> dict:
    """Read the metadata of a GGUF file from a binary stream -> {key: value}. Long arrays (the vocabulary) are
    read past and stored as None. stop_at_tokenizer: stop at the first "tokenizer." key once the model's shape is
    known (converters write the shape first), so a network read does not fetch a whole vocabulary."""
    r = _Reader(stream, limit)
    try:
        magic = r.read(4)
    except GGUFError:
        magic = b""                                          # shorter than the magic itself
    if magic != MAGIC:
        raise GGUFError("not a GGUF file")
    version = r.unpack("<I", 4)
    if version not in (2, 3):
        raise GGUFError(f"GGUF version {version} is not supported (2 and 3 are)")
    r.unpack("<Q", 8)                                        # tensor count: not needed
    n_kv = r.unpack("<Q", 8)
    meta = {"__version__": version}
    for _ in range(n_kv):
        key = r.string()
        if stop_at_tokenizer and key.startswith("tokenizer.") and shape(meta):
            meta["__partial__"] = True
            break
        meta[key] = _value(r, r.unpack("<I", 4))
    return meta


def read_file(path) -> dict:
    """The header of a .gguf file on disk (the first part, for a split model)."""
    with open(path, "rb") as f:
        return read_header(f)


# --- The model's shape and its memory ---------------------------------------------------------------------
def _per_layer(value, n_layer: int) -> list:
    if isinstance(value, list):
        return [int(v) for v in value[:n_layer]] + [0] * max(0, n_layer - len(value))
    return [int(value or 0)] * n_layer


def shape(meta: dict):
    """The numbers the cache depends on -> dict, or None when the header lacks them (not a language model, or a
    layout this reader does not know)."""
    arch = meta.get("general.architecture")
    if not isinstance(arch, str) or not arch:
        return None
    g = lambda k: meta.get(f"{arch}.{k}")                    # noqa: E731
    n_layer = int(g("block_count") or 0)
    n_embd = int(g("embedding_length") or 0)
    heads = g("attention.head_count")
    if not n_layer or not n_embd or heads is None:
        return None
    n_head = _per_layer(heads, n_layer)
    kv = g("attention.head_count_kv")
    n_head_kv = _per_layer(kv, n_layer) if kv is not None else list(n_head)
    widest = max(n_head) or 1
    k_len = int(g("attention.key_length") or n_embd // widest)
    v_len = int(g("attention.value_length") or n_embd // widest)
    notes = []
    if g("attention.sliding_window"):
        notes.append("sliding")
    if g("attention.kv_lora_rank"):
        notes.append("compressed")
    if any(k.startswith(f"{arch}.ssm.") or k.startswith(f"{arch}.rwkv.") or k.startswith(f"{arch}.wkv.")
           for k in meta):
        notes.append("recurrent")
    return {"arch": arch, "n_layer": n_layer, "n_embd": n_embd, "n_head_kv": n_head_kv, "k_len": k_len,
            "v_len": v_len, "train_ctx": int(g("context_length") or 0), "notes": notes,
            "name": meta.get("general.name") or ""}


def cache_type_bytes(name: str) -> float:
    if name not in CACHE_TYPES:
        raise ValueError(f"unknown cache type {name!r}; llama-server takes: {', '.join(CACHE_TYPES)}")
    return CACHE_TYPES[name]


def kv_cache_bytes(s: dict, ctx: int, type_k: str = "f16", type_v: str = "f16") -> int:
    """Bytes of context cache for `ctx` tokens. ctx 0 means what llama-server does with -c 0: the trained context."""
    ctx = ctx or s["train_ctx"]
    heads = sum(s["n_head_kv"])
    per_token = heads * (s["k_len"] * cache_type_bytes(type_k) + s["v_len"] * cache_type_bytes(type_v))
    return int(ctx * per_token)


def estimate(s: dict, weights_bytes: int, ctx: int, type_k: str = "f16", type_v: str = "f16") -> dict:
    """Memory to run the model: weights + cache + overhead, in MB, and how sure the figure is."""
    kv = kv_cache_bytes(s, ctx, type_k, type_v) // MIB
    weights = weights_bytes // MIB
    bound = "at_most" if {"sliding", "compressed"} & set(s["notes"]) else "exact"
    return {"weights_mb": weights, "kv_mb": kv, "overhead_mb": OVERHEAD_MB, "need_mb": weights + kv + OVERHEAD_MB,
            "ctx": ctx or s["train_ctx"], "train_ctx": s["train_ctx"], "type_k": type_k, "type_v": type_v,
            "bound": bound, "notes": list(s["notes"])}


NOTE_TEXT = {
    "sliding": "Some layers only remember a window of recent text, so the real cache is smaller than this.",
    "compressed": "This model compresses its cache, so the real cache is smaller than this.",
    "recurrent": "Its recurrent layers keep a small fixed-size state that is not counted here.",
}


def weights_bytes(path: Path) -> int:
    """Size of a model on disk; a split model (-00001-of-00003.gguf) is all of its parts."""
    path = Path(path)
    m = re.match(r"^(.*)-00001-of-(\d{5})\.gguf$", path.name, re.I)
    if not m:
        return path.stat().st_size
    total = 0
    for i in range(1, int(m.group(2)) + 1):
        part = path.with_name(f"{m.group(1)}-{i:05d}-of-{m.group(2)}.gguf")
        total += part.stat().st_size if part.is_file() else 0
    return total


def describe(path) -> dict:
    """Everything the page and the CLI show about one local model file -> dict (with "error" if unreadable)."""
    path = Path(path)
    try:
        meta = read_file(path)
    except (OSError, GGUFError) as e:
        return {"file": path.name, "error": str(e)}
    s = shape(meta)
    out = {"file": path.name, "arch": meta.get("general.architecture") or "", "name": meta.get("general.name") or ""}
    if not s:
        out["error"] = "the header does not describe a language model's layers"
        return out
    out.update(shape=s, weights_bytes=weights_bytes(path))
    return out


def main(argv=None) -> int:
    """`python utils/gguf.py FILE [--ctx N] [--cache-type-k T] [--cache-type-v T]`: print what FILE needs."""
    import argparse
    p = argparse.ArgumentParser(prog="gguf", description="How much memory a .gguf model needs to run.")
    p.add_argument("file")
    p.add_argument("--ctx", type=int, default=0, help="context length (default: the model's trained context)")
    p.add_argument("--cache-type-k", default="f16", choices=sorted(CACHE_TYPES))
    p.add_argument("--cache-type-v", default="f16", choices=sorted(CACHE_TYPES))
    a = p.parse_args(argv)
    d = describe(a.file)
    if d.get("error"):
        print(f"{d['file']}: {d['error']}")
        return 1
    e = estimate(d["shape"], d["weights_bytes"], a.ctx, a.cache_type_k, a.cache_type_v)
    s = d["shape"]
    print(f"{d['file']}  ({s['arch']}, {s['n_layer']} layers, trained on {s['train_ctx']} tokens)")
    word = "at most " if e["bound"] == "at_most" else ""
    print(f"  weights {e['weights_mb']} MB + context cache {word}{e['kv_mb']} MB ({e['ctx']} tokens, "
          f"K {e['type_k']} / V {e['type_v']}) + overhead {e['overhead_mb']} MB = {word}{e['need_mb']} MB")
    for n in e["notes"]:
        print("  " + NOTE_TEXT[n])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
