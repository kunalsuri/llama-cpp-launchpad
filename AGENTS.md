# AGENTS.md — llama-cpp-launchpad AI Agent Guide

Welcome, Agent. This document establishes the core architecture, operational constraints, development workflows, and golden rules for working on **`llama-cpp-launchpad`**.

---

## 1. Project Mission & Mental Model

**`llama-cpp-launchpad`** is a zero-friction, cross-platform launcher, recommender, and runner for local LLMs powered by `llama.cpp`'s `llama-server`.

- **Core Mantra**: *"Local AI in one command."*
- **Primary Value**: Hardware-aware model selection, automatic downloading with resume support, speed benchmarking, periodic update discovery from Hugging Face, and turnkey browser UIs.
- **Target Platforms**: Windows (PowerShell 5.1+ / 7), macOS (Bash / .command), and Linux (Bash).
- **Zero Third-Party Runtime Dependencies**: Everything inside `utils/` runs strictly on the **Python standard library** (Python 3.9+). No `pip` dependencies are permitted for the runtime application.

---

## 2. Repository Layout & Architecture

```
llama-cpp-launchpad/
├── AGENTS.md                  # Root agent guide and workspace instructions (this file)
├── README.md                  # End-user documentation
├── requirements.txt           # Developer dependencies only (pytest)
├── LICENSE                    # MIT License
├── .agents/                   # AI-native agent definitions
│   ├── rules/                 # Specialized workspace rules
│   │   ├── security-and-audit.md  # Strict source-audit security constraints
│   │   ├── code-style.md          # Python standard library & cross-platform conventions
│   │   └── testing-standards.md   # Testing, mocking, and coverage rules
│   └── skills/                # Workflow runbooks
│       ├── audit-codebase/    # Static AST security audit runner
│       ├── run-tests/         # Test suite runner & diagnostic workflows
│       ├── manage-catalog/    # Curated models.catalog update & validation workflow
│       ├── hardware-diagnostics/ # Hardware profiling & environment override workflow
│       └── dev-environment/   # Dev venv, setup scripts, and UI dev server
├── models/                    # Target directory for downloaded .gguf models (git-ignored)
│   └── README.md              # Instructions for manual downloads
├── utils/                     # Core runtime modules (STANDARD LIBRARY ONLY)
│   ├── model_setup.py         # Main CLI wizard, download manager, speed test, update checker
│   ├── hardware.py            # Hardware profiling (RAM, CPU, GPU detection & llama.cpp compatibility)
│   ├── hf_discover.py         # Pure-logic Hugging Face Hub model discovery and ranking (offline-capable)
│   ├── ui_server.py           # Localhost HTTP server for setup page (token-authenticated, strict CSP)
│   └── models.catalog         # Curated catalog of battle-tested GGUF models
├── ui/                        # Turnkey web frontends (pure vanilla HTML/CSS/JS, zero build step)
│   ├── setup/index.html       # Web-based model recommendation and download wizard
│   └── translation/index.html # Dedicated translation interface communicating with llama-server
├── scripts/                   # Platform-specific launcher and utility scripts
│   ├── win/                   # Windows PowerShell & Batch scripts (serve.ps1, dev-setup.ps1, etc.)
│   ├── unix/                  # Linux / Unix Bash scripts (serve.sh, model-setup.sh, ui.sh)
│   └── mac/                   # macOS .command double-clickable wrappers
└── tests/                     # Test suite (all tests run offline without GPU/llama.cpp)
    ├── fixtures/              # Mock API responses, meminfo files, and benchmark outputs
    ├── test_hardware.py       # Hardware detection and report file tests
    ├── test_hf_discover.py    # Discovery ranking, quant parsing, and candidate filtering tests
    ├── test_model_setup.py    # CLI wizard, download manager, fit calculator, and update tests
    ├── test_source_audit.py   # AST security audit verifying code invariants
    └── test_ui_server.py      # Localhost server security, token auth, CSP, and route tests
```

---

## 3. The Golden Rules & Non-Negotiable Invariants

Every agent working on this codebase **MUST** uphold these invariants. Any pull request or commit that violates them will fail automated testing (`test_source_audit.py`).

### Rule 1: Python Standard Library Only in `utils/`
- Runtime code in `utils/*.py` **must not** import any package that requires `pip install`.
- Only explicitly whitelisted standard library modules and local modules are permitted:
  - Allowed stdlib: `__future__`, `argparse`, `csv`, `ctypes`, `datetime`, `io`, `json`, `os`, `platform`, `re`, `shutil`, `subprocess`, `sys`, `urllib`, `pathlib`, `winreg`, `http`, `secrets`, `threading`, `webbrowser`.
  - Allowed local modules: `hardware`, `hf_discover`, `ui_server`.
- `requirements.txt` is strictly for development tooling (e.g. `pytest`).

### Rule 2: No Dynamic Code Execution or Raw Shells
- **Banned built-ins**: `eval`, `exec`, `compile`, `__import__`.
- **Banned OS methods**: `os.system`, `os.popen`, `os.startfile`, `os.spawn*`, `os.fork`, `os.exec*`.
- **Subprocess calls**:
  - Must **never** pass `shell=True`.
  - Must **never** pass raw command strings (`subprocess.run("command string")` is banned).
  - Must pass argument lists (`subprocess.run(["cmd", "arg1"])`).
  - Permitted executables in `run_cmd` are strictly whitelisted:
    `{"nvidia-smi", "sysctl", "--list-devices", "llama-server", "llama-bench"}`.

