"""llama-cpp-launchpad: the simple setup page (`model-setup --ui`).

A tiny web server for ONE page (ui/setup/index.html). The page asks what you want to do, shows the model
that fits your computer, and downloads and speed-tests it. All the real work is done by model_setup.py;
this file only exposes it over HTTP.

Python standard library only. Safe by construction:
  - listens on 127.0.0.1 only, and refuses requests whose Host header is not localhost (DNS rebinding)
  - changing things (download) needs a random per-run token that only the page itself is given
  - the browser never sends a repo or file name: it sends an id of a model this server offered earlier
  - serves one fixed file; no directory listing, no file paths from the browser
  - contacts nothing itself: Hugging Face traffic goes through model_setup.py, as in the command line
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import detect_tools
import hf_discover

PAGE = Path(__file__).resolve().parent.parent / "ui" / "setup" / "index.html"
USES = ("chat", "coding", "translation", "fast")
SEARCH_FOR_USE = {"coding": "coder"}            # extra Hub search text per use
MAX_BODY = 4096
# What to tell the user about each local-LLM tool. Plain text on purpose: the page never links elsewhere.
INSTALL_HINTS = {
    "ollama": "Download it from ollama.com/download",
    "llama-cpp": {"Windows": "winget install ggml.llamacpp", "default": "brew install llama.cpp"},
    "lmstudio": "Download it from lmstudio.ai",
    "unsloth": "pip install unsloth",
}
# A start command is only offered when the program it runs was really found (not just an app bundle, a Python
# package or a sibling program): tool id -> (program the command needs, what to say when it is missing).
START_NEEDS = {
    "ollama": ("ollama", "The ollama command was not found. Open the Ollama app, or add ollama to your PATH."),
    "llama-cpp": ("llama-server", "llama-server was not found, and the serve script needs it. {install}"),
    "lmstudio": ("lms", "The lms command was not found. Start the server from the LM Studio app instead."),
}
# Found, but not where the start command will look: say where it is instead of showing a command that fails.
OFF_PATH = {
    "ollama": "ollama was found at {path}, but it is not on your PATH, so 'ollama serve' would fail. "
              "Add its folder to your PATH.",
    "llama-cpp": "llama-server was found at {path}, but the serve script does not look there. "
                 "Set LLAMA_SERVER to that path, or copy it into this project's bin folder.",
    "lmstudio": "lms was found at {path}, but it is not on your PATH, so 'lms server start' would fail. "
                "Add its folder to your PATH.",
}
START_CMD = {"ollama": "ollama serve", "lmstudio": "lms server start"}      # llama.cpp: the project's serve script
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
       "img-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def find_program(tool: dict, program: str, probe) -> tuple:
    """Where is the executable `program`? -> (path or "", runnable: will the start command reach it?).
    Found in a known location is not enough: `lms server start` needs lms on PATH. The serve script (llama.cpp)
    also looks in $LLAMA_SERVER, the project's bin folder and ~/llama.cpp/build/bin."""
    j = probe.join
    serve_dirs = [j(probe.root, "bin")] + ([] if probe.system == "Windows" else [j(probe.home, "llama.cpp", "build", "bin")])
    serve_dirs = [probe.norm(d) for d in serve_dirs]
    found = ""
    for e in tool["evidence"]:
        stem = re.split(r"[\\/]", e["path"])[-1].lower()
        stem = stem[:-4] if stem.endswith(".exe") else stem
        if not (e["kind"].startswith("env-") or (e["kind"] in ("on-PATH", "known-location") and stem == program)):
            continue
        found = found or e["path"]
        parent = probe.norm(e["path"]).rsplit("/", 1)[0]
        if e["kind"] == "on-PATH" or (tool["id"] == "llama-cpp" and (e["kind"].startswith("env-") or parent in serve_dirs)):
            return e["path"], True
    return found, False


def serve_cmd(system: str) -> str:
    return "scripts\\win\\serve.bat" if system == "Windows" else "./scripts/unix/serve.sh"


