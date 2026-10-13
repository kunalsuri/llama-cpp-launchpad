# Security & Source Audit Rules

This rule defines the critical security invariants enforced by `tests/test_source_audit.py`.
Any modification to `utils/*.py` is subjected to static AST parsing during the test run.
Violations cause immediate test failures.

---

## 1. Import Constraints

- **Rule**: All runtime code in `utils/*.py` must be Python Standard Library only.
- **Allowed Stdlib Imports**:
  `__future__`, `argparse`, `csv`, `ctypes`, `datetime`, `io`, `json`, `os`, `platform`, `re`, `shutil`, `subprocess`, `sys`, `urllib`, `pathlib`, `winreg`, `http`, `secrets`, `threading`, `webbrowser`.
- **Allowed Local Modules**:
  `hardware`, `hf_discover`, `ui_server`.
- **Prohibited Modules**:
  Do **NOT** import `requests`, `numpy`, `torch`, `huggingface_hub`, `psutil`, `aiohttp`, `fastapi`, `pydantic`, or any other third-party packages.
  Do **NOT** import banned standard library modules: `pickle`, `marshal`, `base64`, `socket` (except inside stdlib http.server), `ftplib`, `smtplib`, `telnetlib`.

---

## 2. Dynamic Code & Shell Execution Constraints

- **Banned Built-ins**:
  Never call `eval()`, `exec()`, `compile()`, or `__import__()`.
- **Banned OS Execution**:
  Never call `os.system()`, `os.popen()`, `os.startfile()`, `os.spawn*()`, `os.fork()`, `os.exec*()`.
- **Subprocess Invocation**:
  - Never pass `shell=True` as a keyword argument to any function.
  - Subprocess calls must take an argument list (e.g. `['llama-server', '--version']`), **never** a string.
  - Programs executed via `run_cmd` must be in the `ALLOWED_PROGRAMS` whitelist:
    `{"nvidia-smi", "sysctl", "--list-devices", "llama-server", "llama-bench"}`.

---

## 3. Network & Host Restrictions

- **Permitted Network Hosts**:
  Only `huggingface.co`, `github.com`, and `127.0.0.1` (localhost).
- **HTTP Transport Function**:
  - Network calls must strictly pass through `urllib.request.urlopen`.
  - Allowed request headers are restricted to `User-Agent` and `Range` (for download chunk resume).
  - No request bodies: `urlopen(..., data=...)` is forbidden.
- **No Personal Identifiers in Network or State**:
  The code must not call `getpass()`, `gethostname()`, `getlogin()`, `platform.node()`, `platform.uname()`, `os.environ.copy()`, or `uuid.getnode()`.

---

## 4. Privacy & Filesystem Boundary Invariants

- **Personal Directory Access**:
  Code must never inspect or access personal configuration directories:
  `.ssh`, `.aws`, `.gnupg`, `Cookies`, `Login Data`, `id_rsa`, `.netrc`, `keychain`, `.bash_history`.
- **Filesystem Modification**:
  - `model_setup.py` may only write to `models/` directory and `.launchpad-state`.
  - `hardware.py` may only write `.hardware.env`.
  - Broad destructive filesystem operations (`shutil.rmtree`, `os.remove`, `unlink`, `rmdir`) are forbidden in `model_setup.py`.

---

## 5. Code Obfuscation Prevention

- No hex-escaped bytecode strings (`\x00`, `\x2f\x2e`).
- Maximum line length is capped at 200 characters.
- No null bytes (`\x00`) in source files.
