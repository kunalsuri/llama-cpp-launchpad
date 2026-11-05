# Getting started

From nothing to a first reply from a model running on your computer. It takes two downloads, llama.cpp (unless you
already have it) and one model (about 1–3 GB for the small models suggested first); chatting after that needs no
connection. Back to the [documentation home](README.md).

> **Screenshots and video:** not recorded yet. They will be made from a real run by
> [`tools/docs-media/capture.py`](media/README.md) and added here with the machine they were recorded on.

## What you need

- **Python 3.** Nothing else to install for the launcher itself: no `pip install`, no virtual environment.
  Missing? `winget install Python.Python.3.12` (Windows), `brew install python` (macOS), `sudo apt install python3`
  (Debian, Ubuntu).
- **An internet connection for the first run**, to [Hugging Face](https://huggingface.co) (models) and
  [GitHub releases](https://github.com/ggml-org/llama.cpp/releases) (llama.cpp). Both are reached over HTTPS, and
  nothing else is contacted.
- **Disk and memory for one model.** The setup page checks what fits before it suggests anything.

## 1. Open the setup page

| OS | Double-click | Or, in a terminal in the project folder |
| --- | --- | --- |
| Windows | `scripts\win\launchpad.bat` | `scripts\win\launchpad.bat` |
| macOS | `scripts/mac/launchpad.command` | `./scripts/unix/launchpad.sh` |
| Linux | | `./scripts/unix/launchpad.sh` |

Your browser opens the setup page, normally at `http://127.0.0.1:8765/` (if that port is taken, the next free one is
used, and the terminal prints the address). The page is served only to this computer. The terminal window that opened
keeps the page running: **Ctrl+C** in it stops the page.

*macOS: if the `.command` file will not open*, the ZIP download was quarantined. Right-click it, choose **Open** once,
or run `xattr -dr com.apple.quarantine .` in the project folder.

## 2. Get llama.cpp, if the page asks

The page looks for a working `llama-server` in `LLAMA_SERVER`, your PATH, the project's `bin/` folder and
`~/llama.cpp/build/bin`. When it finds none, or finds one that cannot use your graphics card, it offers
**Get llama.cpp**:

- **Windows and Linux**: it downloads the official build for this computer (CUDA for NVIDIA, Vulkan for AMD and
  Intel Arc, otherwise CPU) into `bin/`, checks it, and keeps it only if `llama-server --version` runs. No
  administrator rights are needed, and nothing outside `bin/` changes.
- **macOS**: it runs `brew install llama.cpp` when Homebrew is installed, and shows the steps otherwise.

Already have llama.cpp? Check with `llama-server --version`; the page uses it.

## 3. Say what you will use it for

The first screen asks *What will you use it for?* with four choices: *General chat*, *Writing code*, *Translation*
and *Fastest replies*. Pick one. The page compares models from Hugging Face with this computer's memory and graphics
card and recommends one, with its size, the memory it needs and an estimated speed. An estimate is labelled as one.

## 4. Get the model

Press **Get this model** (it reads **Use this model** when the file is already in `models/`). The download:

- continues where it stopped if the connection drops (press **Try again**);
- is checked against the SHA-256 that Hugging Face publishes for the file, and a file that does not match is not
  kept (when Hugging Face publishes no checksum, only the size is checked, and the page says so);
- ends with a speed test on this computer, so the speed on the next screen is measured, not estimated.

The model is saved in the project's `models/` folder.

## 5. Choose settings and start

The **Ready** screen shows the measured speed. If it is under 15 tokens per second, it names the cause it can check
(for example, a graphics card your llama.cpp build cannot use). Below that are presets, each with the exact command
and the memory it needs:

| Preset | What it sets |
| --- | --- |
| *Short chats* | `-c 4096` |
| *Long documents* | `-c 32768`, 8-bit key cache |
| *Fastest replies* | `-c 2048 -ngl 99`, offered only with a usable graphics card |
| *Let llama.cpp decide* | no flags; the default when your llama-server has `--fit` |

A preset is offered only when your `llama-server` lists its flags in `--help`. The settings you start with are
remembered for this model and used later by the `serve` scripts as well.

Press **Start chatting**. The page starts `llama-server`, shows the command it ran, and shows **Open the chat** when
the model is loaded. If it fails, the page shows llama-server's own output; "failed to load model" usually means the
model is too big for this computer's memory.

## 6. Chat

**Open the chat** opens llama.cpp's built-in chat page, served by `llama-server` on this computer. Type a message and
press Enter. While the chat runs, the setup page also shows the address and settings for other programs
([guide](guides/other-programs.md)).

**Stop** on the setup page stops the server it started; closing the setup page's window stops it too.

## Next

- Run a model without the setup page, and choose the **Tasks** or **Translation** interface:
  [Run a model from the terminal](guides/serve.md).
- [Summarize, explain code, rewrite](guides/tasks.md) · [Translate text](guides/translation.md)
- Everything else on the setup page (My models, compare, model radar, installed tools):
  [full reference](setup-page.md).
- Something went wrong: [Troubleshooting](../README.md#troubleshooting).
