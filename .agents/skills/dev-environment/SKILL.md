---
name: dev-environment
description: >-
  Use this skill to set up or verify the local development environment, manage
  Python virtual environments, audit dependencies against requirements.txt, or run the
  local setup UI dev server.
license: MIT
compatibility: Python 3.9+ (Windows, macOS, Linux)
metadata:
  standard: agentskills.io
---

# Dev Environment Skill

This skill guides the agent through setting up, inspecting, and managing the development environment for `llama-cpp-launchpad`.

---

## 1. Setting Up on Windows (PowerShell)

The script `scripts/win/dev-setup.ps1` handles end-to-end setup:
1. Detects Python (version 3.10+ required for pytest).
2. Creates `.venv` in the project root if missing.
3. Installs `requirements.txt` into `.venv`.
4. Detects `llama.cpp`, `Ollama`, and `LM Studio` runtimes.
5. Performs a dependency audit comparing project imports against `requirements.txt`.
6. Generates `.system.env` and runs `hardware.py` to produce `.hardware.env`.

### Common Commands:
```powershell
# Standard setup run
scripts\win\dev-setup.ps1

# Append third-party imports missing from requirements.txt
scripts\win\dev-setup.ps1 -Fix

# Force recreation of the virtual environment
scripts\win\dev-setup.ps1 -Recreate
```

---

## 2. Setting Up on Linux / macOS (Bash)

Since the core app uses Python standard library only, setting up for development requires only a standard venv with dev dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 3. Running the Setup UI Dev Server

To test and develop the browser-based setup interface (`ui/setup/index.html`):

```bash
# Python direct invocation
python utils/model_setup.py --ui --no-browser --port 8765

# Windows PowerShell helper
scripts\win\dev-run-ui.ps1 -Port 8765 -NoBrowser
```

Key UI Server Properties:
- Listens strictly on `127.0.0.1`.
- Requests with non-localhost `Host` headers are rejected with 403 Forbidden.
- Actions requiring modifications (`/api/install`) require the `X-LP-Token` security token generated per session.
- Serves static assets with strict Content Security Policy.
