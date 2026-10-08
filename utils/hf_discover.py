"""llama-cpp-launchpad: Hugging Face discovery rules.

The logic behind `model-setup --discover`: which GGUF models on the Hub can this machine run with llama.cpp?

This file has no network and no file access. model_setup.py fetches the JSON and passes it in, so every rule
below can be tested offline. Python standard library only.

What it works out for each repo (from the Hub's own metadata, no model is downloaded):
  - the quantizations on offer and their real file sizes (split files are summed)
  - a memory estimate: weights + context cache + overhead (the cache is a rough guess, see kv_cache_mb)
  - where it would run (GPU, GPU+CPU split, CPU) and a speed estimate, using the same rules as model_setup
  - whether llama.cpp knows the architecture
"""
from __future__ import annotations

import re
from urllib.parse import quote

MIB = 1048576
MIN_MODEL_BYTES = 300_000_000    # smaller .gguf files are adapters or draft heads, not models
OVERHEAD_MB = 600                # compute buffers and runtime
DEFAULT_CTX = 4096               # context length the memory estimate assumes
USABLE_TPS = 5                   # at or above this is "usable"

# Architectures (general.architecture) llama.cpp could run when this list was written. A newer one is not an
# error: it is shown as "unverified" because it may need a newer llama.cpp build.
KNOWN_ARCHS = frozenset("""
llama llama4 deci falcon falcon-h1 baichuan grok gpt2 gptj gptneox mpt starcoder starcoder2 refact bloom stablelm
qwen qwen2 qwen2moe qwen2vl qwen3 qwen3moe qwen3vl phi2 phi3 phimoe plamo plamo2 codeshell orion internlm2 minicpm
minicpm3 gemma gemma2 gemma3 gemma3n mamba mamba2 xverse command-r cohere2 dbrx olmo olmo2 olmoe openelm arctic
deepseek deepseek2 chatglm glm4 glm4moe bitnet jais nemotron nemotron_h exaone exaone4 rwkv6 rwkv7 arwkv7 granite
granitemoe granitehybrid chameleon solar smollm3 hunyuan-moe hunyuan-dense lfm2 ernie4_5 ernie4_5-moe gpt-oss
seed_oss smallthinker dots1 plm mistral3 apertus bailingmoe bailingmoe2 afmoe jamba
""".split())
# Embedding, vision and speech files: llama.cpp can load some of them, but they are not chat models.
NOT_CHAT_ARCHS = frozenset({"clip", "bert", "nomic-bert", "nomic-bert-moe", "jina-bert-v2", "neo-bert",
                            "modern-bert", "t5encoder", "wavtokenizer-dec", "mmproj"})


# --- Names: parameter counts and quantizations ----------------------------------------------------
_PARAMS = re.compile(r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)[Bb](?![A-Za-z])")
_ACTIVE = re.compile(r"(?<![A-Za-z0-9.])[Aa](\d+(?:\.\d+)?)[Bb](?![A-Za-z])")
_QUANT = re.compile(r"(?<![A-Za-z0-9])(IQ\d(?:_[A-Z0-9]+)*|TQ\d_\d|Q\d(?:_K)?(?:_[A-Z0-9]+)?|MXFP4|BF16|F16|F32)"
                    r"(?![A-Za-z0-9])", re.I)
_SHARD = re.compile(r"^(?P<stem>.+)-(?P<n>\d{5})-of-(?P<total>\d{5})\.gguf$", re.I)
_SKIP_FILES = re.compile(r"mmproj|imatrix|vocab", re.I)


def parse_params_b(name: str):
    """'Qwen3-Coder-30B-A3B-GGUF' -> 30.0 (billions of parameters in the name), or None."""
    m = _PARAMS.search(name)
    return float(m.group(1)) if m else None


def parse_active_b(name: str):
    """'Qwen3-Coder-30B-A3B-GGUF' -> 3.0 (a mixture-of-experts model's active parameters), or None."""
    m = _ACTIVE.search(name)
    return float(m.group(1)) if m else None


def quant_of(filename: str) -> str:
    """'dir/Model-UD-Q4_K_XL.gguf' -> 'Q4_K_XL'. Empty when the name carries no quantization."""
    found = _QUANT.findall(filename.rsplit("/", 1)[-1])
    return found[-1].upper() if found else ""


def quant_bits(quant: str) -> float:
    """Rough bits per weight: a quality ranking of quantizations (higher keeps more of the original)."""
    q = (quant or "").upper()
    if q == "F32":
        return 32.0
    if q in ("F16", "BF16"):
        return 16.0
    if q == "MXFP4":
        return 4.3
    m = re.match(r"(IQ|TQ|Q)(\d)", q)
    if not m:
        return 4.0
    d = int(m.group(2))
    if m.group(1) == "TQ":
        return 2.0
    if m.group(1) == "IQ":
        return d + 0.3
    return d + (0.9 if "_K" in q else 0.5)


