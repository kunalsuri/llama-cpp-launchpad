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

**No terminal: double-click `launchpad`.**

| OS | Double-click | Or run |
| --- | --- | --- |
| Windows | `scripts\win\launchpad.bat` | `scripts\win\launchpad.bat` |
| macOS | `scripts/mac/launchpad.command` | `./scripts/unix/launchpad.sh` |
| Linux | | `./scripts/unix/launchpad.sh` |

It opens the setup page in your browser. From there: get llama.cpp if it is missing (Windows and Linux download the
official release into `bin/`; macOS uses Homebrew when it is installed), get a model that fits this computer, and press
**Start chatting**. It needs Python 3 and nothing else. The steps below do the same from a terminal.

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
winget install ggml.llamacpp    # Windows (then open a new terminal)
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

Run `ui` (e.g. `scripts\win\ui.bat` or `./scripts/unix/ui.sh`) to open the local browser setup interface. It prints
its address (normally `http://127.0.0.1:8765/`) and opens your browser.

- **Get a model:** answers *"What will you use it for?"*, picks the model that fits your CPU/GPU/RAM, downloads it
  (resumable) and runs a speed test. Every download (page, `model-setup`, `radar --download`) is checked against the
  SHA-256 Hugging Face publishes for the file; a file that does not match is not kept. When Hugging Face gives no
  checksum, only the size is checked, and it says so.
- **How will you use it?** Before starting, pick a preset: *Short chats* (`-c 4096`), *Long documents* (`-c 32768`,
  8-bit key cache), *Fastest replies* (`-c 2048 -ngl 99`, only with a usable graphics card) or *Let llama.cpp decide*
  (no flags; the default when your llama-server has `--fit`). Each shows its exact command and the memory it needs
  (the model's weights + its context cache, worked out from the model file's own header, + overhead), and whether
  that fits your graphics card or memory. A preset is offered only when your llama-server lists its flags in `--help`.
  Advanced users can type a context length. The settings you start with are remembered for that model, and the serve
  scripts use them too (before `EXTRA_ARGS`, so your own flags still win).
- **Why is it slow?** After a speed test under 15 tokens/s, the done screen names the cause it can check on this
  computer: a graphics card your llama.cpp build cannot use, a model too big for the card, a model that takes most of
  your memory, or a run far below what this kind of computer usually manages.
- **What do these mean?** The recommended model's card explains its quantization (e.g. what 4-bit costs and saves),
  the memory it needs, and its speed in words per second against reading speed.
- **Image support:** for a vision model whose Hugging Face repository has a projector file (`mmproj`), the done
  screen offers *Add image support*; the chat then starts with `--mmproj` (also from the serve scripts).
- **Use it from other programs:** while a chat runs, the address, key and model name for any OpenAI-API program, Open
  WebUI's connection settings, a Continue `config.yaml`, and the aider command (only when aider is installed).
- **Start chatting:** the done screen starts `llama-server` with that model and shows the exact command first
  (`llama-server -m MODEL --port PORT`, plus `EXTRA_ARGS`, as the serve scripts do; `PORT` and `EXTRA_ARGS` come
  from the environment the page was started in). It shows *starting*, *running* (with an **Open the chat** link),
  *stopped*, or *failed* with llama-server's own output. **Stop** stops only the server this page started; closing
  the page's window stops it too. If port 8080 is taken, the page says which program holds it and offers the next free
  port.
- **Get llama.cpp** (`/#llama`): offered when no working `llama-server` is found (looked for in `LLAMA_SERVER`, your
  PATH, `bin/`, `~/llama.cpp/build/bin`), or when the one found cannot use your graphics card.
  - *Windows, Linux:* downloads the official build for this machine:
    - CUDA for NVIDIA, with its CUDA runtime archive, and never newer than the CUDA your driver runs (`nvidia-smi`
      shows it); if the driver is too old for every CUDA build, Vulkan, with a note that a driver update gets CUDA;
    - Vulkan for AMD graphics (Windows and Linux), Intel Arc (Windows, found by name) or a GPU you declared with
      `LP_VRAM_MB`. Integrated Intel graphics keep the CPU build: they rarely run models faster than the processor;
    - otherwise CPU;

    from
    [github.com/ggml-org/llama.cpp/releases](https://github.com/ggml-org/llama.cpp/releases) over HTTPS into `bin/`.
    No admin rights; nothing outside `bin/` changes. It checks the size, the SHA-256 when GitHub publishes one
    (and says so when it does not), and that `llama-server --version` runs before anything is moved into `bin/`.
    If a GPU build does not start, it offers the CPU build.
  - *macOS:* runs `brew install llama.cpp` if Homebrew is installed; otherwise it shows the steps.
  - If another `llama-server` comes first in the lookup order (`LLAMA_SERVER` or your PATH), the page says so: the
    serve scripts would use that one, not the copy in `bin/`.
- **Model radar** (`/#radar`) and **What changed** (`/#history`): trending and new GGUF models on Hugging Face, checked
  against your memory. Speeds are labelled as estimates until a model is downloaded and tested.
- **My models** (`/#models`): what is in the models folder, with size, origin, architecture and free disk space.
  - *Delete* asks first, then removes the model's files (only files inside the models folder).
  - *Compare*: pick two or three models; they answer the same prompts one after another (only one is in memory at a
    time), and the answers are shown side by side with llama-server's own speed figures. There is no quality score:
    a few prompts cannot rank models, so you judge the answers.
  - *Serve all my models*: one llama-server for every model, in llama.cpp's router mode (`--models-preset`,
    `--models-max 1`). A program asks for a model by name and llama.cpp loads it, one at a time. Needs a llama.cpp
    recent enough to have router mode; the page says so otherwise.
