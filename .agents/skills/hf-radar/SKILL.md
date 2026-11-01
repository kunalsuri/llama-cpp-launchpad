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
2. **Workload Cluster Classification**:
   - Classifies models into functional domains: **Coding** (`coding`), **Agentic Work** (`agentic`), **Chat & Instruct** (`chat`), **Reasoning & Math** (`reasoning`), and **Creative & Roleplay** (`creative`).
   - Supports multi-label assignment and interactive UI/CLI filtering by cluster.
3. **Hardware Suitability & Speed Profiling**:
   - Scores candidates against detected hardware (Apple Silicon unified memory or NVIDIA VRAM).
   - Computes KV cache requirements at context lengths (default 4096 tokens).
   - Classifies fit into `GPU`, `CPU`, or `Tight` and estimates memory-bandwidth tokens/sec.
4. **Historical Snapshots & "What Changed" Diff**:
   - Archives raw daily snapshots in `data/hf_history/snapshots/YYYY-MM-DD.json`.
   - Appends all observed models to `data/hf_history/history.jsonl` for historical velocity tracking.
   - Computes diffs between syncs to surface fresh frontier arrivals, download surges, and retired weights.
5. **Visual & CLI Dashboards**:
   - Terminal summary table and diff report via `utils/hf_radar.py`.
   - Localhost interactive dashboard via setup UI (`/api/radar` and `/api/radar/history`).

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

### 2. Inspect What Changed Since Last Sync
View fresh arrivals, velocity movers, and cooled-off models in the terminal:
```bash
python utils/hf_radar.py --history --cli
```
Or launch directly into the Web UI Sync History page:
```bash
python utils/hf_radar.py --history
```
Or compare against a specific baseline snapshot date:
```bash
python utils/hf_radar.py --history --base 2026-10-31 --cli
```

### 3. Filter by Workload Clusters (Coding, Agentic, Chat, Reasoning)
Filter models by functional cluster in terminal:
```bash
# Coding models
python utils/hf_radar.py --dashboard --cluster coding --cli

# Agentic / tool-calling models
python utils/hf_radar.py --dashboard --cluster agentic --cli

# Reasoning & Math models
python utils/hf_radar.py --dashboard --cluster reasoning --cli
```

### 4. Synchronize Latest Models from Hugging Face (Headless)
Fetch fresh models, score them against local hardware, and archive the snapshot:
```bash
python utils/hf_radar.py --sync --cli
```

### 5. View Terminal Radar Leaderboard
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

### 6. Terminal Download & Dual-View Monitoring
Download any evaluated model with live progress in terminal and automatic progress sync to the Web UI:
```bash
# Download by repository name
python utils/hf_radar.py --download unsloth/DeepSeek-R1-Distill-Qwen-7B-GGUF

# Download a specific GGUF file from a repository
python utils/hf_radar.py --download Qwen/Qwen2.5-Coder-7B-Instruct-GGUF --file qwen2.5-coder-7b-instruct-q4_k_m.gguf
```

### 7. Resumable curl Downloads
Every model in the Web UI (radar cards, technical specs drawer, spotlight keynote, install view, and failure view) includes one-click "Copy curl" and "Copy CLI" commands:
```bash
curl -L -C - -o "models/model.gguf" "https://huggingface.co/repo/resolve/main/model.gguf"
```
The download supports HTTP Range resume, ensuring no progress is lost if the connection drops.

### 6. Output Structured JSON
For scripts and automated agent analysis:
```bash
python utils/hf_radar.py --json
python utils/hf_radar.py --history --json
```

### 7. Access via Launchpad Setup UI
You can also launch the general setup server:
```bash
python utils/model_setup.py --ui
```
And click **"Model Radar"** or **"Sync History"** in the top navigation bar.

