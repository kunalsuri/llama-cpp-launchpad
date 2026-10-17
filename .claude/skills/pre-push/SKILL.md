---
name: pre-push
description: Run the full verification matrix before pushing or declaring work done in this repo - all machine personas, repeat runs, coverage - and report which platforms were not run. Use before git push, opening a PR, or saying a change is finished.
---

# Pre-push check

A passing local run is not enough (rule 11). Run these from the repo root and read the output:

```
python tests/run.py --repeat 3
python tests/run.py --as mac
python tests/run.py --as mac-intel
python tests/run.py --as linux
python tests/run.py --as linux-arm
python tests/run.py --cov --min 85        # needs: pip install coverage
```

Exit code 0 = passed, 1 = a test failed, 2 = nothing ran (never a pass).

Then:

1. Look at `git status` and `git diff`: no stray files (models, `.webui_secret_key`, `.launchpad-state`).
2. After pushing, read CI (`.github/workflows/ci.yml` runs {ubuntu, macos, windows} x {3.10, 3.13}, coverage and the
   personas). Real macOS and Linux are only covered by CI.
3. Report plainly: what passed, what failed, and which platforms were **not** run locally (usually everything except
   the host OS and the `--as` personas). Do not say "done" until CI is read.
