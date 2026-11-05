# llama-cpp-launchpad documentation

Run a language model on your own computer with [llama.cpp](https://github.com/ggml-org/llama.cpp), from a page in your
browser or from a terminal. These pages explain how, one task at a time. The project's [README](../README.md) is the
one-page summary; this folder goes further.

## Start here

| If you want to… | Read |
| --- | --- |
| Go from nothing to a first reply, on Windows, macOS or Linux | [Getting started](getting-started.md) |
| Know what every screen of the setup page does and checks | [The setup page: full reference](setup-page.md) |

## Guides

Each guide does one thing, from start to finish.

| Guide | What you get |
| --- | --- |
| [Run a model from the terminal](guides/serve.md) | The `serve` menus, every setting, and running it from a script |
| [Summarize, explain code, rewrite](guides/tasks.md) | The **Tasks** interface |
| [Translate text](guides/translation.md) | The **Translation** interface |
| [Use the model from other programs](guides/other-programs.md) | The values to paste into any OpenAI-API program, Continue and aider |
| [Using Open WebUI](open-webui.md) | Conversation history, documents and web search on top of your model |

## Pictures and videos

Screenshots, GIFs and videos in these pages are made by a script from the real program: a real llama.cpp and a real
model, on a machine that is named under each picture. Nothing is mocked up or retouched. A long wait (a download) is
sped up, and the video says so with a card. [How the pictures are made](media/README.md) lists the rules and how to
make them again.

## For contributors

- [Developer notes](notes.md): Windows virtual environment, running the tests, the radar dashboard.
- The rules for code in this project are in [CLAUDE.md](../CLAUDE.md) and the test workflow in
  [tests/README.md](../tests/README.md).

### Writing these pages

- **Say only what the program does.** Check each claim against the code or by running it, and name the file when a
  reader may want to check too. When behaviour differs by operating system, say which.
- **One task per guide**, in the order a person does it. Start with what is needed; end with what to do when it fails.
- **Name things as the screen names them**: **Start chatting**, **Open the chat**, *General chat*. Buttons in bold,
  menu items and options in italics, commands and files in `code`.
- **Commands for every OS** the step applies to: `scripts\win\…` for Windows, `./scripts/unix/…` for Linux and macOS.
- **Pictures come from `tools/docs-media/capture.py`** only, and only files listed in
  [media/manifest.json](media/manifest.json) may appear on a page. `tests/test_docs.py` checks this, and that every
  link and `#anchor` in these pages resolves.
