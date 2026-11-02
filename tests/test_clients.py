"""Tests for utils/clients.py: what to type into other programs to use the running llama-server.

Formats checked against each program's own documentation (November 2026):
  - Continue: docs/customize/model-providers/more/llamacpp.mdx (provider llama.cpp, apiBase without /v1)
  - aider: aider/website/docs/llms/openai-compat.md (OPENAI_API_BASE, OPENAI_API_KEY, --model openai/<name>)
  - llama-server: "model" is required in router mode and ignored with a single model (tools/server/README.md)
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "utils"))
import clients  # noqa: E402


def by_id(rows):
    return {r["id"]: r for r in rows}


class TestSnippets(unittest.TestCase):
    def test_the_address_key_and_model_name_for_any_openai_compatible_program(self):
        r = by_id(clients.snippets(8080, ["Qwen3-4B-Q4_K_M"], "Linux", lambda n: ""))["openai"]
        self.assertIn("http://127.0.0.1:8080/v1", r["text"])
        self.assertIn("Qwen3-4B-Q4_K_M", r["text"])
        self.assertIn("any text", r["text"])

    def test_open_webui_with_the_docker_address_too(self):
        r = by_id(clients.snippets(9000, ["m"], "Linux", lambda n: ""))["open-webui"]
        self.assertIn("http://127.0.0.1:9000/v1", r["text"])
        self.assertIn("http://host.docker.internal:9000/v1", r["text"])

    def test_continue_config_as_its_docs_give_it(self):
        r = by_id(clients.snippets(8080, ["m-Q4"], "Linux", lambda n: ""))["continue"]
        self.assertEqual(r["kind"], "file")
        self.assertIn("provider: llama.cpp", r["text"])
        self.assertIn("apiBase: http://127.0.0.1:8080\n", r["text"])
        self.assertIn("model: m-Q4", r["text"])
        self.assertIn("schema: v1", r["text"])

    def test_aider_command_only_when_aider_was_found(self):
        """Rule 3: a command is shown only when its program was found, and then in this OS's shell."""
        found = lambda n: "/usr/bin/aider" if n == "aider" else ""      # noqa: E731
        r = by_id(clients.snippets(8080, ["m"], "Linux", found))["aider"]
        self.assertEqual(r["kind"], "cmd")
        self.assertEqual(r["text"], "OPENAI_API_BASE=http://127.0.0.1:8080/v1 OPENAI_API_KEY=sk-local aider --model openai/m")
        r = by_id(clients.snippets(8080, ["m"], "Windows", lambda n: "C:\\aider.exe" if n == "aider" else ""))["aider"]
        self.assertEqual(r["text"], '$env:OPENAI_API_BASE="http://127.0.0.1:8080/v1"; $env:OPENAI_API_KEY="sk-local"; '
                                    'aider --model openai/m')
        r = by_id(clients.snippets(8080, ["m"], "Linux", lambda n: ""))["aider"]
        self.assertEqual(r["kind"], "missing")
        self.assertIn("aider was not found", r["text"])
        self.assertNotIn("--model", r["text"])

    def test_router_mode_names_every_model_and_says_the_name_matters(self):
        rows = by_id(clients.snippets(8080, ["alpha", "beta"], "Linux", lambda n: ""))
        self.assertIn("alpha", rows["openai"]["text"])
        self.assertIn("beta", rows["openai"]["text"])
        self.assertIn("names the model", rows["openai"]["note"])
        single = by_id(clients.snippets(8080, ["alpha"], "Linux", lambda n: ""))
        self.assertIn("any name", single["openai"]["note"])


if __name__ == "__main__":
    unittest.main()
