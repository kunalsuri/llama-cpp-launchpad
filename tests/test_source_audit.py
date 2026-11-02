"""Audit tests: they read the source of utils/*.py and fail if it does anything a reviewer would not expect.

The point is that anyone can verify model_setup.py: standard library only, no shell, no dynamic code,
network only to Hugging Face, and no reads of personal files.
Run: python3 -m unittest discover -s tests -v
"""
import ast
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

UTILS = Path(__file__).resolve().parent.parent / "utils"
SOURCES = sorted(UTILS.glob("*.py"))

# Everything the script may import. All of it ships with Python; nothing is installed with pip.
ALLOWED_IMPORTS = {"__future__", "argparse", "csv", "ctypes", "datetime", "io", "json", "os", "platform",
                   "re", "shutil", "subprocess", "sys", "urllib", "pathlib", "winreg",
                   "http", "secrets", "threading", "webbrowser",     # ui_server.py: the localhost-only setup page
                   "glob", "importlib",   # detect_tools.py: file-system globbing and installed-package metadata (read-only)
                   "collections", "shlex", "time",   # chat_server.py: in-memory log, quoting the shown command, polling
                   "hashlib", "tarfile", "zipfile",  # llama_install.py: SHA-256 check, unpacking release archives
                   "struct",                         # gguf.py: decoding a model file's binary header
                   "hardware", "hf_discover", "ui_server", "detect_tools", "hf_radar", "model_setup",
                   "chat_server", "llama_install", "gguf"}      # local modules
LOCAL_MODULES = {p.stem for p in SOURCES}
# 127.0.0.1 = the setup page itself (ui_server.py); api.github.com = the llama.cpp release listing (llama_install.py)
ALLOWED_HOSTS = {"huggingface.co", "github.com", "api.github.com", "127.0.0.1"}
# The only programs the script may start (always as an argument list, never through a shell).
ALLOWED_PROGRAMS = {"nvidia-smi", "sysctl", "--list-devices", "llama-server", "llama-bench"}


def trees():
    for path in SOURCES:
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