- **Installed tools** (`/#tools`): Ollama, llama.cpp, LM Studio and Unsloth: found or not, version, location, and how
  to start or install each one.
- **Every command shown is for your OS** and only uses programs that were found: `scripts\win\...bat` and `curl.exe`
  on Windows, `./scripts/unix/...sh` elsewhere, `winget` / `brew` / `pip` only when they are installed.
- **Works on phones, tablets and desktops**, light and dark, keyboard and screen reader friendly; browser Back/Forward
  work, and each view has its own address you can bookmark.
- **Local & private:** listens only on `127.0.0.1`, loads nothing from the internet, needs no npm or pip packages.
  Everything that changes something (download, install, start, stop) is a POST that needs the page's own token.

---

## Interfaces

### Built-in Interfaces

| Interface | Description |
| --- | --- |
| **llama.cpp Default** | llama.cpp's own built-in web chat UI. |
| **Translation** | Clean, fast translation UI matching llama.cpp styling. Select language pairs, swap, choose formal (*vous*) or informal (*tu*) register, and adjust temperature. Self-contained HTML file with no dependencies. |
| **Tasks** | Three everyday jobs with one option each: *Summarize* (bullets, a paragraph, or detailed), *Explain code* (for a beginner or a developer, with likely bugs listed), *Rewrite* (plainer, more formal, friendlier, shorter). Same style and self-contained file as Translation. `UI=tasks` skips the menu. |

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
- Memory is read from each shown model's own header (the first megabytes of the file, with an HTTP Range request):
  layers, key/value heads and trained context give the exact context-cache size. When the header cannot be read, the
  table says the figure is a rough estimate.

### More tools for the terminal

```bash
python utils/gguf.py models/MODEL.gguf --ctx 32768 --cache-type-k q8_0   # memory this model needs at that context
python utils/compare.py models/A.gguf models/B.gguf                      # same prompts, answers side by side
./scripts/unix/model-setup.sh --profile-args MODEL.gguf                  # settings saved for a model on the setup page
```

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
| `UI` | ask | `default`, `translation` or `tasks` (bypasses menu) |
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
| **`Permission denied` running a `.sh` script** | Run it with bash (`bash scripts/unix/ui.sh`) or make it executable once: `chmod +x scripts/unix/*.sh scripts/mac/*.command`. |
| **macOS won't open a `.command` file** | If you downloaded the project as a ZIP, macOS quarantines it. Right-click the file and choose **Open** once, or run `xattr -dr com.apple.quarantine .` in the project folder. |
| **Setup page download stopped** | Press **Try again**, or run the command the page shows (`radar --download ...`): it continues the partial file instead of starting over. |
| **Radar says it could not reach Hugging Face** | It shows your last saved scan. Check your connection or proxy, then press **Sync now**. |
| **Start chatting says the port is in use** | The page names the program holding it and offers the next free port. To always use another port, start the page with `PORT` set (e.g. `PORT=8081 ./scripts/unix/launchpad.sh`). |
| **Start chatting failed** | The page shows llama-server's own output. "failed to load model" usually means the model is too big for this computer's memory. |
| **"Another llama-server comes first"** after installing | A copy on your PATH (or in `LLAMA_SERVER`) is found before `bin/`. Remove it from PATH, or set `LLAMA_SERVER` to the `bin/` copy the page names. |
| **The Vulkan or CUDA build "did not start"** | The page keeps nothing it could not start. Press **Install the CPU build instead**, or install your GPU driver (Linux Vulkan needs the system's Vulkan loader, e.g. `libvulkan1`). |

---

## Develop

`llama-cpp-launchpad` itself is strictly Python standard library. Developer dependencies (`pytest`, `coverage`) are only needed to run tests:

```bash
python tests/run.py                    # same command on every OS and CI (-k NAME, --repeat 5, --cov)
python tests/run.py --as mac           # pretend to be another machine (mac, mac-intel, linux, linux-arm)
```

The setup page has two layers of tests: `tests/page_harness.js` runs its script against a fake DOM (behaviour: screens,
polling, Back), and `tests/browser_check.js` opens it in real Chromium (layout at phone/tablet/desktop widths, light
and dark, clipboard, browser history). The browser check needs Node and Playwright, and is skipped with a reason
without them:

```bash
npm ci && npx playwright install chromium   # once
python tests/run.py -k TestBrowser
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
ui/tasks/            summarize / explain code / rewrite interface (self-contained HTML file)
utils/               model_setup.py, hf_discover.py, ui_server.py, hardware.py, detect_tools.py, models.catalog,
                     gguf.py (model headers, memory), chat_server.py, local_models.py (My models), compare.py,
                     router.py (all models at one address), clients.py (settings for other programs)
tests/               unit tests, source audit, runner (run.py), fake machine (fakes.py)
```

See [tests/README.md](tests/README.md) for details on testing rules, hermetic machine mocking, and CI checks.

---

## License

[MIT](LICENSE) © Kunal Suri
