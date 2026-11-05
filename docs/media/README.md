# How the pictures are made

Every screenshot, GIF, video and terminal recording in this documentation is made by
[`tools/docs-media/capture.py`](../../tools/docs-media/capture.py) from the real program on a real machine, and
listed in [`manifest.json`](manifest.json) with how it was made. Back to the [documentation home](../README.md).

**Status:** no media has been captured yet. The pages say where pictures will go.

## The rules

1. **The real program only.** The setup page is started by `model-setup.py --ui`, as `ui.sh` does; `serve.sh` is
   typed into a real terminal; the Tasks and Translation pages are served by that `llama-server`. Publishing into
   `docs/media/` is refused when `llama-server` is the test suite's fake (`tests/fake_llama_server.py`) or any other
   program that does not report a llama.cpp version.
2. **Real model, named.** Each run records every model it used: file name, Hugging Face repository and SHA-256. The
   replies on screen are the model's own, unedited, including its mistakes.
3. **Real input.** What is typed into the pages is taken from this project's own files when the scene runs: the
   README's introduction to summarize, a function from `utils/model_setup.py` to explain, a sentence of
   `docs/setup-page.md` to rewrite, two README sentences to translate.
4. **Every change is stated.** Only these are made, and each is written into the manifest entry of the file it
   affects:
   - a wait longer than 8 seconds (finding models, a download, a model loading, a long answer) is sped up to about
     4 seconds, and a card before it says, for example, *Downloading, checking and speed-testing the model took
     3 min 12 s. Shown 48x faster.* (`speedup`);
   - in terminal recordings, pauses longer than 2 seconds are shortened to 2 seconds, as asciinema's idle limit does
     (`idle_limit_s`);
   - in terminal recordings, the recording machine's home folder is shown as `~` (`edits`).
5. **Where it was recorded.** Each run records the date, the operating system, CPU, threads, memory and GPU, the
   llama.cpp version and the project commit (`runs` in the manifest). Speeds on screen are that machine's, not a
   promise for yours.
6. **No sound.** The videos have no narration and no audio track.

`tests/test_docs.py` enforces rules 1, 2 and 5, and that each speed-up in rule 4 records what was sped up, its real
length and its factor: every file here must have a complete manifest entry, every entry
must point to a file, pages may show only listed files, and each file must stay under a size limit (GIF 6 MB, MP4
8 MB, PNG 1.5 MB), because every clone of the repository carries every version of every picture.

## What each file is

| Kind | Made by | Notes |
| --- | --- | --- |
| `*.png` | Chromium, at 2x | The browser at 1280 x 800 CSS pixels; terminal frames are drawn by xterm.js |
| `*.mp4` | ffmpeg, H.264 | Plays in browsers and on GitHub; no audio |
| `*.gif` | ffmpeg, one palette per clip | The same clip as the MP4, smaller and looping; for README embeds |
| `*.cast` | `capture.py` | The terminal recording itself, [asciicast v2](https://docs.asciinema.org/manual/asciicast/v2/); plays in asciinema's player |

## Make them again

On Linux or macOS (terminal scenes need a Unix pseudo-terminal), in the project folder:

```bash
npm ci && npx playwright install chromium     # Playwright, Chromium and xterm.js (developer tools only)
python tools/docs-media/capture.py --list     # the scenes, and anything missing to run them
python tools/docs-media/capture.py            # everything, into docs/media/ and manifest.json
python tools/docs-media/capture.py --only serve --model MODEL.gguf   # one scene, with a model from models/
```

It also needs `ffmpeg` with libx264, a real `llama-server` (found where the project looks for it), and a connection
to Hugging Face for the *setup* scene, which downloads the model the setup page recommends for that machine.

| Scene | What it records |
| --- | --- |
| `setup` | The setup page from the first screen to a first reply: use, recommended model, download, speed test, **Start chatting**, llama.cpp's chat |
| `views` | Installed tools, Get llama.cpp, My models, Model radar |
| `detect` | `detect-tools.sh` in a terminal |
| `serve` | `serve.sh` in a terminal (choose the model, then *Tasks*), then the Tasks page: summarize, explain code, rewrite |
| `translate` | `UI=translation serve.sh`, then the Translation page |

A trial run with `--out SOMEWHERE_ELSE` may use the test suite's fake `llama-server`; its files are marked not
publishable and cannot be put here.

### Before you commit new pictures

- **Look at every picture.** The tool never records a host or user name and shows the home folder as `~` in
  terminals, but a browser page can show a path you typed or a model folder outside your home.
- Run `python tests/run.py -k test_docs`.
- Say in the pull request which machine the run was on, so a reviewer knows what the speeds mean.