### Rule 3: Network & Privacy Sandbox
- Network access is strictly restricted to:
  - `huggingface.co`
  - `github.com`
  - `127.0.0.1` / `localhost`
- All outgoing HTTP requests must pass through `urllib.request.urlopen`.
- Request headers are strictly restricted to `User-Agent` and `Range` (for resumable downloads).
- **No request bodies**: Sending request bodies (`urlopen(..., data=...)`) is banned to prevent data exfiltration.
- **No personal data collection**: Probing usernames (`getpass`, `getuser`), hostnames (`gethostname`, `platform.node`), or machine IDs is strictly forbidden.
- **No reading personal directories**: Never touch `.ssh`, `.aws`, `.gnupg`, `Cookies`, `Login Data`, `id_rsa`, `.netrc`, `keychain`, `.bash_history`.

### Rule 4: Filesystem Boundaries
- Runtime file writes are strictly confined to:
  - `models/` (downloaded `.gguf` and partial `.part` files)
  - `.launchpad-state` (local state: installed model, speed test results, last check timestamp)
  - `.hardware.env` (hardware profile summary written by `hardware.py`)
- Broad file deletion functions (`shutil.rmtree`, `os.remove`, `unlink`, `rmdir`) are strictly restricted in `model_setup.py` to prevent accidental deletion of user data.

### Rule 5: Pure Logic Separation in `hf_discover.py`
- `utils/hf_discover.py` must remain completely pure: **zero network access, zero file access**.
- It only processes data structures passed to it in-memory. This guarantees deterministic, 100% offline-testable discovery rules.

### Rule 6: Cross-Platform Compatibility & Parity
- Never assume a POSIX shell or Windows PowerShell exclusively. Always maintain parity between `scripts/win/` and `scripts/unix/`.
- Always use `pathlib.Path` or `os.path` for path manipulation. Avoid hardcoded path separators (`/` or `\`).

---

## 4. Key Workflows & Command Reference

### Running the Test Suite
```bash
# Standard unittest (requires zero installed packages, runs anywhere with Python 3)
python -m unittest discover -s tests -v

# Run with pytest (inside dev environment)
pytest tests -v

# On Windows via dev-test script
scripts\win\dev-test.ps1
```

### Running the Source Audit Test
```bash
python -m unittest tests/test_source_audit.py -v
```

### Checking Hardware Profiling
```bash
# Print detected hardware to stdout without modifying files
python utils/hardware.py --print

# Write report to .hardware.env
python utils/hardware.py
```

### Running the Setup UI Dev Server
```bash
# Start server on localhost port 8765 without launching a browser window
python utils/model_setup.py --ui --no-browser --port 8765

# On Windows via PowerShell script
scripts\win\dev-run-ui.ps1 -NoBrowser -Port 8765
```

### Discovering Models on Hugging Face (CLI)
```bash
# Recommend models based on hardware
python utils/model_setup.py --list

# Search Hugging Face Hub with custom parameters (dry run)
python utils/model_setup.py --discover --search coder --list
```

### Environment Variable Overrides
Useful for testing different hardware configurations:
- `LP_RAM_MB`: Override detected system RAM in megabytes (e.g. `LP_RAM_MB=16384`).
- `LP_VRAM_MB`: Override detected GPU VRAM in megabytes (e.g. `LP_VRAM_MB=8192`).
- `LP_GPU_USABLE`: Force GPU usability evaluation (`1` = true, `0` = false).
- `MODELS_DIR`: Override the model directory location.
- `LLAMA_SERVER`: Explicit path to `llama-server` binary.
- `PORT`: HTTP port for `serve` or `ui_server`.

---

## 5. Development Protocols for Agents

When implementing changes or fixing issues in this repository:

1. **Check Invariants First**: Before editing any file in `utils/`, verify that your proposed changes do not introduce third-party imports, shell calls, unwhitelisted subprocess commands, or new external network hosts.
2. **Preserve Compatibility**: Keep CLI flags and environment variables backward-compatible.
3. **Run AST Audit & Test Suite**:
   ```bash
   python -m unittest discover -s tests -v
   ```
4. **Inspect Git Status**: Ensure no temporary test files, caches, or unexpected artifacts are left behind.

---

## 6. Associated Skills & Rules

Detailed guides are located in the `.agents/` directory:
- [security-and-audit.md](file:///c:/Users/ks248120/Documents/GitHub/llama-cpp-launchpad/.agents/rules/security-and-audit.md) — Comprehensive AST security and audit specification.
- [code-style.md](file:///c:/Users/ks248120/Documents/GitHub/llama-cpp-launchpad/.agents/rules/code-style.md) — Coding conventions and styling guidelines.
- [testing-standards.md](file:///c:/Users/ks248120/Documents/GitHub/llama-cpp-launchpad/.agents/rules/testing-standards.md) — Test architecture and mocking conventions.
- Skills in `.agents/skills/`:
  - `audit-codebase`: Step-by-step code audit procedure.
  - `run-tests`: Test runner runbook.
  - `manage-catalog`: Catalog formatting and addition workflow.
  - `hardware-diagnostics`: Hardware profiling and override runbook.
  - `dev-environment`: Development environment setup and troubleshooting.
