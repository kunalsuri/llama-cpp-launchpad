"""llama-cpp-launchpad: what to type into other programs to use the llama-server the setup page is running.

Each entry is checked against that program's own documentation (November 2026):
  - any OpenAI-compatible program: base URL http://127.0.0.1:PORT/v1. llama-server checks no key unless it was
    started with --api-key, and with one model it ignores the "model" field; in router mode the field picks the model
    (llama.cpp tools/server/README.md)
  - Open WebUI: Admin Panel > Settings > Connections > OpenAI API (as README.md of this project describes)
  - Continue: config.yaml, provider llama.cpp, apiBase without /v1 (Continue docs, model-providers/more/llamacpp)
  - aider: OPENAI_API_BASE, OPENAI_API_KEY and --model openai/<name> (aider docs, llms/openai-compat)
A command is given only when its program was found (rule 3), written for this OS's shell.

Python standard library only. Pure: it builds text and touches nothing.
"""
from __future__ import annotations

KEY = "sk-local"


def snippets(port: int, models: list, system: str, which) -> list:
    """-> [{id, label, kind: values | file | cmd | missing, text, note}] for llama-server on 127.0.0.1:port."""
    base = f"http://127.0.0.1:{port}"
    first = models[0] if models else "local"
    several = len(models) > 1
    names = ", ".join(models) if models else first
    note = ("Every request names the model it wants; llama.cpp loads it when asked." if several else
            "With one model, llama-server answers whatever model name is asked for, so any name works.")
    out = [
        {"id": "openai", "label": "Any program that speaks the OpenAI API", "kind": "values", "note": note,
         "text": f"Address (base URL): {base}/v1\nAPI key: any text, e.g. {KEY} (it is not checked)\n"
                 f"Model{'s' if several else ''}: {names}"},
        {"id": "open-webui", "label": "Open WebUI", "kind": "values",
         "note": "Then pick the model in a new chat. See the README for starting Open WebUI on port 3000.",
         "text": f"Admin Panel > Settings > Connections > OpenAI API\nURL: {base}/v1 "
                 f"(Open WebUI in Docker: http://host.docker.internal:{port}/v1)\nAPI key: {KEY}"},
        {"id": "continue", "label": "Continue (VS Code, JetBrains): config.yaml", "kind": "file",
         "note": "Add this to Continue's config.yaml (or add the model entry to the models you have).",
         "text": "name: Local llama.cpp\nversion: 0.0.1\nschema: v1\n\nmodels:\n"
                 + "".join(f"  - name: {m}\n    provider: llama.cpp\n    model: {m}\n    apiBase: {base}\n"
                           for m in (models or [first]))},
    ]
    if which("aider"):
        cmd = (f'$env:OPENAI_API_BASE="{base}/v1"; $env:OPENAI_API_KEY="{KEY}"; aider --model openai/{first}'
               if system == "Windows" else f"OPENAI_API_BASE={base}/v1 OPENAI_API_KEY={KEY} aider --model openai/{first}")
        out.append({"id": "aider", "label": "aider (in your project's folder)", "kind": "cmd", "text": cmd,
                    "note": "aider may warn that it does not know this model; that is expected."})
    else:
        out.append({"id": "aider", "label": "aider", "kind": "missing", "note": "",
                    "text": "aider was not found on this computer (looked on your PATH). Install it, then come back "
                            "here for the command."})
    return out
