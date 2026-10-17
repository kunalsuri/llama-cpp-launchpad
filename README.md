<div align="center">

# 🚀 llama-cpp-launchpad

**Local AI in one command.**

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![Platforms](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-blue)
![Powered by](https://img.shields.io/badge/powered%20by-llama.cpp-orange)

</div>

Pick a model. Pick an interface. Start chatting. Everything runs on your machine.

```
  ✻ llama-cpp-launchpad  local model server

  Choose a model  ↑/↓ move · enter select · q quit

  ❯ gemma-3-4b-it-Q4_K_M.gguf                      2.4G
    Qwen3-1.7B-Q4_K_M.gguf                         1.2G

  Choose an interface  ↑/↓ move · enter select · q quit

  ❯ llama.cpp Default                       built-in chat
    Translation                                translator
```

> [!NOTE]
> **Zero Pip Dependencies:** `llama-cpp-launchpad` runs using standard Python 3 only. No virtual environment, `pip install`, or extra packages are needed to download models, benchmark, or serve them. (A `.venv` is only used if you are running developer tests).

---

## Start

**0. See what you already have** (optional, 2 seconds)

```bash
# Windows
scripts\win\detect-tools.bat

# Linux / macOS (or double-click scripts/mac/detect-tools.command)
./scripts/unix/detect-tools.sh
```

Lists Ollama, llama.cpp, LM Studio, and Unsloth: installed or not, version, and location.
Everything it needs is Python 3 ([install](#troubleshooting) if the command says it is missing).

**1. Get llama.cpp**

```bash
winget install llama.cpp        # Windows (then open a new terminal)
brew install llama.cpp          # macOS
```

*Linux*: Download a [release](https://github.com/ggml-org/llama.cpp/releases) and copy `llama-server` into `bin/`.  
Already have it? Check with `llama-server --version`.

**2. Get a model that fits your machine**

You can use either the visual browser wizard or the terminal:

- **Option A: Visual Setup Wizard (Easiest)**

  ```bash
  scripts\win\ui.bat            # Windows (or double-click)
  ./scripts/unix/ui.sh          # Linux / macOS (or double-click scripts/mac/ui.command)
  ```

  Opens a local web page. Select what you will use the model for, and it downloads, tests speed, and configures everything with one click.

- **Option B: Terminal CLI**

  ```bash
  scripts\win\model-setup.bat   # Windows
  ./scripts/unix/model-setup.sh # Linux / macOS
  ```

  Inspects your RAM & GPU, recommends matching models from Hugging Face, downloads your pick, and benchmarks real tokens/second.  
  *(Prefer manual downloads? Drop any `.gguf` file into `models/`, see [models/README.md](models/README.md)).*

**3. Run**

```bash
scripts\win\serve.bat           # Windows (or double-click it)
./scripts/unix/serve.sh         # Linux / macOS (or double-click scripts/mac/serve.command)
```

Use arrow keys to choose a model and an interface. The server starts at `http://localhost:8080` and opens your browser automatically.

---

## Visual Setup & Tools Dashboard

Run `ui` (e.g. `scripts\win\ui.bat` or `./scripts/unix/ui.sh`) to open the local browser setup interface:

- **1-Click Recommendations:** Answers *"What will you use it for?"*, picks the optimal model for your exact CPU/GPU/RAM, downloads with resume support, and runs a speed test.
- **Installed tools Dashboard:** Click **Installed tools** (or visit `http://localhost:9000/#tools`) to see all detected local AI engines (Ollama, llama.cpp, LM Studio, Unsloth) with installation paths, versions, and copy-paste startup commands.
- **Local & Private:** Listens only on `127.0.0.1` and requires zero npm or pip packages.

---

## Interfaces

### Built-in Interfaces

| Interface | Description |
| --- | --- |
| **llama.cpp Default** | llama.cpp's own built-in web chat UI. |
| **Translation** | Clean, fast translation UI matching llama.cpp styling. Select language pairs, swap, choose formal (*vous*) or informal (*tu*) register, and adjust temperature. Self-contained HTML file with no dependencies. |

Small models (1B) translate roughly; 4B and up produce high-quality translations.

---

### External Frontends & Live Internet Access (Open WebUI)

`llama-cpp-launchpad` serves an **OpenAI-compatible API** at:

```
http://localhost:8080/v1
```

By default, local models run completely offline. If you want a ChatGPT-style interface with **live internet access** (e.g. weather in Paris, real-time web browsing via DuckDuckGo), conversation history, or document upload (RAG), you can connect [Open WebUI](https://github.com/open-webui/open-webui):

#### 1. Start Open WebUI (on port 3000)

> [!TIP]
> Launchpad uses port `8080`, so run Open WebUI on port `3000` to prevent port collisions.  
> Open WebUI requires Python 3.11–3.12. Using `uv` or Docker is recommended:

```bash
# Method A: Using uv (fastest, downloads Python 3.12 automatically)
uvx --python 3.12 open-webui serve --port 3000

# Method B: Using a dedicated virtualenv with uv
uv venv .venv-312 --python 3.12
.\.venv-312\Scripts\Activate.ps1   # (Linux/macOS: source .venv-312/bin/activate)
uv pip install open-webui
open-webui serve --port 3000

# Method C: Using Docker Desktop
docker run -d -p 3000:8080 --add-host=host.docker.internal:host-gateway -v open-webui:/app/backend/data --name open-webui --restart always ghcr.io/open-webui/open-webui:main
```

#### 2. Connect Open WebUI to `llama-cpp-launchpad`

1. Open **`http://localhost:3000`** in your browser and create your local account.
2. Navigate to **Settings** (or **Admin Panel**) ➔ **Connections** ➔ **OpenAI API**.
3. Set the connection URL:
   - For pip / uv installations: `http://localhost:8080/v1`
   - For Docker installations: `http://host.docker.internal:8080/v1`
4. Enter any placeholder API Key (e.g. `sk-launchpad`).
5. Click the 🔄 verify button — your running GGUF model will be detected automatically. Click **Save**.

#### 3. Enable Web Search (Live Internet Queries)

1. In Open WebUI, go to **Settings** ➔ **Web Search**.
2. Turn **Enable Web Search** to **ON**.
3. Under **Web Search Engine**, select **`duckduckgo`** (completely free, no API key required).
4. In any chat, ensure the web search toggle (globe icon) is enabled, then ask real-time questions (e.g., *"What is the current weather in Paris right now?"*). Open WebUI fetches live search results and injects them directly into your local model's prompt!

---

## model-setup (CLI)

Which model should you run? The CLI tool provides fine-grained control:

- **First run:** Detects RAM and GPU, shows up to five models that fit with estimated speed, downloads your selection, and benchmarks the actual tokens/second.
- **Weekly update check:** `serve` can periodically check for newly released models that beat your current setup.
- **On demand:**

  ```bash
  ./scripts/unix/model-setup.sh --check-updates   # Windows: scripts\win\model-setup.bat --check-updates
  ./scripts/unix/model-setup.sh --test            # re-run the speed benchmark
  ./scripts/unix/model-setup.sh --list            # show recommendations only
  ```

### Discovering Models from Hugging Face

`--discover` searches the Hugging Face Hub for GGUF models your machine can run, beyond the built-in catalog:

```bash
./scripts/unix/model-setup.sh --discover                          # best fits from trusted authors
./scripts/unix/model-setup.sh --discover --search coder --list    # search for coder models
./scripts/unix/model-setup.sh --discover --ctx 16384 --all        # plan for 16k context, include all authors
./scripts/unix/model-setup.sh --discover --json --top 20          # machine-readable JSON output
```

- Filters: `--sort popular|size|speed`, `--hub downloads|trending|recent`, `--author NAME`, `--min-tps N`.
- Safe & audited: standard library only, talks strictly to `huggingface.co`, and writes only to `models/` and `.launchpad-state`.

---

## detect-tools (CLI)

Checks whether Ollama, llama.cpp, LM Studio, or Unsloth are installed on your system:

```bash
scripts\win\detect-tools.bat            # Windows
./scripts/unix/detect-tools.sh           # Linux / macOS (scripts/mac/detect-tools.command to double-click)
```

- Flags: `--json` for automation, `--verbose` to inspect checked paths (evidence), `--tool ollama` to filter, `--strict` to exit 1 if anything is missing.
- Read-only, standard library only, no network calls.

---

## Options & Configuration

Configure behavior using environment variables on any platform:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MODELS_DIR` | `models/` | Folder containing your `.gguf` files |
| `LLAMA_SERVER` | auto-detected | Path to `llama-server` binary |
| `PORT` | `8080` | Port for `llama-server` to serve on |
| `UI` | ask | `default` or `translation` (bypasses menu) |
| `OPEN_BROWSER` | `1` | Automatically open the web browser when server starts |
| `KILL_EXISTING` | `1` | Stop any running `llama-server` process before starting |
| `EXTRA_ARGS` | empty | Extra flags for `llama-server`, e.g. `"-t 8 -c 8192"` |
| `CHECK_DAYS` | `7` | Days between new model prompts (`0` = disable) |
| `INCLUDE_ALL` | off | `1` = suggest community fine-tunes and unknown authors |
| `LP_RAM_MB`, `LP_VRAM_MB` | detected | Override hardware RAM/VRAM detection |

Example:

```bash
PORT=9000 UI=translation ./scripts/unix/serve.sh
# Windows PowerShell:
# $env:PORT = "9000"; scripts\win\serve.bat
```

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| **PowerShell: Running scripts is disabled** | Use the double-click `.bat` scripts (`serve.bat`, `ui.bat`, `model-setup.bat`) which bypass policy automatically. Or run: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in your PowerShell session. |
| **Could not find llama-server** | Install `llama.cpp` (Step 1) or set `LLAMA_SERVER`. On Windows, open a fresh terminal after running `winget`. |
| **Port in use (8080 or 3000)** | Set `PORT=9000` for launchpad. If running Open WebUI, run it on `--port 3000` to avoid conflicting with launchpad on 8080. |
| **Open WebUI pip install fails on Python 3.13** | Open WebUI requires Python 3.11–3.12. Use `uvx --python 3.12 open-webui serve --port 3000` or Docker Desktop. |
| **Browser shows `File Not Found`** | Your build lacks the web chat assets (common with some Homebrew builds). Choose **Translation** or download a release binary. |
| **No `.gguf` models found** | Run `model-setup` or `ui` to download a model, or manually place a `.gguf` file into `models/`. |
| **Very slow replies** | Pick a smaller model, or pass `EXTRA_ARGS="-t 8"`. |
| **Out of memory** | Pick a smaller model (a `Q4_K_M` quant is recommended for most setups). |
| **model-setup says "GPU not used"** | Your llama.cpp binary is CPU-only. Install a CUDA, Vulkan, or Metal build. |
| **model-setup needs Python** | Install Python 3 (`winget install Python.Python.3.12`, `brew install python`, or `sudo apt install python3`). |

---

## Develop

`llama-cpp-launchpad` itself is strictly Python standard library. Developer dependencies (`pytest`, `coverage`) are only needed to run tests:

```bash
python tests/run.py                    # same command on every OS and CI (-k NAME, --repeat 5, --cov)
```

### Windows Dev Plumbing

Two helper scripts manage developer setup and testing on Windows:

```powershell
scripts\win\dev-setup.ps1   # creates .venv, installs pytest/coverage, detects tools, audits imports, writes .system.env
scripts\win\dev-test.ps1    # runs the test suite with pytest inside .venv (e.g. scripts\win\dev-test.ps1 -k audit)
```

### Project Structure

```
models/              your .gguf files (git-ignored)
bin/                 optional llama-server binary (git-ignored)
scripts/             serve, model-setup, ui, and detect-tools launchers (win / mac / unix)
ui/setup/            visual model setup page & tools dashboard (one self-contained HTML file)
ui/translation/      translation interface (self-contained HTML file)
utils/               model_setup.py, hf_discover.py, ui_server.py, hardware.py, detect_tools.py, models.catalog
tests/               unit tests, source audit, runner (run.py), fake machine (fakes.py)
```

See [tests/README.md](tests/README.md) for details on testing rules, hermetic machine mocking, and CI checks.

---

## License

[MIT](LICENSE) © Kunal Suri
