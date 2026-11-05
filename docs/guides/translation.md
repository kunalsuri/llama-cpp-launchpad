# Translate text: the Translation interface

A translator answered by the model running on your computer. It is one HTML file (`ui/translation/index.html`) that
`llama-server` serves. Back to the [documentation home](../README.md).

> **Screenshots and video:** not recorded yet; see [How the pictures are made](../media/README.md).

## Open it

Start `serve` and choose *Translation* in the interface menu, or skip the menu:

```bash
UI=translation ./scripts/unix/serve.sh            # Linux, macOS
```

```powershell
$env:UI = "translation"; scripts\win\serve.bat    # Windows PowerShell
```

It opens at `http://localhost:8080` (or your `PORT`), with an example sentence in the box so you can try it at once.
For the menus and settings see [Run a model from the terminal](serve.md). On the setup page, *Translation* as the use
picks a model suited to it.

## Use it

1. Choose the languages under the box. *From* can be *Detect language*; *To* is one of 24 languages. The swap button
   between them exchanges the two (from *Detect language*, it sets *From* to the current *To* language and *To* to
   English, or to Spanish when that was English).
2. Type or paste the text. **Enter** translates; **Shift+Enter** starts a new line.
3. The translation appears under your text as it is written, with the language pair, then the number of tokens, the
   time and the speed (t/s). Under each translation, **Copy translation** copies it and **Translate again** translates
   the same text with the languages and settings now chosen.
4. Translations stay on the page, one under another, until you press **New translation** (the pencil button in the
   side bar), which also puts every setting back to its default.

The 24 languages: English, Spanish, French, German, Italian, Portuguese, Dutch, Russian, Ukrainian, Polish, Turkish,
Arabic, Hebrew, Hindi, Bengali, Urdu, Chinese, Japanese, Korean, Vietnamese, Thai, Indonesian, Swedish and Greek.

## Settings

| Setting | Where | Choices | Default |
| --- | --- | --- | --- |
| French form of address | next to the languages, only when *To* is French | *Formal (vous)*, *Normal (tu)* | *Formal (vous)* |
| Tone | **Settings** (the gear button in the side bar) | *Neutral*, *Formal*, *Casual* | *Neutral* |
| Temperature | **Settings** | 0 to 1, in steps of 0.1 | 0.2 |

Into French, the vous/tu choice decides the register and *Tone* is not used. A lower temperature gives steadier,
more literal translations; a higher one, more varied wording.

## How good is it?

That depends on the model, not on this page. As a rough guide, small models (around 1B parameters) translate
roughly; 4B and up do much better. The page tells the model to output only the translation, with no notes; it cannot
check that the translation is right. For anything that matters, have it checked by someone who reads both languages.

## Privacy

The text goes only to the `llama-server` that serves the page, on this computer. The page loads nothing from the
internet.
