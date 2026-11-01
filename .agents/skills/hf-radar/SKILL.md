---
name: hf-radar
description: >-
  Use this skill to fetch, score, and monitor fresh GGUF models directly from Hugging Face,
  evaluate hardware fit against local system RAM/GPU, and inspect historical trend snapshots.
license: MIT
compatibility: Python 3.9+ (Windows, macOS, Linux)
metadata:
  standard: agentskills.io
---

# Hugging Face Model Radar & History Skill

This skill allows agents and users to discover the latest GGUF models on Hugging Face, track release trends, and verify which models fit the local machine's memory budget.

---

## Capabilities

1. **Live Hugging Face Scanning**:
   - Queries `trendingScore`, `createdAt`, and `downloads` for `pipeline_tag=text-generation&filter=gguf`.
   - Filters out non-LLM weights (vision, embedding, speech) and draft heads.
2. **Hardware Suitability & Speed Profiling**:
   - Scores candidates against detected hardware (Apple Silicon unified memory or NVIDIA VRAM).
   - Computes KV cache requirements at context lengths (default 4096 tokens).
   - Classifies fit into `GPU`, `CPU`, or `Tight` and estimates memory-bandwidth tokens/sec.
3. **Historical Snapshots & Time-Series Archive**:
   - Archives raw daily snapshots in `data/hf_history/snapshots/YYYY-MM-DD.json`.
   - Appends all observed models to `data/hf_history/history.jsonl` for historical velocity tracking.
4. **Visual & CLI Dashboards**:
   - Terminal summary table via `utils/hf_radar.py`.
   - Localhost interactive dashboard via setup UI (`/api/radar`).

---

## Common Workflows

### 1. Launch Interactive Model Radar GUI (Default)
Running `hf_radar.py` automatically synchronizes fresh Hugging Face models and launches the modern Web UI dashboard in your browser:
```bash
python utils/hf_radar.py
```
Or explicitly with `--ui`:
```bash
python utils/hf_radar.py --ui --port 8765
```

### 2. Synchronize Latest Models from Hugging Face (Headless)
Fetch fresh models, score them against local hardware, and archive the snapshot:
```bash
python utils/hf_radar.py --sync --cli
```

### 3. View Terminal Radar Leaderboard
View top models fitting local hardware without launching the browser:
```bash
python utils/hf_radar.py --dashboard --cli
```

Filter strictly for models running 100% on GPU:
```bash
python utils/hf_radar.py --dashboard --gpu-only --cli
```

Filter by keyword (e.g. coder, ternary, bonsai):
```bash
python utils/hf_radar.py --dashboard --search bonsai --cli
```

### 4. Output Structured JSON
For scripts and automated agent analysis:
```bash
python utils/hf_radar.py --json
```

### 5. Access via Launchpad Setup UI
You can also launch the general setup server:
```bash
python utils/model_setup.py --ui
```
And click **"Model Radar"** in the top navigation bar.

