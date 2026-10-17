# Rules for working in this repo

Run the tests: `python tests/run.py` (also `--repeat 3`, `--cov --min 85`). Details in `tests/README.md`.

## Rules (each one exists because it caused a real bug in PR #1)

1. **Test first.** Write the test, watch it fail for the right reason, then fix. Bug fix = a test that reproduces the bug.
2. **Tests must not depend on the machine running them.** Pin platform, chip, env vars and PATH (`tests/fakes.py`,
   `mock.patch`). A test that passes only on Windows or only on x86 is a broken test. (macOS CI failed because tests
   picked up the Apple Silicon runner.) Enforced by `python tests/run.py --as mac|mac-intel|linux|linux-arm`, which
   pretends to be that machine; CI runs all of them. Run `--as mac` before pushing.
3. **"Installed" is not "can run".** Never show a command, button or claim unless the exact program it needs was found.
   Say what is missing instead.
4. **State machines need scenario tests, not string checks.** For UI with polling or several screens, test the real
   script with `tests/page_harness.js`: open screen, wait, click Back. Grepping the HTML proves nothing.
5. **Log misses as well as hits.** Anything that searches must record where it looked and found nothing.
6. **Never rebuild arguments by guessing how the user typed them.** Use parsed values (`--min 85` and `--min=85`).
7. **Launchers keep the tool's exit status.** Save `$?` / `%errorlevel%` before any pause or cleanup, then return it.
    Enforced: `test_harness.TestLauncherExitStatus` checks every script ends with `exec` / `exit` and runs the real
    launchers to see the exit code arrive.
8. **Read request bodies before refusing a request**, or clients get a connection reset instead of the error.
9. **Test servers write in small chunks (64 KB).** One huge write stalls and resets on Windows loopback.
10. **Do not write Python or code through shell heredocs.** Escapes (`\n`, `\w`, `\x1b`) get eaten. Use the Write or
    Edit tools. Run with strict warnings (`tests/run.py` does) so bad escapes fail loudly.
11. **A passing local run is not enough.** Windows and WSL passing does not cover macOS. Push and read CI before saying
    "done"; say plainly which platforms were not run.
12. **Keep `utils/` standard library only and read-only unless a test and the audit allow more**
    (`tests/test_source_audit.py`).
