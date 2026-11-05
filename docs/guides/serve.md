# Run a model from the terminal

`serve` starts llama.cpp's `llama-server` with a model from your `models/` folder and opens an interface in your
browser. Use it once you have a model (the [setup page](../getting-started.md) gets one), when you want the **Tasks**
or **Translation** interface, or to start a model from a script. Back to the [documentation home](../README.md).

> **Screenshots and video:** not recorded yet; see [How the pictures are made](../media/README.md).

## Start it

| OS | Double-click | Or, in a terminal in the project folder |
| --- | --- | --- |
| Windows | `scripts\win\serve.bat` | `scripts\win\serve.bat` |
| macOS | `scripts/mac/serve.command` | `./scripts/unix/serve.sh` |
| Linux | | `./scripts/unix/serve.sh` |

## What happens

1. **It finds `llama-server`**: `LLAMA_SERVER` if set, then your PATH, then `bin/` in the project, then
   `~/llama.cpp/build/bin` (Linux and macOS). If none is found, it says where it looked and how to install one.
2. **It stops any `llama-server` already running**, by name, so the port is free. This includes one you started
   yourself, outside this project. Set `KILL_EXISTING=0` to keep it.
3. **Every `CHECK_DAYS` days** (7 by default; `0` turns it off), once the setup page or `model-setup` has run on
   this computer, it asks whether to
   check Hugging Face for newer models that fit this computer: `y` checks now, `n` asks again in `CHECK_DAYS` days,
   `never` stops asking, and anything else asks again next time. Then it carries on.
4. **Choose a model.** The menu lists the `.gguf` files in `MODELS_DIR` with their size. Move with ↑/↓, choose with
   Enter, quit with `q`. A model split into parts (`name-00001-of-00003.gguf`, …) is listed once, by its first part,
   and only when every part is there. Vision projector files (`mmproj`) are not listed as models.
5. **Choose an interface**, unless `UI` is set:

   | Interface | `UI=` | What opens |
   | --- | --- | --- |
   | *llama.cpp Default* | `default` | llama.cpp's own chat page |
   | *Translation* | `translation` | [Translate text](translation.md) |
   | *Tasks* | `tasks` | [Summarize, explain code, rewrite](tasks.md) |

6. **It starts `llama-server`** on `http://localhost:8080` (or `PORT`) and opens your browser when the model has
   loaded (`OPEN_BROWSER=0` to skip that). **Ctrl+C** stops it.

## What it passes to llama-server

```text
llama-server -m MODELS_DIR/MODEL --port PORT [--path ui/INTERFACE] [--mmproj PROJECTOR] [SAVED SETTINGS] [EXTRA_ARGS]
```

- `--path` serves the Translation or Tasks page instead of llama.cpp's own.
- `--mmproj`: when a vision projector downloaded from the same Hugging Face repository as the model is in the models
  folder, and your `llama-server` lists `--mmproj` in its `--help`. The script says which it did.
- *Saved settings*: the settings you started this model with on the setup page (the presets). They come before
  `EXTRA_ARGS`, so a flag you set there wins.

## Settings

All optional, as environment variables, on every OS.

| Variable | Default | Meaning |
| --- | --- | --- |
| `MODELS_DIR` | `models/` | Folder with your `.gguf` files |
| `LLAMA_SERVER` | found as above | Path to the `llama-server` program |
| `PORT` | `8080` | Port for `llama-server` |
| `UI` | ask | `default`, `translation` or `tasks`: skip the interface menu |
| `OPEN_BROWSER` | `1` | Open the browser when the server is ready |
| `KILL_EXISTING` | `1` | Stop a running `llama-server` first |
| `EXTRA_ARGS` | empty | More `llama-server` flags, e.g. `"-t 8 -c 8192"` |
| `CHECK_DAYS` | `7` | Days between new-model offers (`0` = never) |

```bash
PORT=9000 UI=translation ./scripts/unix/serve.sh
```

```powershell
$env:PORT = "9000"; $env:UI = "translation"; scripts\win\serve.bat
```

## From a script (Linux and macOS)

When it is not run in a terminal, `serve.sh` shows no menus. It reads the model's number from its input, then the
interface's number (if `UI` is not set), each counted from 1 in the order the menus would show them:

```bash
printf '1\n3\n' | OPEN_BROWSER=0 ./scripts/unix/serve.sh    # first model, Tasks
```

It ends with `llama-server`'s own exit status, so a script can tell whether it failed.

## When it fails

| It says | What to do |
| --- | --- |
| *Could not find llama-server* | Get it on the setup page (**Get llama.cpp**), or set `LLAMA_SERVER`. On Windows, open a new terminal after `winget`. |
| *No .gguf models found* | Get one on the setup page, or put a `.gguf` file in `models/`. In a terminal it offers to run `model-setup`. |
| The browser shows *File Not Found* | Your llama.cpp build has no built-in chat page (some Homebrew builds). Choose *Translation*, or use a release build. |
| The port is in use | Set `PORT=9000` (any free port). |

More in the README's [Troubleshooting](../../README.md#troubleshooting).