# --- Files ---------------------------------------------------------------------------------------
def group_files(siblings, min_bytes: int = MIN_MODEL_BYTES) -> list:
    """Repo file list -> one entry per downloadable model file set:
    {name, quant, size, files: [(path, size), ...]} where files[0] is what llama.cpp is pointed at.
    Split files (-00001-of-00003.gguf) are summed; incomplete sets and projector/imatrix files are dropped."""
    groups, shards = [], {}
    for s in siblings or []:
        f = s.get("rfilename", "")
        if not f.lower().endswith(".gguf") or _SKIP_FILES.search(f):
            continue
        size = int(s.get("size") or 0)
        m = _SHARD.match(f)
        if m:
            g = shards.setdefault(m.group("stem"), {"total": int(m.group("total")), "parts": {}})
            g["parts"][int(m.group("n"))] = (f, size)
        else:
            groups.append({"name": f.rsplit("/", 1)[-1][:-5], "quant": quant_of(f), "size": size, "files": [(f, size)]})
    for stem, g in shards.items():
        if sorted(g["parts"]) != list(range(1, g["total"] + 1)):
            continue                                        # a shard is missing: unusable
        files = [g["parts"][i] for i in sorted(g["parts"])]
        groups.append({"name": stem.rsplit("/", 1)[-1], "quant": quant_of(stem), "size": sum(x[1] for x in files),
                       "files": files})
    return sorted((g for g in groups if g["size"] >= min_bytes), key=lambda g: g["size"])


# --- Memory and speed ---------------------------------------------------------------------------------
def kv_cache_mb(params_b: float, ctx: int, train_ctx: int = 0) -> int:
    """Rough size of the context cache (f16) in MB. The Hub does not list layer or head counts, so this is
    fitted to common models (about 125 KB per token at 8B, 330 KB at 70B). It is an estimate, not a guarantee."""
    if train_ctx:
        ctx = min(ctx, train_ctx)
    per_token = 40 * 1024 * max(params_b, 0.5) ** 0.55
    return int(ctx * per_token / MIB)


