# Code Style & Engineering Standards

This rule outlines the code style, typing, and engineering patterns used throughout `llama-cpp-launchpad`.

---

## 1. Python Style & Conventions

- **Python Version**: Minimum Python 3.9. Use `from __future__ import annotations` at the top of Python files.
- **Standard Library Idioms**:
  - Prefer `pathlib.Path` for path resolution, manipulation, reading, and writing.
  - Always specify encoding when opening or reading text: `path.read_text(encoding="utf-8")` or `open(..., encoding="utf-8")`.
  - Use `subprocess.run(["program", "arg1"], capture_output=True, text=True, timeout=...)` with explicit timeouts.
  - Never use `shell=True` in subprocess calls.
- **Typing**:
  - Use standard type hints: `dict`, `list`, `set`, `tuple`, `str | None`.
  - Annotate public function signatures and return types.
- **Graceful Degradation**:
  - Hardware detection must never crash on unusual or constrained systems; catch OS/hardware query exceptions and return safe defaults (e.g. 0 MB RAM, 1 CPU core, `none` GPU).
  - Terminal coloring should automatically disable if output is redirected or if `NO_COLOR` environment variable is set.

---

## 2. Cross-Platform Parity

- **Dual-Script Architecture**:
  - Launchpad maintains feature parity across Windows, macOS, and Linux.
  - When a feature, environment variable, or flag is added to `scripts/win/serve.ps1` (or `model-setup.bat`), reflect the equivalent behavior in `scripts/unix/serve.sh` and `scripts/mac/serve.command`.
- **Path Portability**:
  - Never hardcode backslashes (`\`) in cross-platform Python code; use `Path` division operator (`Path(__file__).resolve().parent / "models"`).
  - PowerShell scripts should use `Join-Path` or forward slashes where appropriate.

---

## 3. Web Frontend Standards (`ui/`)

- **Vanilla HTML / CSS / JS**:
  - No build systems, no npm bundling, no external framework runtime dependencies.
  - Single-file self-contained delivery (`index.html`) per UI interface.
- **Design System & Aesthetics**:
  - Use CSS custom properties with `oklch()` color tokens consistent with `llama.cpp`'s native web chat UI.
  - Support automatic dark mode via `@media (prefers-color-scheme: dark)`.
  - Include responsive layouts, micro-animations, accessible keyboard focus indicators (`:focus-visible`), and clean SVGs for icons.
- **Security & Content Security Policy (CSP)**:
  - Any server-rendered UI served by `ui_server.py` must obey the strict CSP (`default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'`).
  - Never load scripts, fonts, or assets from external CDNs.
