---
name: run-tests
description: >-
  Use this skill when running the full test suite or targeted test modules for
  llama-cpp-launchpad, debugging test failures, or validating changes across hardware
  detection, discovery, setup, and UI server components.
license: MIT
compatibility: Python 3.9+ (Windows, macOS, Linux)
metadata:
  standard: agentskills.io
---

# Run Tests Skill

This skill provides the standard runbook for executing, filtering, and debugging tests in `llama-cpp-launchpad`.

## Test Suite Overview

The repository contains 118+ automated unit tests that run entirely offline without needing a GPU, live internet access, or `llama-server`.

| Test File | Focus Area |
|-----------|------------|
| `tests/test_source_audit.py` | AST static security audit enforcing stdlib-only, no shell, safe subprocesses |
| `tests/test_hardware.py` | Hardware profiling, `.hardware.env` generation, and privacy invariants |
| `tests/test_hf_discover.py` | Hugging Face metadata parsing, quant bit sizing, MoE parameters, candidate ranking |
| `tests/test_model_setup.py` | CLI options, download resumption, memory fit calculations, and update prompts |
| `tests/test_ui_server.py` | Localhost HTTP server, token authentication, CSP headers, and download API |

---

## Execution Procedures

### 1. Run the Complete Suite
Using Python's built-in `unittest` runner:
```bash
python -m unittest discover -s tests -v
```

On Windows with PowerShell (using the project virtual environment):
```powershell
scripts\win\dev-test.ps1
```

Using `pytest` (if dev dependencies installed):
```bash
pytest tests -v
```

### 2. Run a Single Test Module
```bash
python -m unittest tests/test_hardware.py -v
python -m unittest tests/test_hf_discover.py -v
python -m unittest tests/test_model_setup.py -v
python -m unittest tests/test_ui_server.py -v
python -m unittest tests/test_source_audit.py -v
```

### 3. Run a Specific Test Case or Method
```bash
python -m unittest tests.test_model_setup.TestFit.test_speed_estimates -v
python -m unittest tests.test_ui_server.TestGuards.test_post_needs_the_token -v
```

---

## Troubleshooting Test Failures

1. **Linux `/proc/meminfo` test skipped on Windows**:
   - `test_linux_detection_and_gpu` is expected to skip when running on Windows or macOS. This is normal.
2. **Mocking leaks or unstopped patches**:
   - Always ensure `unittest.mock.patch` objects are registered with `self.addCleanup(patcher.stop)` or used in context managers.
3. **Environment pollution**:
   - Check if environment variables like `LP_RAM_MB` or `LLAMA_SERVER` are overriding expected test behavior. Use `mock.patch.dict(os.environ, ...)` in tests.
4. **Temporary file residue**:
   - If tests fail with disk or file errors, inspect the temporary directories created during test setup.