def budget_mb(hw) -> int:
    """The most memory any run mode on this machine could offer a model (used to skip hopeless repos early)."""
    b = hw.ram_mb * 60 // 100
    if hw.gpu_kind == "apple":
        b = max(b, hw.ram_mb * 65 // 100)
    if hw.gpu_kind in ("nvidia", "gpu") and hw.gpu_usable:
        b = max(b, hw.vram_mb * 90 // 100)
    return b


def plausibly_fits(repo_id: str, hw) -> bool:
    """False when the parameter count in the repo name rules the model out even at a 2-bit quantization."""
    p = parse_params_b(repo_id.split("/", 1)[-1])
    return not p or p * 0.25 * 1024 + OVERHEAD_MB <= budget_mb(hw)


def place(need_mb: int, hw):
    """Where would this run? -> (mode, gpu_share). mode: gpu | partial | cpu | tight | no.
    Same budgets as model_setup.fit(); 'partial' = does not fit the GPU but fits RAM, so layers are split."""
    gpu = hw.gpu_kind in ("nvidia", "gpu") and hw.gpu_usable
    if gpu and need_mb <= hw.vram_mb * 90 // 100:
        return "gpu", 1.0
    if hw.gpu_kind == "apple" and need_mb <= hw.ram_mb * 65 // 100:
        return "gpu", 1.0
    if need_mb <= hw.ram_mb * 60 // 100:
        share = hw.vram_mb * 0.90 / need_mb if gpu and hw.vram_mb else 0.0
        return ("partial", share) if share >= 0.15 else ("cpu", 0.0)
    if need_mb <= hw.ram_mb * 80 // 100:
        return "tight", 0.0
    return "no", 0.0


def speed(size_bytes: int, mode: str, share: float, tps_fn, moe_ratio: float = 1.0) -> int:
    """Estimated tokens/s. tps_fn(size_bytes, mode) is model_setup.est_tps. A split model is limited by its
    slow half, so the GPU and CPU times add up. A mixture-of-experts model only reads its active experts."""
    if mode == "partial":
        t = share / max(tps_fn(size_bytes, "gpu"), 1) + (1 - share) / max(tps_fn(size_bytes, "cpu"), 1)
        tps = 1 / t
    else:
        tps = tps_fn(size_bytes, mode)
    return int(tps * max(moe_ratio * 0.7, 1.0))


# --- One repo ------------------------------------------------------------------------------------------
def evaluate_repo(repo: str, detail, hw, tps_fn, ctx: int = DEFAULT_CTX, min_tps: int = 3,
                  min_bytes: int = MIN_MODEL_BYTES):
    """Hub model JSON (fetched with ?blobs=true) -> (result, reason).
    result is the best quantization that runs here (dict), or None, in which case reason says why:
    unreadable | gated | not-chat | no-gguf | too-big | too-slow."""
    if not isinstance(detail, dict):
        return None, "unreadable"
    if detail.get("gated") or detail.get("private") or detail.get("disabled"):
        return None, "gated"
    meta = detail.get("gguf") or {}
    arch = str(meta.get("architecture") or "")
    if arch in NOT_CHAT_ARCHS:
        return None, "not-chat"
    groups = group_files(detail.get("siblings"), min_bytes)
    if not groups:
        return None, "no-gguf"
    name = repo.split("/", 1)[-1]
    train_ctx = int(meta.get("context_length") or 0)
    total_b = float(meta.get("total") or 0) / 1e9 or parse_params_b(name)
    active_b = parse_active_b(name)
    moe = bool(active_b and total_b and active_b < total_b * 0.8)
    ratio = total_b / active_b if moe else 1.0

    fits, any_fit = [], False
    for g in groups:
        params = total_b or g["size"] * 8 / (quant_bits(g["quant"]) * 1e9)
        kv = kv_cache_mb(params, ctx, train_ctx)
        need = g["size"] // MIB + kv + OVERHEAD_MB
        mode, share = place(need, hw)
        if mode in ("no", "tight"):
            continue
        any_fit = True
        tps = speed(g["size"], mode, share, tps_fn, ratio)
        if tps >= min_tps:
            fits.append(dict(g, mode=mode, gpu_share=round(share, 2), tps=tps, need_mb=need, kv_mb=kv, params_b=params))
    if not fits:
        return None, "too-slow" if any_fit else "too-big"
    # Highest quality that still runs well; beyond 8-bit extra size buys nothing, so the smaller file wins.
    best = max(fits, key=lambda r: (min(quant_bits(r["quant"]), 8.5), -r["size"]))
    return {
        "repo": repo, "file": best["files"][0][0], "files": best["files"], "name": best["name"],
        "quant": best["quant"], "bits": round(quant_bits(best["quant"]), 1), "size": best["size"],
        "mode": best["mode"], "gpu_share": best["gpu_share"], "tps": best["tps"], "need_mb": best["need_mb"],
        "kv_mb": best["kv_mb"], "ctx": min(ctx, train_ctx) if train_ctx else ctx, "arch": arch,
        "compat": "ok" if arch in KNOWN_ARCHS else "unverified", "params_b": round(best["params_b"], 1),
        "moe": moe, "low_quality": quant_bits(best["quant"]) < 3, "other_quants": len(fits) - 1,
        "downloads": int(detail.get("downloads") or 0), "likes": int(detail.get("likes") or 0),
        "updated": (detail.get("lastModified") or "")[:10],
    }, ""


# --- Candidate lists and ranking ------------------------------------------------------------------------
HUB_SORTS = {"downloads": "downloads", "trending": "trendingScore", "recent": "createdAt"}


def list_urls(api: str, hub: str = "downloads", search: str = "", authors=(), default_authors=(), limit: int = 60) -> list:
    """Hub list queries to run: one per named author, else one global query plus one per default author."""
    base = (f"{api}/models?filter=gguf&pipeline_tag=text-generation&sort={HUB_SORTS.get(hub, 'downloads')}"
            f"&direction=-1&limit={limit}")
    if search:
        base += "&search=" + quote(search)
    names = list(authors) or [None] + list(default_authors)
    return [base + (f"&author={quote(a)}" if a else "") for a in names]


def parse_list(data) -> list:
    """Hub list JSON -> [{id, downloads, likes}] for public repos."""
    out = []
    for m in data if isinstance(data, list) else []:
        if isinstance(m, dict) and m.get("id") and not m.get("private"):
            out.append({"id": m["id"], "downloads": int(m.get("downloads") or 0), "likes": int(m.get("likes") or 0)})
    return out


def popularity(row: dict) -> int:
    return row["downloads"] + row["likes"] * 20


def rank(results: list, sort: str = "popular") -> list:
    """Usable models (>= 5 t/s) first, then by popularity, size (bigger = more capable) or speed."""
    keys = {"size": lambda r: (r["tps"] >= USABLE_TPS, r["size"]),
            "speed": lambda r: (r["tps"], r["size"])}
    key = keys.get(sort, lambda r: (r["tps"] >= USABLE_TPS, popularity(r)))
    return sorted(results, key=key, reverse=True)
