"""llama-cpp-launchpad: compare two or three downloaded models on the same prompts, one after another.

Each model is started with llama-server (chat_server.ChatServer, the same command Start chatting runs), asked every
prompt through its /v1/chat/completions, and stopped before the next one starts, so only one model is in memory at
a time. What is recorded is what llama-server itself reports: its answer, generation speed (timings.
predicted_per_second) and time to the first token (timings.prompt_ms), plus how long the model took to load.

There is deliberately no quality score: a handful of prompts cannot rank models, so the answers are shown side by
side for the reader to judge.

Command line:  python utils/compare.py MODEL_A.gguf MODEL_B.gguf [--prompt TEXT ...] [--ctx N] [--max-tokens N]
Python standard library only. Writes nothing to disk.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import threading
import time
from pathlib import Path

import chat_server
from hardware import find_llama_server

PROMPTS = [
    ("Explain", "Explain in three sentences why the sky is blue."),
    ("Write", "Write a short, polite email declining an invitation to a meeting on Friday."),
    ("Reason", "A train leaves at 14:10 and arrives at 16:45. How long is the journey? Answer briefly."),
    ("Code", "Write a Python function that returns the n-th Fibonacci number, with a one-line comment."),
]
LOAD_TIMEOUT_S = 600


def server_argv() -> list:
    found = find_llama_server()
    return [found] if found else []


class Comparison:
    """One comparison run in a background thread. status() is safe to call at any time."""

    def __init__(self, models: list, find_server, prompts=None, settings=None, environ=None, system=None,
                 max_tokens: int = 256):
        if not 2 <= len(models) <= 3:
            raise ValueError("Compare two or three models.")
        self.models = [(Path(p), title) for p, title in models]
        self.find_server, self.prompts = find_server, list(prompts or PROMPTS)
        self.settings, self.environ, self.system = list(settings or []), environ, system
        self.max_tokens = max_tokens
        self.lock = threading.Lock()
        self.halt = threading.Event()
        self.server = None
        self.state = {"state": "idle", "prompts": [p[0] for p in self.prompts],
                      "models": [{"title": t, "file": p.name, "state": "waiting", "results": []} for p, t in self.models]}

    def status(self) -> dict:
        with self.lock:
            out = dict(self.state)
            out["models"] = [dict(m, results=list(m["results"])) for m in self.state["models"]]
            return out

    def _model(self, i: int, **kw) -> None:
        with self.lock:
            self.state["models"][i].update(kw)

    def servers_running(self):
        """The llama-server this run started that is still running, or None."""
        cs = self.server
        return cs if cs is not None and cs.proc is not None and cs.proc.poll() is None else None

    def start(self) -> dict:
        if not self.find_server():
            return {"error": chat_server.NOT_FOUND}
        with self.lock:
            if self.state["state"] == "running":
                return {"error": "A comparison is already running."}
            self.state["state"] = "running"
            self.state["started"] = time.time()
        threading.Thread(target=self._run, daemon=True).start()
        return self.status()

    def stop(self) -> dict:
        """Stop the run and the llama-server it started. "stopped" is recorded first: the run's own thread,
        which ends as soon as its server goes away, must not report "done" in between."""
        with self.lock:
            self.halt.set()
            if self.state["state"] == "running":
                self.state["state"] = "stopped"
            cs = self.server
        if cs is not None:
            cs.stop()
        return self.status()

    def _run(self) -> None:
        for i, (path, title) in enumerate(self.models):
            if self.halt.is_set():
                break
            self._one(i, path, title)
        with self.lock:
            if self.state["state"] == "running" and not self.halt.is_set():
                self.state["state"] = "done"

    def _one(self, i: int, path: Path, title: str) -> None:
        cs = chat_server.ChatServer(find_server=self.find_server, environ=self.environ, system=self.system)
        with self.lock:                     # stop() sets halt under this lock: never start a server after it
            if self.halt.is_set():
                return
            self.server = cs
        port = cs.port()
        port = port if not chat_server.port_in_use(port) else chat_server.next_free_port(port)
        t0 = time.monotonic()
        self._model(i, state="loading", started=time.time())
        code, body = cs.start(path, title, port or None, self.settings)
        if code != 202:
            self._model(i, state="failed", error=body.get("error", "llama-server did not start."), log=[], finished=time.time())
            return
        self._model(i, cmd=body.get("cmd", ""))
        while not self.halt.is_set():
            s = cs.status()
            if s["state"] in ("running", "failed", "stopped"):
                break
            if time.monotonic() - t0 > LOAD_TIMEOUT_S:
                cs.stop()
                break
            time.sleep(0.1)
        s = cs.status()
        if s["state"] != "running":
            cs.stop()
            self._model(i, state="failed", error=s.get("error") or "llama-server did not finish loading the model.",
                        log=s.get("log", [])[-20:], finished=time.time())
            return
        self._model(i, state="asking", load_s=round(time.monotonic() - t0, 1))
        speeds = []
        for name, text in self.prompts:
            if self.halt.is_set():
                break
            answer = chat_server.http_post_json(port, "/v1/chat/completions", {
                "messages": [{"role": "user", "content": text}], "max_tokens": self.max_tokens,
                "temperature": 0, "stream": False})
            row = {"prompt": name, "text": "", "tps": 0.0, "first_ms": 0.0, "tokens": 0, "error": ""}
            if not answer or answer[0] != 200 or not isinstance(answer[1], dict):
                row["error"] = f"llama-server answered {answer[0]}" if answer else "llama-server did not answer"
            else:
                j = answer[1]
                timings = j.get("timings") or {}
                row.update(text=str(((j.get("choices") or [{}])[0].get("message") or {}).get("content", "")),
                           tps=round(float(timings.get("predicted_per_second") or 0), 1),
                           first_ms=round(float(timings.get("prompt_ms") or 0), 1),
                           tokens=int(timings.get("predicted_n") or (j.get("usage") or {}).get("completion_tokens") or 0))
                if row["tps"]:
                    speeds.append(row["tps"])
            with self.lock:
                self.state["models"][i]["results"].append(row)
        cs.stop()
        self._model(i, state="stopped" if self.halt.is_set() else "done",
                    tps=round(statistics.mean(speeds), 1) if speeds else 0.0, finished=time.time())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="compare", description="Ask two or three models the same prompts, one at a time.")
    p.add_argument("models", nargs="+", help="two or three .gguf files")
    p.add_argument("--prompt", action="append", help="a prompt (repeatable; default: four built-in ones)")
    p.add_argument("--ctx", type=int, default=4096, help="context length for every model (default 4096)")
    p.add_argument("--max-tokens", type=int, default=256)
    a = p.parse_args(argv)
    prompts = [(f"Prompt {i}", t) for i, t in enumerate(a.prompt, 1)] if a.prompt else PROMPTS
    try:
        c = Comparison([(Path(m), Path(m).name) for m in a.models], find_server=server_argv, prompts=prompts,
                       settings=["-c", str(a.ctx)], max_tokens=a.max_tokens)
    except ValueError as e:
        print(e)
        return 2
    started = c.start()
    if started.get("error"):
        print(started["error"])
        return 1
    try:
        while c.status()["state"] == "running":
            time.sleep(0.2)
    except KeyboardInterrupt:
        c.stop()
        print("Stopped.")
        return 130
    s = c.status()
    for k, (name, text) in enumerate(prompts):
        print(f"\n=== {name}: {text}")
        for m in s["models"]:
            r = m["results"][k] if k < len(m["results"]) else None
            print(f"\n--- {m['file']}")
            print(r["error"] or r["text"] if r else m.get("error", "(no answer)"))
    print("\nModel".ljust(46) + "load      speed            first token")
    for m in s["models"]:
        if m["state"] == "failed":
            print(f"{m['file']:<45} failed: {m.get('error', '')}")
            continue
        first = statistics.mean(r["first_ms"] for r in m["results"]) if m["results"] else 0
        print(f"{m['file']:<45} {m.get('load_s', 0):>5.1f} s   {m.get('tps', 0):>6.1f} tokens/s   {first:>7.0f} ms")
    return 0 if all(m["state"] == "done" for m in s["models"]) else 1


if __name__ == "__main__":
    sys.exit(main())
