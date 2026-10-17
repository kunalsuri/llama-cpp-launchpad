---
name: test-first
description: Make a change in this repo the way CLAUDE.md requires - red, green, refactor with tests/run.py. Use when adding a feature, fixing a bug, or touching utils/, scripts/ or ui/.
---

# Test-first change

Follow this loop. The rules referenced are the numbered rules in `CLAUDE.md`.

1. **Find the test file.** Every `utils/<name>.py` has `tests/test_<name>.py`. Page behaviour is tested with
   `tests/page_harness.js`, not by grepping the HTML (rule 4).
2. **Red.** Write the test first. For a bug, it must reproduce the bug. Run
   `python tests/run.py -k <part of the test name>` and confirm it fails *for the right reason* (rule 1).
   A test that passes on its first run proves nothing: say so if one does.
3. **Pin the machine** (rule 2). Use `tests/fakes.py` (`FakeProbe`) and `mock.patch` for platform, chip, env and PATH.
   Never depend on the host.
4. **Green.** Write the least code that passes. Keep `utils/` standard library only and read-only (rule 12).
   Write Python with the Write/Edit tools, never shell heredocs (rule 10).
5. **Refactor** with the tests green.
6. **Verify** with the `pre-push` skill before saying "done".

Do not rebuild CLI arguments by guessing how the user typed them (rule 6). Anything that searches must log misses as
well as hits (rule 5). Never show a command or button unless the exact program it needs was found (rule 3).
