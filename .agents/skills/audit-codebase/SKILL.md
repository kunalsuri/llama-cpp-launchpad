---
name: audit-codebase
description: >-
  Use this skill to audit Python code in utils/ against the strict AST security rules
  in tests/test_source_audit.py, ensuring standard library purity, no shell or dynamic code,
  and strict host and subprocess whitelisting.
license: MIT
compatibility: Python 3.9+ (Windows, macOS, Linux)
metadata:
  standard: agentskills.io
---

# Audit Codebase Skill

This skill guides the agent through verifying that any changes made to `utils/*.py` strictly adhere to the project's security and architecture rules.

## When to Use
- Whenever modifying or creating any file in `utils/` (`model_setup.py`, `hardware.py`, `hf_discover.py`, `ui_server.py`, etc.).
- Before completing any task involving runtime Python code.
- When an import error, banned function warning, or test failure occurs in `test_source_audit.py`.

## Audit Procedure

### Step 1: Run the Static AST Audit Test
Execute the source audit test suite directly:

```bash
python -m unittest tests/test_source_audit.py -v
```

### Step 2: Analyze Violations (If Any)

| Failure Type | Root Cause | Remediation |
|--------------|------------|-------------|
| `unexpected import '...'` | An unapproved standard library or third-party package was imported. | Remove third-party imports. Only approved stdlib imports are permitted. If standard library, verify against `ALLOWED_IMPORTS` in `test_source_audit.py`. |
| `calls eval() / exec() / compile()` | Dynamic code execution attempted. | Replace dynamic code with static structures or explicit dictionary lookups. |
| `passes shell=` or calls `os.system` | Shell execution attempted. | Use `subprocess.run(["cmd", "arg"])` with an argument list, never a shell. |
| `run_cmd starts unexpected program '...'` | Subprocess executable not in whitelist. | Whitelist is limited to `nvidia-smi`, `sysctl`, `--list-devices`, `llama-server`, `llama-bench`. Do not invoke external programs. |
| `talks to <host>` | Hardcoded URL to an unwhitelisted domain. | Allowed hosts are only `huggingface.co`, `github.com`, and `127.0.0.1`. |
| `urlopen(...) passes data=` | POST request with body attempted. | `model_setup.py` only performs GET requests for metadata and downloads; outgoing bodies are prohibited. |
| `personal file check` | Probing `.ssh`, `.aws`, `.gnupg`, etc. | Remove code referencing sensitive home directory files. |
| `unexpected deletes` | Prohibited file removal function used. | `shutil.rmtree`, `os.remove`, `unlink`, and `rmdir` are forbidden in `model_setup.py`. |
| `very long line` | Line exceeded 200 characters. | Wrap line under 120-140 characters. |

### Step 3: Verify Clean Test Status
Confirm all 10 audit test cases pass:
```text
test_hardware_report_has_no_identity_and_writes_one_file ... ok
test_http_goes_through_one_function_and_sends_no_personal_data ... ok
test_network_hosts_are_only_huggingface_and_github ... ok
test_no_dynamic_code_or_shell ... ok
test_no_obfuscation ... ok
test_no_reads_of_personal_files ... ok
test_python_standard_library_only ... ok
test_subprocess_only_runs_known_programs_as_lists ... ok
test_there_is_something_to_audit ... ok
test_writes_stay_in_models_dir_and_state_file ... ok
```
