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
