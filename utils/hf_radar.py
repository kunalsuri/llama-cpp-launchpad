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
    return {
        "repo": repo_id,
        "name": ev["name"],
        "quant": ev["quant"],
        "size_bytes": ev["size"],
        "size_mb": round(ev["size"] / 1048576, 1),
        "arch": ev.get("arch", "unknown"),
        "params_b": round(ev.get("params_b") or 0.0, 1),
        "moe": ev.get("moe", False),
        "fit_mode": ev["mode"],
        "tps": ev["tps"],
        "downloads": int(repo_meta.get("downloads") or 0),
        "likes": int(repo_meta.get("likes") or 0),
        "created_at": (repo_meta.get("createdAt") or "")[:10],
        "compat": ev.get("compat", "ok"),
        "other_quants": ev.get("other_quants", 0),
    }


def record_history(models: list, hdir: Path | None = None) -> None:
    """Append current evaluated models to history.jsonl and write latest.json."""
    h = hdir or history_dir()
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    today_str = now_iso[:10]

    snap_dir = h / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_file = snap_dir / f"{today_str}.json"
    snap_file.write_text(json.dumps({"updated_at": now_iso, "models": models}, indent=2), encoding="utf-8")

    latest_file = h / "latest.json"
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
                return data
        except Exception:
            pass
    snap_dir = h / "snapshots"
    if snap_dir.is_dir():
        for s in sorted(snap_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(s.read_text(encoding="utf-8"))
                if data and data.get("models"):
                    return data
            except Exception:
                continue
    return None


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
    if evaluated:
        record_history(evaluated, hdir)
    else:
        cached = load_latest(hdir)
        if cached and cached.get("models"):
            return cached
    return {
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total_scanned": len(repos_to_check),
        "total_compatible": len(evaluated),
        "models": evaluated,
    }


def render_dashboard(data: dict, gpu_only: bool = False, limit: int = 15) -> str:
    """Render terminal ASCII dashboard."""
    models = data.get("models") or []
    if gpu_only:
        models = [m for m in models if m.get("fit_mode") == "gpu"]
    models = models[:limit]

    lines = []
    lines.append("=" * 80)
    lines.append("  HUGGING FACE LOCAL MODEL RADAR & HISTORICAL DASHBOARD")
    lines.append(f"  Last Updated: {data.get('updated_at', 'unknown')} | Models: {len(models)}")
    lines.append("=" * 80)
    lines.append(f"{'#':<3} {'Model Repository':<38} {'Quant':<8} {'Size':<8} {'Mode':<6} {'Speed':<9} {'Downloads':<10}")
    lines.append("-" * 80)

    for idx, m in enumerate(models, 1):
        repo = m["repo"]
        if len(repo) > 36:
            repo = repo[:33] + "..."
        mode = m.get("fit_mode", "cpu").upper()
        tps = f"~{m.get('tps', 0)} t/s"
        dl = f"{m.get('downloads', 0):,}"
        sz = f"{m.get('size_mb', 0) / 1024:.1f} GB"
        quant = m.get("quant") or "?"
        lines.append(f"{idx:<3} {repo:<38} {quant:<8} {sz:<8} {mode:<6} {tps:<9} {dl:<10}")

    lines.append("=" * 80)
    return "\n".join(lines)


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
    parser.add_argument("--search", type=str, help="filter by keyword (e.g. coder, bonsai)")
    parser.add_argument("--json", action="store_true", help="output JSON")
    parser.add_argument("--limit", type=int, default=15, help="number of models to display in terminal")
    args = parser.parse_args(argv)

    hw = hardware.detect_hw()
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
        print(render_dashboard(data, gpu_only=args.gpu_only, limit=args.limit))
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
