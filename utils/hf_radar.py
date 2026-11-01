"""Hugging Face Model Radar and Historical Tracker.
Standard library only. Fetches trending and new GGUF models from Hugging Face,
evaluates hardware fit against local machine, and archives historical snapshots.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import hardware
import hf_discover
import model_setup
import ui_server

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HISTORY_DIR = ROOT / "data" / "hf_history"
USER_AGENT = "llama-cpp-launchpad/1.0 (https://github.com/kunalsuri/llama-cpp-launchpad)"
HF_API = "https://huggingface.co/api/models"

CLUSTER_KEYWORDS = {
    "coding": (
        "coder", "code", "-dev", "coding", "starcoder", "codellama",
        "deepseek-coder", "programming", "sql", "python", "dev-",
    ),
    "agentic": (
        "agent", "agentic", "tool", "function-call", "function_call",
        "function-calling", "command-r", "hermes", "react", "tooluse",
        "tool-use", "action", "workflow", "browse",
    ),
    "reasoning": (
        "reasoning", "reasoner", "-r1", "deepseek-r1", "-cot",
        "chain-of-thought", "math", "qwq", "olympiad", "logic", "proof",
    ),
    "creative": (
        "creative", "story", "roleplay", "rp", "uncensored",
        "abliterated", "heretic", "fiction", "novel", "writing",
    ),
    "chat": (
        "instruct", "chat", "dialog", "conversation", "assistant",
        "alpaca", "vicuna", "talk",
    ),
}

CLUSTER_LABELS = {
    "coding": "Coding",
    "agentic": "Agentic Work",
    "chat": "Chat & Instruct",
    "reasoning": "Reasoning & Math",
    "creative": "Roleplay & Creative",
}


def classify_clusters(repo_meta: dict, name: str = "") -> list[str]:
    """Classify model into functional clusters (coding, agentic, chat, reasoning, creative)."""
    text_parts = [
        repo_meta.get("id") or repo_meta.get("modelId") or repo_meta.get("repo") or "",
        name or repo_meta.get("name") or "",
        repo_meta.get("description") or "",
    ]
    tags = repo_meta.get("tags")
    if isinstance(tags, list):
        text_parts.extend(str(t) for t in tags)
    blob = " ".join(text_parts).lower()

    clusters = []
    for c_id, keywords in CLUSTER_KEYWORDS.items():
        if c_id == "chat":
            continue
        if any(k in blob for k in keywords):
            clusters.append(c_id)

    if any(k in blob for k in CLUSTER_KEYWORDS["chat"]) or not clusters:
        clusters.append("chat")

    return clusters


def history_dir() -> Path:
    override = os.environ.get("LP_RADAR_DIR")
    p = Path(override) if override else DEFAULT_HISTORY_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def http_json(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def tps_fn_for(hw: hardware.Hw):
    def _fn(size_bytes: int, mode: str) -> int:
        size_mb = max(size_bytes // 1048576, 1)
        bw10 = {"gpu": 1000 if hw.gpu_kind == "apple" else 2500, "cpu": 150, "tight": 50}.get(mode, 150)
        return max(bw10 * 102 // size_mb, 1)
    return _fn


def fetch_hf_repos(sort: str = "trendingScore", limit: int = 40, search: str | None = None) -> list:
    """Fetch repo metadata list from Hugging Face API."""
    params = [
        "filter=gguf",
        "pipeline_tag=text-generation",
        f"sort={sort}",
        f"limit={limit}",
    ]
    if sort == "createdAt":
        params.append("direction=-1")
    if search:
        params.append(f"search={urllib.parse.quote(search)}")
    url = f"{HF_API}?{'&'.join(params)}"
    data = http_json(url)
    return data if isinstance(data, list) else []


def fetch_repo_details(repo_id: str) -> dict | None:
    """Fetch siblings and tags for a specific model repo."""
    url = f"{HF_API}/{urllib.parse.quote(repo_id)}?blobs=true"
    data = http_json(url)
    return data if isinstance(data, dict) else None


def evaluate_repo(repo_meta: dict, siblings: list, hw: hardware.Hw, ctx: int = 4096) -> dict | None:
    """Evaluate a repo against hardware specs using pure-logic hf_discover."""
    repo_id = repo_meta.get("id") or repo_meta.get("modelId")
    if not repo_id:
        return None
    detail = dict(repo_meta, siblings=siblings)
    ev, reason = hf_discover.evaluate_repo(repo_id, detail, hw, tps_fn_for(hw), ctx=ctx)
    if not ev:
        return None
    f = ev.get("file") or (ev.get("files")[0][0] if ev.get("files") else f"{ev['name']}.gguf")
    files = ev.get("files") or [(f, ev["size"])]
    dl_url = f"https://huggingface.co/{repo_id}/resolve/main/{f}"
    return {
        "repo": repo_id,
        "name": ev["name"],
        "file": f,
        "files": files,
        "download_url": dl_url,
        "quant": ev["quant"],
        "size_bytes": ev["size"],
        "size_mb": round(ev["size"] / 1048576, 1),
        "arch": ev.get("arch", "unknown"),
        "params_b": round(ev.get("params_b") or 0.0, 1),
        "moe": ev.get("moe", False),
        "fit_mode": ev["mode"],
        "tps": ev["tps"],
        "clusters": classify_clusters(repo_meta, ev["name"]),
        "downloads": int(repo_meta.get("downloads") or 0),
        "likes": int(repo_meta.get("likes") or 0),
        "created_at": (repo_meta.get("createdAt") or "")[:10],
        "compat": ev.get("compat", "ok"),
        "other_quants": ev.get("other_quants", 0),
    }


def _normalize_model_entry(m: dict) -> dict:
    """Ensure cached or minimal model dictionary has file, files, download_url, clusters."""
    repo = m.get("repo", "")
    name = m.get("name") or repo.split("/")[-1] or "model"
    size = int(m.get("size_bytes") or m.get("size") or 0)
    if "clusters" not in m:
        m["clusters"] = classify_clusters(m, name)
    if "file" not in m:
        if m.get("files") and isinstance(m["files"], list) and len(m["files"]) > 0:
            m["file"] = m["files"][0][0]
        else:
            m["file"] = f"{name}.gguf"
    if "files" not in m:
        m["files"] = [(m["file"], size)]
    if "download_url" not in m and repo and m["file"]:
        m["download_url"] = f"https://huggingface.co/{repo}/resolve/main/{m['file']}"
    return m


def record_history(models: list, hdir: Path | None = None) -> None:
    """Append current evaluated models to history.jsonl and write latest.json."""
    h = hdir or history_dir()
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    today_str = now_iso[:10]

    latest_file = h / "latest.json"
    prev_file = h / "previous.json"
    if latest_file.is_file():
        try:
            curr_data = json.loads(latest_file.read_text(encoding="utf-8"))
            if curr_data and curr_data.get("updated_at") != now_iso:
                prev_file.write_text(json.dumps(curr_data, indent=2), encoding="utf-8")
        except Exception:
            pass

    snap_dir = h / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_file = snap_dir / f"{today_str}.json"
    snap_file.write_text(json.dumps({"updated_at": now_iso, "models": models}, indent=2), encoding="utf-8")

    latest_file.write_text(json.dumps({"updated_at": now_iso, "models": models}, indent=2), encoding="utf-8")

    history_file = h / "history.jsonl"
    with history_file.open("a", encoding="utf-8") as f:
        for m in models:
            entry = dict(m, synced_at=now_iso)
            f.write(json.dumps(entry, sort_keys=True) + "\n")


def load_latest(hdir: Path | None = None) -> dict | None:
    """Load latest radar scan if available."""
    h = hdir or history_dir()
    f = h / "latest.json"
    if f.is_file():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data and data.get("models"):
                for m in data["models"]:
                    _normalize_model_entry(m)
                return data
        except Exception:
            pass
    snap_dir = h / "snapshots"
    if snap_dir.is_dir():
        for s in sorted(snap_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(s.read_text(encoding="utf-8"))
                if data and data.get("models"):
                    for m in data["models"]:
                        _normalize_model_entry(m)
                    return data
            except Exception:
                continue
    return None


def list_snapshots(hdir: Path | None = None) -> list[dict]:
    """List all available snapshots with date, count, and timestamp."""
    h = hdir or history_dir()
    snap_dir = h / "snapshots"
    results = []
    if snap_dir.is_dir():
        for p in sorted(snap_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                models = data.get("models") or []
                results.append({
                    "date": p.stem,
                    "count": len(models),
                    "updated_at": data.get("updated_at", ""),
                })
            except Exception:
                continue
    return results


def compute_sync_diff(hdir: Path | None = None, base_snap: str | None = None) -> dict:
    """Compute difference between current radar scan and previous sync (or specific base snapshot)."""
    h = hdir or history_dir()
    latest_data = load_latest(h) or {"updated_at": "", "models": []}
    curr_models = latest_data.get("models") or []
    curr_updated = latest_data.get("updated_at") or ""

    for m in curr_models:
        _normalize_model_entry(m)

    curr_by_repo = {m["repo"]: m for m in curr_models if m.get("repo")}

    prev_data = None
    snap_dir = h / "snapshots"
    if base_snap and snap_dir.is_dir():
        cand_name = base_snap if base_snap.endswith(".json") else f"{base_snap}.json"
        cand = snap_dir / cand_name
        if cand.is_file():
            try:
                prev_data = json.loads(cand.read_text(encoding="utf-8"))
            except Exception:
                pass

    if not prev_data:
        prev_file = h / "previous.json"
        if prev_file.is_file():
            try:
                cand = json.loads(prev_file.read_text(encoding="utf-8"))
                if cand and cand.get("updated_at") != curr_updated and cand.get("models"):
                    prev_data = cand
            except Exception:
                pass

    if not prev_data and snap_dir.is_dir():
        snaps = sorted(snap_dir.glob("*.json"), reverse=True)
        for s in snaps:
            try:
                cand = json.loads(s.read_text(encoding="utf-8"))
                if cand and cand.get("updated_at") != curr_updated and cand.get("models"):
                    prev_data = cand
                    break
            except Exception:
                continue

    prev_models = (prev_data.get("models") or []) if prev_data else []
    for m in prev_models:
        _normalize_model_entry(m)
    prev_by_repo = {m["repo"]: m for m in prev_models if m.get("repo")}
    prev_updated = prev_data.get("updated_at", "") if prev_data else ""

    new_repos = [r for r in curr_by_repo if r not in prev_by_repo]
    removed_repos = [r for r in prev_by_repo if r not in curr_by_repo]
    common_repos = [r for r in curr_by_repo if r in prev_by_repo]

    new_models = [curr_by_repo[r] for r in new_repos]
    removed_models = [prev_by_repo[r] for r in removed_repos]

    movers = []
    for r in common_repos:
        c = curr_by_repo[r]
        p = prev_by_repo[r]
        dl_diff = int(c.get("downloads", 0)) - int(p.get("downloads", 0))
        likes_diff = int(c.get("likes", 0)) - int(p.get("likes", 0))
        entry = dict(c)
        entry["delta_downloads"] = dl_diff
        entry["delta_likes"] = likes_diff
        entry["prev_downloads"] = int(p.get("downloads", 0))
        entry["prev_likes"] = int(p.get("likes", 0))
        movers.append(entry)

    movers.sort(key=lambda m: (m.get("delta_downloads", 0), m.get("delta_likes", 0)), reverse=True)
    gpu_ready_new = sum(1 for m in new_models if m.get("fit_mode") == "gpu")
    snapshots = list_snapshots(h)

    return {
        "has_previous": prev_data is not None,
        "latest_sync": curr_updated,
        "previous_sync": prev_updated,
        "summary": {
            "new_count": len(new_models),
            "removed_count": len(removed_models),
            "persisted_count": len(common_repos),
            "gpu_ready_new": gpu_ready_new,
            "total_current": len(curr_models),
            "total_previous": len(prev_models),
        },
        "new_models": new_models,
        "top_movers": movers[:10],
        "all_movers": movers,
        "removed_models": removed_models,
        "snapshots": snapshots,
    }


def load_history_entries(hdir: Path | None = None, days: int = 30) -> list:
    """Load and parse historical entries from history.jsonl."""
    h = hdir or history_dir()
    f = h / "history.jsonl"
    if not f.is_file():
        return []
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    entries = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if row.get("synced_at", "") >= cutoff:
                entries.append(row)
        except Exception:
            continue
    return entries


def sync_radar(hw: hardware.Hw | None = None, hdir: Path | None = None,
               max_repos: int = 30, search: str | None = None) -> dict:
    """Synchronize with Hugging Face, score against hardware, and save history."""
    target_hw = hw or hardware.detect_hw()
    seen_ids = set()
    repos_to_check = []

    sources = [("trendingScore", 30), ("createdAt", 30), ("downloads", 20)]
    for sort_key, limit in sources:
        for r in fetch_hf_repos(sort=sort_key, limit=limit, search=search):
            rid = r.get("id") or r.get("modelId")
            if rid and rid not in seen_ids:
                seen_ids.add(rid)
                repos_to_check.append(r)
            if len(repos_to_check) >= max_repos:
                break
        if len(repos_to_check) >= max_repos:
            break

    evaluated = []
    for r in repos_to_check:
        rid = r.get("id") or r.get("modelId")
        siblings = r.get("siblings")
        if siblings is None:
            detail = fetch_repo_details(rid)
            siblings = detail.get("siblings") if detail else []
        ev = evaluate_repo(r, siblings, target_hw)
        if ev:
            evaluated.append(ev)

    evaluated.sort(key=lambda m: (m["downloads"] + m["likes"] * 20), reverse=True)
    offline = not repos_to_check                # no listing came back at all: the Hub was not reached
    if evaluated:
        record_history(evaluated, hdir)
    else:
        cached = load_latest(hdir)
        if cached and cached.get("models"):
            return dict(cached, offline=offline)
    return {
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total_scanned": len(repos_to_check),
        "total_compatible": len(evaluated),
        "models": evaluated,
        "offline": offline,
    }


def render_dashboard(data: dict, gpu_only: bool = False, cluster: str = "all", limit: int = 15) -> str:
    """Render terminal ASCII dashboard."""
    models = data.get("models") or []
    if gpu_only:
        models = [m for m in models if m.get("fit_mode") == "gpu"]
    if cluster and cluster != "all":
        models = [m for m in models if cluster in m.get("clusters", [])]
    models = models[:limit]

    lines = []
    lines.append("=" * 80)
    lines.append("  HUGGING FACE LOCAL MODEL RADAR & HISTORICAL DASHBOARD")
    lines.append(f"  Last Updated: {data.get('updated_at', 'unknown')} | Models: {len(models)}")
    lines.append("=" * 80)
    lines.append(
        f"{'#':<3} {'Model Repository':<34} {'Quant':<8} {'Size':<8} "
        f"{'Mode':<5} {'Speed':<8} {'Clusters':<10}"
    )
    lines.append("-" * 80)

    for idx, m in enumerate(models, 1):
        repo = m["repo"]
        if len(repo) > 32:
            repo = repo[:29] + "..."
        mode = m.get("fit_mode", "cpu").upper()
        tps = f"~{m.get('tps', 0)} t/s"
        sz = f"{m.get('size_mb', 0) / 1024:.1f} GB"
        quant = m.get("quant") or "?"
        clusters = ",".join(m.get("clusters", [])[:2]).upper()
        lines.append(f"{idx:<3} {repo:<34} {quant:<8} {sz:<8} {mode:<5} {tps:<8} {clusters:<10}")

    lines.append("=" * 80)
    return "\n".join(lines)


def render_history_diff(diff: dict) -> str:
    """Render terminal ASCII diff of changes since last sync."""
    lines = []
    lines.append("=" * 80)
    lines.append("  HUGGING FACE MODEL RADAR: WHAT CHANGED SINCE LAST SYNC")
    lines.append("=" * 80)
    latest_ts = diff.get("latest_sync") or "unknown"
    prev_ts = diff.get("previous_sync") or "no previous sync recorded"
    sm = diff.get("summary") or {}
    lines.append(f"  Current Scan:   {latest_ts}")
    lines.append(f"  Previous Sync:  {prev_ts}")
    lines.append(
        f"  Summary:        +{sm.get('new_count', 0)} new models | "
        f"-{sm.get('removed_count', 0)} departures | "
        f"{sm.get('persisted_count', 0)} tracked | "
        f"{sm.get('gpu_ready_new', 0)} full GPU"
    )
    lines.append("=" * 80)

    new_models = diff.get("new_models") or []
    if new_models:
        lines.append(f"  NEW ARRIVALS ON THE FRONTIER (+{len(new_models)}):")
        lines.append(f"  {'#':<3} {'Repository':<36} {'Quant':<8} {'Speed':<8} {'Clusters':<16}")
        lines.append("  " + "-" * 74)
        for idx, m in enumerate(new_models[:10], 1):
            repo = m["repo"]
            if len(repo) > 34:
                repo = repo[:31] + "..."
            tps = f"~{m.get('tps', 0)} t/s"
            quant = m.get("quant") or "?"
            clust = ",".join(m.get("clusters") or ["chat"])[:16].upper()
            lines.append(f"  {idx:<3} {repo:<36} {quant:<8} {tps:<8} {clust:<16}")
        if len(new_models) > 10:
            lines.append(f"  ... and {len(new_models) - 10} more new models")
        lines.append("")

    movers = diff.get("top_movers") or []
    if movers:
        lines.append("  TOP VELOCITY MOVERS:")
        lines.append(f"  {'#':<3} {'Repository':<36} {'Downloads':<12} {'Growth':<12} {'Speed':<8}")
        lines.append("  " + "-" * 74)
        for idx, m in enumerate(movers[:8], 1):
            repo = m["repo"]
            if len(repo) > 34:
                repo = repo[:31] + "..."
            dl = f"{m.get('downloads', 0):,}"
            gain = m.get("delta_downloads", 0)
            delta_dl = f"+{gain:,}" if gain >= 0 else f"{gain:,}"
            tps = f"~{m.get('tps', 0)} t/s"
            lines.append(f"  {idx:<3} {repo:<36} {dl:<12} {delta_dl:<12} {tps:<8}")
        lines.append("")

    removed = diff.get("removed_models") or []
    if removed:
        lines.append(f"  COOLED OFF / RETIRED FROM RADAR (-{len(removed)}):")
        for m in removed[:6]:
            lines.append(f"  - {m.get('repo')} ({m.get('quant', '?')})")
        if len(removed) > 6:
            lines.append(f"  ... and {len(removed) - 6} more")
        lines.append("")

    lines.append("=" * 80)
    return "\n".join(lines)


def download_model_cli(repo_or_url: str, custom_file: str | None = None) -> int:
    """Download a model directly from terminal with progress, updating .launchpad-state."""
    raw = repo_or_url.strip().rstrip("/")
    if "huggingface.co/" in raw:
        after = raw.split("huggingface.co/", 1)[-1]
        parts = after.split("/")
        if len(parts) >= 2:
            repo = f"{parts[0]}/{parts[1]}"
            if "/resolve/" in raw and raw.endswith(".gguf"):
                custom_file = parts[-1]
        else:
            repo = after
    else:
        repo = raw

    hw = hardware.detect_hw()
    cached = load_latest()
    match = None
    if cached:
        for m in cached.get("models") or []:
            if m.get("repo", "").lower() == repo.lower():
                match = dict(m)
                break

    if not match:
        print(f"Fetching repository details from Hugging Face for {repo}...")
        try:
            info_url = f"{HF_API}/models/{repo}?blobs=true"
            meta = model_setup.http_json(info_url)
            sibs = meta.get("siblings") or []
            match = evaluate_repo(meta, sibs, hw)
        except Exception as e:
            print(f"Error fetching metadata for {repo}: {e}")
            match = None

    if not match:
        print(f"Could not find or evaluate a compatible GGUF for {repo}.")
        print("Verify repository name or check if the repository is private or gated.")
        return 1

    _normalize_model_entry(match)
    fname = custom_file or match["file"]
    size = match["size_bytes"]
    files = match["files"] if not custom_file else [(custom_file, size)]
    dl_url = f"https://huggingface.co/{repo}/resolve/main/{fname}"
    # Running this again continues the partial .part file; a curl command would start a different file from zero.
    radar_launcher = "scripts\\win\\radar.bat" if sys.platform == "win32" else "./scripts/unix/radar.sh"
    resume_cmd = f'{radar_launcher} --download "{repo}"' + (f' --file "{custom_file}"' if custom_file else "")

    print("=" * 80)
    print("  LLAMA-CPP LAUNCHPAD - TERMINAL DOWNLOAD")
    print("=" * 80)
    print(f"  Repository:      {repo}")
    print(f"  Target File:     {fname}")
    print(f"  Size:            {model_setup.human_size(size)}")
    print(f"  Quantization:    {match.get('quant', 'Unknown')}")
    print(f"  Execution Mode:  {match.get('fit_mode', 'cpu').upper()} (~{match.get('tps', 0)} tok/s)")
    print(f"  Direct Link:     {dl_url}")
    print(f"  Resume Command:  {resume_cmd}")
    print("=" * 80)
    print("Starting download into models/ (live progress synchronized with setup UI)...")

    model_setup.state_update({
        "dl_active": "1",
        "dl_state": "downloading",
        "dl_title": match.get("name") or repo,
        "dl_repo": repo,
        "dl_file": fname,
        "dl_done": 0,
        "dl_total": size,
    })

    base = 0
    paths = []
    for f, part_size in files:
        dest, have = model_setup.local_path(repo, f, part_size)
        if have:
            paths.append(dest)
            base += part_size
            continue

        def on_chunk(done, b=base):
            cur = b + done
            model_setup.state_update({"dl_done": cur})

        path = model_setup.download(repo, f, part_size, on_chunk)
        if not path:
            model_setup.state_update({"dl_active": "0", "dl_state": "error"})
            print("\nDownload failed or interrupted. What was downloaded is kept.")
            print("To continue where it stopped, run:")
            print(f"  {resume_cmd}")
            return 1
        base += part_size
        paths.append(path)

    model_setup.record_installed(match.get("name") or repo.split("/")[-1], repo, size)
    model_setup.state_update({
        "dl_active": "0",
        "dl_state": "testing",
        "dl_done": size,
        "dl_total": size,
    })
    print("\nDownload complete! Benchmarking speed with llama-bench...")
    rc = model_setup.check_model_speed(paths[0], size, hw)
    tps = model_setup.state_int("measured_tps") if rc == 0 else 0
    model_setup.state_update({"dl_state": "done"})
    print(f"Speed test result: ~{tps} tokens/s")
    srv = "scripts\\win\\serve.bat" if sys.platform == "win32" else "./scripts/unix/serve.sh"
    print(f"Launch your server now with:\n  {srv}")
    return 0


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hf-radar",
        description="Hugging Face Model Radar & History",
    )
    parser.add_argument("--sync", action="store_true", help="sync latest models from Hugging Face")
    parser.add_argument("--dashboard", action="store_true", help="show terminal radar dashboard")
    parser.add_argument("--cli", action="store_true", help="CLI mode only (do not launch Web UI)")
    parser.add_argument("--ui", action="store_true", help="launch local web dashboard in browser")
    parser.add_argument("--port", type=int, default=8765, help="port for local web dashboard")
    parser.add_argument("--no-browser", action="store_true", help="start web server without opening browser")
    parser.add_argument("--gpu-only", action="store_true", help="filter models running fully on GPU")
    parser.add_argument(
        "--download",
        type=str,
        metavar="REPO",
        help="download a model by repo ID or URL with live progress",
    )
    parser.add_argument(
        "--file",
        type=str,
        metavar="FNAME",
        help="specific GGUF file to download if repo has multiple",
    )
    parser.add_argument(
        "--cluster",
        type=str,
        choices=["all", "coding", "agentic", "chat", "reasoning", "creative"],
        default="all",
        help="filter models by cluster (coding, agentic, chat, reasoning, creative)",
    )
    parser.add_argument(
        "--history",
        "--diff",
        action="store_true",
        dest="history",
        help="show what changed since the last sync",
    )
    parser.add_argument("--base", type=str, help="base snapshot date to compare against for history (YYYY-MM-DD)")
    parser.add_argument("--search", type=str, help="filter by keyword (e.g. coder, bonsai)")
    parser.add_argument("--json", action="store_true", help="output JSON")
    parser.add_argument("--limit", type=int, default=15, help="number of models to display in terminal")
    args = parser.parse_args(argv)

    hw = hardware.detect_hw()

    if args.download:
        return download_model_cli(args.download, custom_file=args.file)

    if args.history:
        diff_data = compute_sync_diff(base_snap=args.base)
        if args.json:
            print(json.dumps(diff_data, indent=2))
            return 0
        if args.cli or not args.ui:
            print(render_history_diff(diff_data))
            if not args.ui:
                return 0
        return ui_server.serve(
            model_setup,
            port=args.port,
            open_browser=not args.no_browser,
            initial_hash="#history",
        )

    if args.sync:
        print(f"Syncing fresh Hugging Face models for {hw.gpu_name} ({hw.ram_mb // 1024} GB RAM)...")
        data = sync_radar(hw, search=args.search)
    else:
        data = load_latest()
        if not data:
            print("No cached radar data found. Performing initial sync from Hugging Face...")
            data = sync_radar(hw, search=args.search)

    if args.json:
        print(json.dumps(data, indent=2))
        return 0

    if args.cli or args.dashboard:
        print(render_dashboard(data, gpu_only=args.gpu_only, cluster=args.cluster, limit=args.limit))
        if not args.ui:
            return 0

    if args.ui or (not args.cli and not (args.sync and not args.ui)):
        print("Launching interactive Hugging Face Model Radar Web UI...")
        return ui_server.serve(
            model_setup,
            port=args.port,
            open_browser=not args.no_browser,
            initial_hash="#radar",
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
