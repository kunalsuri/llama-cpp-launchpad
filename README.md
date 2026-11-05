<div align="center">

# 🚀 llama-cpp-launchpad

**Local AI in one command.**

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![Platforms](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-blue)
![Powered by](https://img.shields.io/badge/powered%20by-llama.cpp-orange)

</div>

A launcher for [llama.cpp](https://github.com/ggml-org/llama.cpp)'s `llama-server`. It finds or installs llama.cpp,
picks a model that fits your computer, downloads and speed-tests it, and starts a chat in your browser. The model runs
on your machine; nothing is sent anywhere.

```
  ✻ llama-cpp-launchpad  local model server

  Choose a model  ↑/↓ move · enter select · q quit

  ❯ gemma-3-4b-it-Q4_K_M.gguf                      2.4G
    Qwen3-1.7B-Q4_K_M.gguf                         1.2G

  Choose an interface  ↑/↓ move · enter select · q quit

  ❯ llama.cpp Default                       built-in chat
    Translation                                translator
```

**What it is not:** it does not run models itself (llama.cpp does), it does not train or fine-tune, and it does not rank
models by quality. Speeds it shows are measured on your machine, or labelled as estimates.

**New here?** [Getting started](docs/getting-started.md) goes from nothing to a first reply, step by step. Every guide
is listed in the [documentation](docs/README.md).

## Contents

- [Requirements](#requirements)
- [Start](#start)
- [What you can do](#what-you-can-do)
- [Interfaces](#interfaces)
- [Use it from other programs](#use-it-from-other-programs)
- [Command-line tools](#command-line-tools)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Privacy and safety](#privacy-and-safety)
- [Develop and contribute](#develop-and-contribute)
- [License](#license)

## Requirements

- **Python 3**, standard library only: no `pip install`, no virtual environment. CI tests Python 3.10 and 3.13 on
  Linux, macOS and Windows.
- **llama.cpp's `llama-server`**. The setup page can get it for you (below).
- **Disk and memory for a model**: roughly 1–3 GB for the small models it suggests first. It checks what fits.

## Start

**No terminal: double-click `launchpad`.**

| OS | Double-click | Or run |
| --- | --- | --- |
| Windows | `scripts\win\launchpad.bat` | `scripts\win\launchpad.bat` |
| macOS | `scripts/mac/launchpad.command` | `./scripts/unix/launchpad.sh` |
| Linux | | `./scripts/unix/launchpad.sh` |

It opens the setup page in your browser. From there: get llama.cpp if it is missing (Windows and Linux download the
official release into `bin/`; macOS uses Homebrew when it is installed), get a model that fits this computer, and press
**Start chatting**. The steps below do the same from a terminal.

**0. See what you already have** (optional, 2 seconds)

```bash
scripts\win\detect-tools.bat     # Windows
./scripts/unix/detect-tools.sh   # Linux / macOS (or double-click scripts/mac/detect-tools.command)
```

Lists Ollama, llama.cpp, LM Studio and Unsloth: installed or not, version, and location.

**1. Get llama.cpp**

```bash
winget install ggml.llamacpp    # Windows (then open a new terminal)
brew install llama.cpp          # macOS
```

*Linux*: use the setup page's **Get llama.cpp**, or download a [release](https://github.com/ggml-org/llama.cpp/releases)
and copy `llama-server` into `bin/`. Already have it? Check with `llama-server --version`.

**2. Get a model that fits your machine**

```bash
scripts\win\ui.bat              # Windows: the setup page (or double-click)
./scripts/unix/ui.sh            # Linux / macOS (or double-click scripts/mac/ui.command)

scripts\win\model-setup.bat     # Windows: the same, in the terminal
./scripts/unix/model-setup.sh   # Linux / macOS
```

Both inspect your RAM and GPU, recommend models from Hugging Face that fit, download your pick and measure real
tokens/second. Prefer to download by hand? Put any `.gguf` file in `models/` ([models/README.md](models/README.md)).

**3. Run**

```bash
scripts\win\serve.bat           # Windows (or double-click it)
./scripts/unix/serve.sh         # Linux / macOS (or double-click scripts/mac/serve.command)
```

Choose a model and an interface with the arrow keys. The server starts at `http://localhost:8080` and opens your
browser.

## What you can do

The setup page (`ui` or `launchpad`, normally at `http://127.0.0.1:8765/`) does all of this. The
[full reference](docs/setup-page.md) lists every option and what it checks.

- **Get a model** for a stated use (chat, coding, translation…), with a resumable download checked against the SHA-256
  Hugging Face publishes, and a speed test.
- **Choose settings with their cost shown**: presets for short chats, long documents or fastest replies, each with the
  exact command and the memory it needs, worked out from the model file's own header. Settings are remembered per
  model and used by the serve scripts.
- **Start and stop a chat** from the page, with llama-server's own output when it fails and a free port when 8080 is
  taken.
- **Get llama.cpp** (`/#llama`): the official build for your GPU (CUDA, Vulkan or CPU) into `bin/`, verified before it
  is kept; Homebrew on macOS.
- **Understand the result**: why a model is slow, what a quantization costs, image support for vision models.
- **My models** (`/#models`): sizes and free disk; delete; compare two or three models on the same prompts, side by
  side (you judge the answers; there is no score); serve all of them at one address with llama.cpp's router mode.
- **Model radar** (`/#radar`, `/#history`): new and trending GGUF models that fit your memory.
- **Installed tools** (`/#tools`): Ollama, llama.cpp, LM Studio and Unsloth, found or not, and how to start each.

Every command the page shows is for your OS and uses only programs it found.

## Interfaces

`serve` asks which interface to open (or set `UI=`):

| Interface | What it is |
| --- | --- |
| **llama.cpp Default** | llama.cpp's own built-in web chat. |
| **Translation** | Language pairs, swap, formal or informal register, temperature. One self-contained HTML file. |
| **Tasks** | *Summarize* (bullets, paragraph, detailed), *Explain code* (beginner or developer, with likely bugs), *Rewrite* (plainer, more formal, friendlier, shorter). One self-contained HTML file. |

Small models (around 1B) translate roughly; 4B and up do much better.

## Use it from other programs

While a model runs, `llama-server` serves an OpenAI-compatible API at `http://localhost:8080/v1`. The setup page shows
the address, key and model name to paste, plus ready settings for Open WebUI, Continue and aider.

For conversation history, document upload or web search, see [Using Open WebUI](docs/open-webui.md).

## Command-line tools

Each tool has a launcher in `scripts/win` (`.bat`), `scripts/unix` (`.sh`) and `scripts/mac` (`.command`, double-click).
`--help` lists every flag.

```bash
./scripts/unix/model-setup.sh --list            # recommendations for this machine, no download
./scripts/unix/model-setup.sh --test            # re-run the speed test
./scripts/unix/model-setup.sh --check-updates   # newer models that fit (serve also asks every CHECK_DAYS)
./scripts/unix/model-setup.sh --discover --search coder --list   # search all of Hugging Face
./scripts/unix/model-setup.sh --discover --ctx 16384 --json      # plan for 16k context, JSON output

./scripts/unix/radar.sh --dashboard             # trending models in the terminal
./scripts/unix/radar.sh --download REPO         # download, resumable and checksum-verified

./scripts/unix/detect-tools.sh --verbose        # every location checked, found or not
./scripts/unix/detect-tools.sh --json --strict  # for scripts: exit 1 if anything is missing

python utils/gguf.py models/MODEL.gguf --ctx 32768 --cache-type-k q8_0   # memory needed at that context
python utils/compare.py models/A.gguf models/B.gguf                      # same prompts, answers side by side
```

`--discover` talks only to `huggingface.co` and reads each model's header (the first megabytes, by HTTP Range) to size
its context cache exactly; when it cannot, the table marks the figure as a rough estimate.

## Configuration

Environment variables, on every platform:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MODELS_DIR` | `models/` | Folder with your `.gguf` files |
| `LLAMA_SERVER` | auto-detected | Path to the `llama-server` program |
| `PORT` | `8080` | Port for `llama-server` |
| `UI` | ask | `default`, `translation` or `tasks` (skips the menu) |
| `OPEN_BROWSER` | `1` | Open the browser when the server starts |
| `KILL_EXISTING` | `1` | Stop a running `llama-server` before starting |
| `EXTRA_ARGS` | empty | Extra `llama-server` flags, e.g. `"-t 8 -c 8192"` (override remembered settings) |
| `CHECK_DAYS` | `7` | Days between new-model prompts (`0` = never) |
| `INCLUDE_ALL` | off | `1` = also suggest community fine-tunes and unknown authors |
| `LP_RAM_MB`, `LP_VRAM_MB` | detected | Override detected RAM / graphics memory |

```bash
PORT=9000 UI=translation ./scripts/unix/serve.sh
# Windows PowerShell:  $env:PORT = "9000"; scripts\win\serve.bat
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| **PowerShell: running scripts is disabled** | Use the `.bat` scripts (`serve.bat`, `ui.bat`, `model-setup.bat`), which pass `-ExecutionPolicy Bypass` for you, or run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`. |
| **Could not find llama-server** | Do step 1 or set `LLAMA_SERVER`. On Windows, open a new terminal after `winget`. |
| **"Another llama-server comes first"** after installing | A copy on your PATH (or in `LLAMA_SERVER`) is found before `bin/`. Remove it from PATH, or set `LLAMA_SERVER` to the `bin/` copy the page names. |
| **The Vulkan or CUDA build "did not start"** | Press **Install the CPU build instead**, or install your GPU driver (Linux Vulkan needs the system's Vulkan loader, e.g. `libvulkan1`). |
| **Port in use** | The setup page names the program holding it and offers the next free port. For the scripts, set `PORT=9000`. |
| **Start chatting failed** | The page shows llama-server's output. "failed to load model" usually means the model is too big for this computer's memory. |
| **Browser shows `File Not Found`** | Your llama.cpp build lacks the web chat files (some Homebrew builds). Choose **Translation**, or use a release build. |
| **No `.gguf` models found** | Run `ui` or `model-setup`, or put a `.gguf` file in `models/`. |
| **Very slow replies** | The setup page's speed test names the cause it can check. Otherwise pick a smaller model, or try `EXTRA_ARGS="-t 8"`. |
| **Out of memory** | Pick a smaller model; `Q4_K_M` suits most machines. |
| **"GPU not used"** | Your llama.cpp build is CPU-only. Get a CUDA, Vulkan or Metal build (the setup page's **Get llama.cpp**). |
| **Download stopped** | Press **Try again**, or run the command the page shows (`radar --download ...`): it continues the partial file. |
| **Radar could not reach Hugging Face** | It shows your last saved scan. Check your connection or proxy, then press **Sync now**. |
| **Python is missing** | `winget install Python.Python.3.12`, `brew install python`, or `sudo apt install python3`. |
| **`Permission denied` on a `.sh` script** | `bash scripts/unix/ui.sh`, or once: `chmod +x scripts/unix/*.sh scripts/mac/*.command`. |
| **macOS won't open a `.command` file** | ZIP downloads are quarantined. Right-click → **Open** once, or run `xattr -dr com.apple.quarantine .` in the project folder. |
| **Open WebUI** problems | See [docs/open-webui.md](docs/open-webui.md). |

## Privacy and safety

- The setup page listens only on `127.0.0.1`, loads nothing from the internet into the page, and every action that
  changes something (download, install, start, stop) needs the page's own token.
- Network access is limited to Hugging Face (models) and GitHub releases (llama.cpp), over HTTPS. Downloads are checked
  against the published SHA-256 when one exists, and the page says when it does not.
- It writes inside the project folder: models to `models/`, llama.cpp to `bin/`, radar history to `data/`, and small
  state files such as `.launchpad-state`. Nothing needs admin rights.
- `utils/` uses the Python standard library only; a source audit in the tests enforces it, along with bans on
  `shell=True`, `eval` and similar.

## Develop and contribute

Read [CLAUDE.md](CLAUDE.md) (the rules, each from a real bug) and [tests/README.md](tests/README.md) (the test
workflow: test first, red, green). Pull requests should come with tests.

```bash
python tests/run.py                    # same command on every OS and in CI (-k NAME, --repeat 5, --cov --min 85)
python tests/run.py --as mac           # pretend to be another machine: mac, mac-intel, linux, linux-arm
```

The tests run offline, without a GPU or llama.cpp. Developer tools (`pytest`, `coverage`) are only for tests. The
setup page is tested twice: `tests/page_harness.js` runs its script against a fake DOM (screens, polling, Back), and
`tests/browser_check.js` opens it in real Chromium at several widths, light and dark. The browser check needs Node and
Playwright and is skipped, with a reason, without them:

```bash
npm ci && npx playwright install chromium   # once
python tests/run.py -k TestBrowser
```

On Windows, `scripts\win\dev-setup.ps1` creates `.venv` with the test tools and `scripts\win\dev-test.ps1` runs the
suite in it.

```
models/      your .gguf files (git-ignored)          bin/     optional llama-server (git-ignored)
scripts/     launchers: win / mac / unix              ui/      setup page, translation, tasks (one HTML file each)
utils/       all Python, standard library only       tests/   tests, source audit, runner, fake machine
docs/        guides, setup page reference, media     tools/   docs-media: makes the docs' screenshots and videos
```

## License

[MIT](LICENSE) © Kunal Suri