class TestSourceAudit(unittest.TestCase):
    def test_there_is_something_to_audit(self):
        self.assertTrue(any(p.name == "model_setup.py" for p in SOURCES))

    def test_python_standard_library_only(self):
        stdlib = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else None
        for path, tree in trees():
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""]
                for m in mods:
                    top = m.split(".")[0]
                    self.assertIn(top, ALLOWED_IMPORTS, f"{path.name}: unexpected import '{m}'")
                    if stdlib and top not in LOCAL_MODULES:
                        self.assertIn(top, stdlib, f"{path.name}: '{m}' is not in the standard library")

    def test_no_dynamic_code_or_shell(self):
        banned_builtins = {"eval", "exec", "compile", "__import__"}          # as bare names: dynamic code
        banned_os = {"system", "popen", "startfile", "spawnl", "spawnv", "spawnlp", "spawnvp", "fork", "execv", "execl"}
        for path, tree in trees():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                if isinstance(f, ast.Name):
                    self.assertNotIn(f.id, banned_builtins, f"{path.name}:{node.lineno} calls {f.id}()")
                elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "os":
                    self.assertNotIn(f.attr, banned_os, f"{path.name}:{node.lineno} calls os.{f.attr}()")
                for kw in node.keywords:
                    self.assertNotEqual(kw.arg, "shell", f"{path.name}:{node.lineno} passes shell=")
            text = path.read_text(encoding="utf-8")
            for banned in ("pickle", "marshal", "base64", "socket", "ftplib", "smtplib", "telnetlib"):
                self.assertNotRegex(text, rf"(?m)^\s*(import|from)\s+{banned}\b", f"{path.name} imports {banned}")

    def test_subprocess_only_runs_known_programs_as_lists(self):
        for path, tree in trees():
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("run", "Popen", "call", "check_output")
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"):
                    self.assertTrue(node.args and not isinstance(node.args[0], ast.Constant),
                                    f"{path.name}:{node.lineno} subprocess must take an argument list, not a string")
        for path in SOURCES:
            text = path.read_text(encoding="utf-8")
            for call in re.findall(r'run_cmd\(\[\s*"([^"]+)"', text):
                self.assertIn(call, ALLOWED_PROGRAMS, f"{path.name}: run_cmd starts unexpected program {call!r}")

    def test_network_hosts_are_only_huggingface_and_github(self):
        for path, tree in trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    for url in re.findall(r"https?://[^\s\"')]+", node.value):
                        host = urlparse(url).hostname
                        self.assertIn(host, ALLOWED_HOSTS, f"{path.name}:{node.lineno} talks to {host}")

    def test_http_goes_through_one_function_and_sends_no_personal_data(self):
        text = (UTILS / "model_setup.py").read_text(encoding="utf-8")
        self.assertEqual(text.count("urllib.request.urlopen("), 3,
                         "only http_get, fetch_file and http_open (the first megabytes of a model file) touch the network")
        # request headers are limited to a fixed user-agent and (for resume) a Range header
        headers = set(re.findall(r'headers\[?\s*[\"\']?(?:\[)?"(\w[\w-]*)"', text)) | set(re.findall(r'"(User-Agent|Range)"', text))
        self.assertTrue(headers <= {"User-Agent", "Range"}, headers)
        self.assertNotRegex(text, r"(getpass|gethostname|getlogin|node\(\)|platform\.(node|uname)|os\.environ\.copy)")
        self.assertNotRegex(text, r"urlopen\([^)]*data=", "no request bodies are sent")

    def test_no_reads_of_personal_files(self):
        for path in SOURCES:
            text = path.read_text(encoding="utf-8")
            for needle in (".ssh", ".aws", ".gnupg", "Cookies", "Login Data", "id_rsa", ".netrc", "keychain", ".bash_history"):
                self.assertNotIn(needle, text, path.name)

    def test_hardware_report_has_no_identity_and_writes_one_file(self):
        text = (UTILS / "hardware.py").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(getpass|gethostname|getlogin|node\(\)|platform\.(node|uname)|os\.environ\.copy|getnode|socket)")
        self.assertEqual(re.findall(r"(write_text|write_bytes|os\.replace|shutil\.(?:move|copy|rmtree)|unlink|os\.remove)", text),
                         ["write_text", "os.replace"], "hardware.py writes only its report file")
        self.assertIn('REPORT_NAME = ".hardware.env"', text)

    def test_writes_stay_in_models_dir_and_state_file(self):
        text = (UTILS / "model_setup.py").read_text(encoding="utf-8")
        writers = re.findall(r"(write_text|write_bytes|open\([^)]*[\"'][wa]b?[\"']|os\.replace|shutil\.(move|copy|rmtree)|os\.remove|unlink|rmdir)", text)
        found = {w[0].split("(")[0] for w in writers}
        self.assertFalse({"shutil.rmtree", "os.remove", "unlink", "rmdir"} & found, f"unexpected deletes: {found}")

    def test_chat_server_runs_only_llama_server_and_port_lookups_and_writes_nothing(self):
        """chat_server.py starts the llama-server it was given, and asks the OS's own tools who holds a busy port.
        It keeps the server's output in memory: no files are written."""
        text = (UTILS / "chat_server.py").read_text(encoding="utf-8")
        self.assertEqual(set(re.findall(r'which\("([^"]+)"\)', text)), {"lsof", "ss", "netstat", "tasklist"})
        self.assertEqual(text.count("subprocess.Popen("), 1, "one place starts a process: llama-server")
        writes = re.findall(r"(write_text|write_bytes|\bopen\(|os\.replace|shutil\.(?:move|copy|rmtree)|unlink|os\.remove)", text)
        self.assertEqual(writes, [], "chat_server.py writes no files")
        self.assertNotRegex(text, r"https?://(?!127\.0\.0\.1)", "talks only to localhost")

    def test_llama_install_talks_only_to_ggml_org_releases_and_writes_only_into_bin(self):
        """llama_install.py is the one module that installs a program. It may: read the ggml-org/llama.cpp release
        listing, download that release's archives (redirects only to GitHub hosts), unpack them into the project's
        bin/ through a staging folder inside bin/, run `llama-server --version` and `brew install llama.cpp`."""
        text = (UTILS / "llama_install.py").read_text(encoding="utf-8")
        self.assertIn('REPO = "ggml-org/llama.cpp"', text)
        self.assertIn('LATEST_RELEASE = f"https://api.github.com/repos/{REPO}/releases/latest"', text)
        self.assertIn('DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"', text)
        self.assertEqual(text.count("opener.open("), 1, "one place opens network connections")
        self.assertNotIn("urlopen(", text)
        self.assertIn("build_opener(_GitHubOnly)", text, "every request refuses redirects away from GitHub")
        self.assertIn('BREW_CMD = ["install", "llama.cpp"]', text)
        self.assertEqual(re.findall(r"shutil\.rmtree\(([^,)]*)", text), ["self.staging", "self.staging"],
                         "the only folder ever deleted is the staging folder inside bin/")
        self.assertIn("return self.bin / STAGING", text)
        self.assertEqual(re.findall(r"os\.replace\(([^)]*)\)", text), ["src, target"])
        self.assertIn("target = self.bin.joinpath(", text, "files are only moved into bin/")
        self.assertNotRegex(text, r"(unlink|os\.remove|rmdir|sudo|runas|Program Files|/usr/local)")

    def test_gguf_reader_only_reads(self):
        """gguf.py decodes model headers. It opens files for reading only, writes nothing, runs nothing and has no
        network code of its own (model_setup.py fetches remote headers and hands it the stream)."""
        text = (UTILS / "gguf.py").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"open\(([^)]*)\)", text), ['path, "rb"'])
        self.assertNotRegex(text, r"(write_text|write_bytes|os\.replace|shutil|unlink|os\.remove|rmdir|subprocess"
                                  r"|urllib|http\.client|run_cmd)")

    def test_no_obfuscation(self):
        for path in SOURCES:
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\\x[0-9a-fA-F]{2}\\x[0-9a-fA-F]{2}\\x[0-9a-fA-F]{2}", f"{path.name}: hex-escaped strings")
            self.assertFalse(any(len(line) > 200 for line in text.splitlines()), f"{path.name}: very long line (obfuscation?)")
            self.assertNotIn("\x00", text)


if __name__ == "__main__":
    unittest.main()
