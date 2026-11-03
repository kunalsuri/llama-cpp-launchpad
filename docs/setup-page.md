# The setup page: full reference

Start it with `scripts\win\ui.bat` (Windows) or `./scripts/unix/ui.sh` (Linux / macOS; double-click
`scripts/mac/ui.command`). `launchpad` opens the same page. It prints its address (normally `http://127.0.0.1:8765/`)
and opens your browser. Back to the [README](../README.md).

## Get a model

- Answers *"What will you use it for?"*, picks the model that fits your CPU/GPU/RAM, downloads it (resumable) and runs
  a speed test.
- Every download (page, `model-setup`, `radar --download`) is checked against the SHA-256 Hugging Face publishes for the
  file; a file that does not match is not kept. When Hugging Face gives no checksum, only the size is checked, and it
  says so.

## How will you use it? (presets)

Before starting, pick a preset:

| Preset | Flags |
| --- | --- |
| *Short chats* | `-c 4096` |
| *Long documents* | `-c 32768`, 8-bit key cache |
| *Fastest replies* | `-c 2048 -ngl 99`, only with a usable graphics card |
| *Let llama.cpp decide* | no flags; the default when your llama-server has `--fit` |

Each shows its exact command and the memory it needs (the model's weights + its context cache, worked out from the
model file's own header, + overhead), and whether that fits your graphics card or memory. A preset is offered only when
your llama-server lists its flags in `--help`. Advanced users can type a context length. The settings you start with are
remembered for that model, and the serve scripts use them too (before `EXTRA_ARGS`, so your own flags still win).

## Explanations on the page

- **Why is it slow?** After a speed test under 15 tokens/s, the done screen names the cause it can check on this
  computer: a graphics card your llama.cpp build cannot use, a model too big for the card, a model that takes most of
  your memory, or a run far below what this kind of computer usually manages.
- **What do these mean?** The recommended model's card explains its quantization (e.g. what 4-bit costs and saves),
  the memory it needs, and its speed in words per second against reading speed.
- **Image support:** for a vision model whose Hugging Face repository has a projector file (`mmproj`), the done screen
  offers *Add image support*; the chat then starts with `--mmproj` (also from the serve scripts).

## Start chatting

- The done screen starts `llama-server` with that model and shows the exact command first
  (`llama-server -m MODEL --port PORT`, plus `EXTRA_ARGS`, as the serve scripts do; `PORT` and `EXTRA_ARGS` come from
  the environment the page was started in).
- It shows *starting*, *running* (with an **Open the chat** link), *stopped*, or *failed* with llama-server's own
  output.
- **Stop** stops only the server this page started; closing the page's window stops it too.
- If port 8080 is taken, the page says which program holds it and offers the next free port.
- **Use it from other programs:** while a chat runs, the page shows the address, key and model name for any
  OpenAI-API program, Open WebUI's connection settings, a Continue `config.yaml`, and the aider command (only when
  aider is installed).

## Get llama.cpp (`/#llama`)

Offered when no working `llama-server` is found (looked for in `LLAMA_SERVER`, your PATH, `bin/`,
`~/llama.cpp/build/bin`), or when the one found cannot use your graphics card.

- *Windows, Linux:* downloads the official build for this machine from
  [github.com/ggml-org/llama.cpp/releases](https://github.com/ggml-org/llama.cpp/releases) over HTTPS into `bin/`:
  - CUDA for NVIDIA, with its CUDA runtime archive, and never newer than the CUDA your driver runs (`nvidia-smi` shows
    it); if the driver is too old for every CUDA build, Vulkan, with a note that a driver update gets CUDA;
  - Vulkan for AMD graphics (Windows and Linux), Intel Arc (Windows, found by name) or a GPU you declared with
    `LP_VRAM_MB`. Integrated Intel graphics keep the CPU build: they rarely run models faster than the processor;
  - otherwise CPU.

  No admin rights; nothing outside `bin/` changes. It checks the size, the SHA-256 when GitHub publishes one (and says
  so when it does not), and that `llama-server --version` runs before anything is moved into `bin/`. If a GPU build
  does not start, it offers the CPU build.
- *macOS:* runs `brew install llama.cpp` if Homebrew is installed; otherwise it shows the steps.
- If another `llama-server` comes first in the lookup order (`LLAMA_SERVER` or your PATH), the page says so: the serve
  scripts would use that one, not the copy in `bin/`.

## Model radar (`/#radar`) and What changed (`/#history`)

Trending and new GGUF models on Hugging Face, checked against your memory. Speeds are labelled as estimates until a
model is downloaded and tested.

## My models (`/#models`)

What is in the models folder, with size, origin, architecture and free disk space.

- *Delete* asks first, then removes the model's files (only files inside the models folder).
- *Compare*: pick two or three models; they answer the same prompts one after another (only one is in memory at a
  time), and the answers are shown side by side with llama-server's own speed figures. There is no quality score: a
  few prompts cannot rank models, so you judge the answers.
- *Serve all my models*: one llama-server for every model, in llama.cpp's router mode (`--models-preset`,
  `--models-max 1`). A program asks for a model by name and llama.cpp loads it, one at a time. Needs a llama.cpp recent
  enough to have router mode; the page says so otherwise.

## Installed tools (`/#tools`)

Ollama, llama.cpp, LM Studio and Unsloth: found or not, version, location, and how to start or install each one.

## Behaviour that applies everywhere

- **Every command shown is for your OS** and only uses programs that were found: `scripts\win\...bat` and `curl.exe`
  on Windows, `./scripts/unix/...sh` elsewhere, `winget` / `brew` / `pip` only when they are installed.
- **Works on phones, tablets and desktops**, light and dark, keyboard and screen reader friendly; browser Back/Forward
  work, and each view has its own address you can bookmark.
- **Local & private:** listens only on `127.0.0.1`, loads nothing from the internet into the page, needs no npm or pip
  packages. Everything that changes something (download, install, start, stop) is a POST that needs the page's own
  token.
