# Testing Standards & Guidelines

This rule outlines testing principles, test execution practices, and mocking strategies for `llama-cpp-launchpad`.

---

## 1. Offline & Environment Independence

- **Zero External Prerequisites**:
  Tests must execute successfully on minimal environments without requiring:
  - An installed `llama-server` or `llama-bench` binary
  - A dedicated GPU or CUDA drivers
  - An active internet connection
- **Execution Speed**:
  The full suite of 115+ tests should execute in under 60 seconds on any modern machine.

---

## 2. Test Execution Commands

```bash
# Full test suite via unittest (always available with standard Python)
python -m unittest discover -s tests -v

# Run a specific test module
python -m unittest tests/test_model_setup.py -v

# Run the source security audit
python -m unittest tests/test_source_audit.py -v

# Run with pytest (when dev venv is active)
pytest tests -v
```

---

## 3. Mocking & Fixture Best Practices

- **Network Mocking**:
  - Never allow tests to make actual HTTP requests to Hugging Face or GitHub.
  - Patch `urllib.request.urlopen` or helper functions in `model_setup.py`:
    ```python
    with mock.patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = io.BytesIO(b'{"key": "value"}')
        # test code
    ```
- **Subprocess & Hardware Mocking**:
  - Mock `subprocess.run` or `run_cmd` to return controlled command output (e.g. `nvidia-smi` outputs or `llama-server --list-devices`).
  - Use `tests/fixtures/` for real or synthesized tool output samples (e.g. `bench.csv`, `hf_list.json`).
- **Temporary Directories & State Isolation**:
  - Always write temporary test files into a directory created with `tempfile.mkdtemp()` or `tempfile.TemporaryDirectory()`.
  - Always register cleanup using `self.addCleanup(shutil.rmtree, temp_dir, True)`.
  - Clean up environment variables by patching `os.environ` via `mock.patch.dict(os.environ, {...})`.

---

## 4. Test Verification Checklist

Before completing any task:
1. `python -m unittest discover -s tests -v` passes with 0 failures and 0 errors.
2. `test_source_audit.py` passes completely.
3. No lingering temporary files (`.part`, `.tmp`, `.launchpad-state`) left in the workspace root or `models/`.
