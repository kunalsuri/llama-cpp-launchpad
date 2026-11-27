# Summarize, explain code, rewrite: the Tasks interface

A page for three everyday jobs, answered by the model running on your computer: **Summarize** a text, **Explain code**,
**Rewrite** a draft. It is one HTML file (`ui/tasks/index.html`) that `llama-server` serves. Back to the
[documentation home](../README.md).

> **Screenshots and video:** not recorded yet; see [How the pictures are made](../media/README.md).

## Open it

Start `serve` and choose *Tasks* in the interface menu, or skip the menu:

```bash
UI=tasks ./scripts/unix/serve.sh            # Linux, macOS
```

```powershell
$env:UI = "tasks"; scripts\win\serve.bat    # Windows PowerShell
```

The page opens at `http://localhost:8080` (or your `PORT`). The model's name is shown at the top right. See
[Run a model from the terminal](serve.md) for the menus and settings.

## Use it

1. Choose a task: **Summarize**, **Explain code** or **Rewrite**. The line under the tabs says what it does.
2. Paste your text or code into the box.
3. Pick the option next to it:

   | Task | Option | Choices |
   | --- | --- | --- |
   | Summarize | *Length* | *A few bullet points*, *One paragraph*, *Detailed, by section* |
   | Explain code | *For* | *A beginner*, *A developer* |
   | Rewrite | *Tone* | *Plainer and clearer*, *More formal*, *Friendlier*, *Shorter* |

4. Press **Run**, or **Ctrl+Enter** (**⌘+Enter** on a Mac). The answer appears as it is written; **Run** becomes
   **Stop** until it is done.
5. Under the answer: how many tokens it wrote, how long it took and the speed in tokens per second, measured in your
   browser for this answer. **Copy** copies the answer.

## Open a file

Instead of pasting, press **Open file** (next to the option) and pick a text or code file, or drag a file onto the
box. The file is read by your browser and its text goes into the box; nothing is uploaded anywhere except the normal
request to the local model when you press **Run**. You can still edit the text before running.

- The picker offers `.txt`, `.md` and common code files (`.py`, `.js`, `.ts`, `.c`, `.cpp`, `.java`, `.go`, `.rs`,
  `.json`, `.yaml`, `.html`, `.css`, `.sh` and a few more). Any other file that is plain UTF-8 text opens too.
- The name of the file you opened is shown under the box. For **Explain code**, a known extension tells the model the
  language ("Python" for `.py`); pasted code carries no such hint.
- A file over **1 MB**, or one that looks binary (an image, a program, a zip), is not opened. The message under the box
  names the file and the reason, and your text stays as it was.
- If you drop several files, only the first is opened, and the message says so.

## History

Under the answer, **History** lists your last 20 finished results. Each item shows the task, its option, the time and
the start of your text.

- Click an item to put its task, option, text and answer back on the page.
- The bin button deletes one item; **Clear history** deletes them all (there is no undo).
- Only finished answers are saved: a request that failed or that you stopped is not.
- Text longer than 2,000 characters is saved shortened (restoring it says so).

History lives in this browser's own storage (`localStorage`) and nowhere else: it is not sent to the model or any
server, it stays after you close the page, and another browser or another computer does not see it. If the browser
will not store it (private mode, or storage switched off), the page says so and keeps the items only until you close or
reload the page.

## What the model is asked

The page sends your text with an instruction for the task (`TASKS` in `ui/tasks/index.html`). In short:

- **Summarize**: use only what the text says and never add facts; answer in the language of the text; output only
  the summary.
- **Explain code**: say what the code does, walk through it step by step, then list anything that looks like a bug or
  a risk ("None found" if there is nothing). For a beginner it is told to avoid jargon and explain every term.
- **Rewrite**: keep the meaning and add no information; keep the language of the text; output only the rewritten text.

An instruction is not a guarantee. A small model can still leave out a point, add one, or miss a bug, so check an
answer before you rely on it, especially a summary of something important.

## Privacy

The text goes only to the `llama-server` that serves the page, on this computer. The page loads nothing from the
internet.