class App:
    """Everything the page can ask for. `ms` is the model_setup module (passed in, so there is one copy of it)."""

    def __init__(self, ms, probe=None):
        self.ms = ms
        self.probe = probe or detect_tools.Probe()          # tests pass a fake computer
        self.token = secrets.token_urlsafe(24)
        self.hw = ms.detect_hw()
        ms.save_hw(self.hw)
        self.offered = {}                       # id -> what may be downloaded; the browser can only pick from this
        self.lock = threading.Lock()
        self.job = {"state": "idle"}

    # --- read-only answers ------------------------------------------------------------------------
    def state(self) -> dict:
        ms, hw = self.ms, self.hw
        gpu = hw.gpu_kind in ("nvidia", "gpu") and hw.gpu_usable
        return {
            "token": self.token,
            "ram_gb": (hw.ram_mb + 512) // 1024,
            "gpu": hw.gpu_name if hw.gpu_kind != "none" else "",
            "vram_gb": hw.vram_mb // 1024,
            "gpu_unused": hw.gpu_kind in ("nvidia", "gpu") and not hw.gpu_usable,
            "mode": "gpu" if gpu or hw.gpu_kind == "apple" else "cpu",
            "llama_server": bool(ms.find_llama_server()),
            "installed": ms.state_get("installed"),
            "serve_cmd": serve_cmd(platform.system()),
        }

    def tools(self, ids=None, verbose: bool = False) -> dict:
        """Which of Ollama / llama.cpp / LM Studio / Unsloth are installed: detect_tools.py, plus next-step hints."""
        result = detect_tools.detect(self.probe, ids)
        system = self.probe.system
        for tool in result["tools"]:
            if not verbose:
                del tool["searched"]
            install = INSTALL_HINTS[tool["id"]]
            hint = {"install": install.get(system, install["default"]) if isinstance(install, dict) else install}
            if tool["status"] == "installed" and tool["id"] in START_NEEDS:
                program, missing = START_NEEDS[tool["id"]]
                where, runnable = find_program(tool, program, self.probe)
                if runnable:
                    hint["start"] = serve_cmd(system) if tool["id"] == "llama-cpp" else START_CMD[tool["id"]]
                elif where:
                    hint["setup"] = OFF_PATH[tool["id"]].format(path=where)
                else:
                    hint["setup"] = missing.format(install=hint["install"])
            tool["hint"] = hint
        return result

    def card(self, m: dict) -> dict:
        ms = self.ms
        files = [(f, int(sz)) for f, sz in (m.get("files") or [(m["file"], m["size"])])]
        mid = f"{m['repo']}|{files[0][0]}"
        stem = Path(files[0][0]).stem
        quant = hf_discover.quant_of(stem)
        title = re.sub(r"-?(\d{5}-of-\d{5})$", "", stem)
        if quant:
            title = re.sub(re.escape(quant), "", title, flags=re.I)
        title = re.sub(r"[-_.]+$", "", title) or stem
        self.offered[mid] = {"repo": m["repo"], "files": files, "size": int(m["size"]),
                             "name": m.get("name") or stem, "title": title}
        tps = int(m["tps"])
        return {"id": mid, "title": title, "repo": m["repo"], "quant": quant, "size": int(m["size"]),
                "size_h": ms.human_size(int(m["size"])), "tps": tps,
                "verdict": "tight" if m.get("mode") == "tight" else ms.verdict(tps),
                "where": m.get("mode", "cpu"), "gpu_share": m.get("gpu_share", 0), "note": m.get("note", ""),
                "have": all(ms.local_path(m["repo"], f, sz)[1] for f, sz in files)}

    def recommend(self, use: str) -> dict:
        """The best catalog models for this machine (instant, no network)."""
        return {"models": [self.card(m) for m in self.ms.recommend(use, self.hw)]}

    def more(self, use: str, everything: bool) -> dict:
        """Search all of Hugging Face (slow: one request per repo)."""
        ms = self.ms
        a = argparse.Namespace(hub="downloads", search=SEARCH_FOR_USE.get(use, ""), author=None, all=everything,
                               max_lookups=30, ctx=hf_discover.DEFAULT_CTX, min_tps=3)
        cands = ms.discover_candidates(a, self.hw, lambda _msg: None)
        if cands is None:
            return {"error": "Could not reach Hugging Face. Check your connection and try again."}
        results, _ = ms.discover_check(cands, self.hw, a)
        rows = hf_discover.rank(results, "speed" if use == "fast" else "popular")[:10]
        return {"models": [self.card(r) for r in rows]}

    # --- download job ------------------------------------------------------------------------------
    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.job)

    def _set(self, **kw) -> None:
        with self.lock:
            self.job.update(kw)

    def start_install(self, mid: str):
        """-> (http status, body). Starts a background download of an offered model."""
        offer = self.offered.get(mid)
        if not offer:
            return 404, {"error": "Unknown model. Reload the page."}
        with self.lock:
            if self.job.get("state") in ("downloading", "testing"):
                return 409, {"error": "Another download is running."}
            self.job = {"state": "downloading", "title": offer["title"], "done": 0, "total": offer["size"]}
        threading.Thread(target=self._install, args=(offer,), daemon=True).start()
        return 202, {"ok": True}

    def _install(self, offer: dict) -> None:
        ms = self.ms
        try:
            base, paths = 0, []
            for f, size in offer["files"]:                  # split models: every part, into the same folder
                dest, have = ms.local_path(offer["repo"], f, size)
                path = dest if have else ms.download(
                    offer["repo"], f, size, lambda d, b=base: self._set(done=b + d))
                if not path:
                    self._set(state="error", error="The download did not finish (disk space or connection). "
                                                   "Press the button again to resume.")
                    return
                base += size
                self._set(done=base)
                paths.append(path)
            ms.record_installed(offer["name"], offer["repo"], offer["size"])
            self._set(state="testing")
            rc = ms.check_model_speed(paths[0], offer["size"], self.hw)
            tps = ms.state_int("measured_tps") if rc == 0 else 0
            self._set(state="done", bench="ok" if rc == 0 else "skipped" if rc == 2 else "failed", tps=tps)
        except Exception as e:                              # noqa: BLE001 - show the user something, never crash the page
            self._set(state="error", error=f"Something went wrong: {e}")


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "launchpad-ui"

        def log_message(self, *_args):                      # keep the terminal quiet
            pass

        # --- guards ---
        def host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)
            return host[0] in ("127.0.0.1", "localhost") and (len(host) == 2 and host[1] == str(self.server.server_address[1]))

        def send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def reply(self, code: int, obj) -> None:
            self.send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

        # --- routes ---
        def do_GET(self):
            if not self.host_ok():
                return self.reply(403, {"error": "forbidden"})
            url = urlparse(self.path)
            q = parse_qs(url.query)
            use = (q.get("use") or ["chat"])[0]
            use = use if use in USES else "chat"
            if url.path == "/":
                try:
                    return self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                except OSError:
                    return self.reply(500, {"error": "ui/setup/index.html is missing"})
            if url.path == "/api/state":
                return self.reply(200, app.state())
            if url.path == "/api/recommend":
                return self.reply(200, app.recommend(use))
            if url.path == "/api/more":
                return self.reply(200, app.more(use, (q.get("all") or ["0"])[0] == "1"))
            if url.path == "/api/progress":
                return self.reply(200, app.snapshot())
            if url.path == "/api/tools":
                ids = q.get("tool") or None
                if ids and any(i not in detect_tools.SPECS for i in ids):
                    return self.reply(400, {"error": "unknown tool"})
                try:
                    return self.reply(200, app.tools(ids, (q.get("verbose") or ["0"])[0] == "1"))
                except Exception:                           # noqa: BLE001 - a failed check must not take the page down
                    return self.reply(500, {"error": "Could not check for installed tools."})
            self.reply(404, {"error": "not found"})

        def do_POST(self):
            # Read the body first, even if we are about to refuse the request: answering without reading it
            # makes the client's connection reset (WinError 10054) instead of showing our 403.
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            raw = self.rfile.read(length) if 0 < length <= MAX_BODY else b""
            if length < 0 or length > MAX_BODY:
                self.close_connection = True                # the unread rest of a huge body is not worth draining
            if not self.host_ok():
                return self.reply(403, {"error": "forbidden"})
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host"):
                return self.reply(403, {"error": "forbidden"})
            if not secrets.compare_digest(self.headers.get("X-LP-Token") or "", app.token):
                return self.reply(403, {"error": "forbidden"})
            try:
                body = json.loads(raw or b"{}")
            except (ValueError, OSError):
                return self.reply(400, {"error": "bad request"})
            if urlparse(self.path).path == "/api/install" and isinstance(body, dict) and isinstance(body.get("id"), str):
                code, out = app.start_install(body["id"])
                return self.reply(code, out)
            self.reply(404, {"error": "not found"})

    return Handler


class Server(ThreadingHTTPServer):
    allow_reuse_address = False         # on Windows reuse would let another program share (and read) our port


def serve(ms, port: int = 8765, open_browser: bool = True) -> int:
    """Run the page until Ctrl+C. Uses the first free port from `port` upward."""
    app = App(ms)
    server = None
    for p in range(port, port + 20):
        try:
            server = Server(("127.0.0.1", p), make_handler(app))
            break
        except OSError:
            continue
    if server is None:
        print(f"Could not open a port between {port} and {port + 19}. Try --port N.")
        return 1
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"\n  llama-cpp-launchpad setup page: {url}\n  Only this computer can open it. Press Ctrl+C to stop.\n")
    if open_browser:
        threading.Timer(0.6, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
