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
import re
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import chat_server
import detect_tools
import hf_discover
import llama_install

PAGE = Path(__file__).resolve().parent.parent / "ui" / "setup" / "index.html"
USES = ("chat", "coding", "translation", "fast")
SEARCH_FOR_USE = {"coding": "coder"}            # extra Hub search text per use
MAX_BODY = 4096
LLAMA_RELEASES = "github.com/ggml-org/llama.cpp/releases"


def _llama_cpp_install(probe) -> dict:
    """Windows: winget. macOS: Homebrew. Linux: Homebrew if present, else the release download the README describes.
    A command is only given when its package manager was found (rule 3); otherwise say what to do instead."""
    if probe.system == "Windows":
        if probe.which("winget"):
            return {"install_cmd": "winget install ggml.llamacpp"}
        return {"install": f"Download a Windows release from {LLAMA_RELEASES} and copy llama-server.exe into this "
                           "project's bin folder. (winget, which installs it in one step, was not found.)"}
    if probe.which("brew"):
        return {"install_cmd": "brew install llama.cpp"}
    if probe.system == "Darwin":
        return {"install": "Install Homebrew (see brew.sh), then run: brew install llama.cpp"}
    return {"install": f"Download a Linux release from {LLAMA_RELEASES} and copy llama-server into this project's "
                       "bin folder, or build it from source."}


def _unsloth_install(probe) -> dict:
    pip = "pip" if probe.which("pip") else "pip3" if probe.which("pip3") else ""
    if pip:
        return {"install_cmd": f"{pip} install unsloth"}
    return {"install": "Install it with pip: pip install unsloth (pip was not found on your PATH)."}


# What to tell the user about each local-LLM tool: plain text (the page never links elsewhere), or a function of the
# machine returning {"install": text} and/or {"install_cmd": a command whose program was found}.
INSTALL_HINTS = {
    "ollama": "Download it from ollama.com/download",
    "llama-cpp": _llama_cpp_install,
    "lmstudio": "Download it from lmstudio.ai",
    "unsloth": _unsloth_install,
}


def install_hint(tool_id: str, probe) -> dict:
    """-> {"install": always text to show, "install_cmd": only when it is a command that can run here}."""
    hint = INSTALL_HINTS[tool_id]
    try:
        out = dict(hint(probe)) if callable(hint) else {"install": hint}
    except Exception:                                       # noqa: BLE001 - a failed check must not take the page down
        out = {"install": "Could not check this computer for a package manager. See the README for install steps."}
    out.setdefault("install", out.get("install_cmd", ""))
    return out


def os_name(system: str) -> str:
    return {"Windows": "windows", "Darwin": "mac"}.get(system, "linux")


def launcher(system: str, name: str) -> str:
    """The project's own launcher for this OS (it finds Python itself: `py -3` on Windows, never `python3` there)."""
    return f"scripts\\win\\{name}.bat" if system == "Windows" else f"./scripts/unix/{name}.sh"
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
    return launcher(system, "serve")


def shown_path(path: Path) -> str:
    """A path as the user should type it from the project folder: relative when inside it, else as is."""
    try:
        return str(Path(path).resolve().relative_to(detect_tools.ROOT.resolve()))
    except ValueError:
        return str(path)


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
        # "Start chatting": the one llama-server this page runs. It follows self.probe, which tests replace.
        self.chat = chat_server.ChatServer(
            find_server=lambda: [p] if (p := ms.find_llama_server()) else [],
            system=lambda: self.probe.system, which=lambda name: self.probe.which(name),
            run=lambda args, timeout=20: self.probe.run(args, timeout))
        # Installing llama.cpp: into the project's bin/ (Windows, Linux) or with Homebrew (macOS, if found).
        self.bin_dir = detect_tools.ROOT / "bin"
        self.llama_version = llama_install.server_version       # `llama-server --version`: does the copy found run?
        self.installer = self.make_installer()

    def make_installer(self, **kw):
        args = dict(bin_dir=lambda: self.bin_dir, system=lambda: self.probe.system, machine=lambda: self.probe.machine,
                    gpu_kind=lambda: self.hw.gpu_kind, find=lambda: self.ms.find_llama_server(),
                    which=lambda name: self.probe.which(name), version=lambda argv: self.llama_version(argv),
                    on_done=self._after_install)
        args.update(kw)
        return llama_install.Installer(**args)

    def _after_install(self) -> None:
        """A new llama.cpp build may use the GPU where the old one could not: detect again, so picks follow."""
        self.hw = self.ms.detect_hw()
        self.ms.save_hw(self.hw)

    def llama_info(self) -> dict:
        """What llama-server the serve scripts would use, whether it runs, and why (and how) to install one."""
        found = self.ms.find_llama_server()
        works, out = self.llama_version([found]) if found else (False, "")
        version = next((line.strip() for line in out.splitlines() if "version" in line.lower()), "") if works else ""
        return {"found": found, "works": works, "version": version,
                "need": llama_install.why_install(found, works, self.hw),
                "offer": self.installer.offer(), "job": self.installer.status()}

    def llama_install(self, body: dict):
        variant = body.get("variant", "auto")
        if variant not in ("auto", "cpu"):
            return 400, {"error": "bad request"}
        if self.chat.status().get("state") in ("starting", "running"):
            return 409, {"error": "Stop the chat first: llama-server cannot be replaced while it is running."}
        if not self.llama_info()["need"]:
            return 409, {"error": "A working llama-server that can use this computer is already installed."}
        return self.installer.start(variant)

    def close(self) -> None:
        """The page server is stopping: stop the chat it started (and nothing else)."""
        self.chat.stop()

    # --- read-only answers ------------------------------------------------------------------------
    def state(self) -> dict:
        ms, hw = self.ms, self.hw
        gpu = hw.gpu_kind in ("nvidia", "gpu") and hw.gpu_usable
        llama = self.llama_info()
        return {
            "token": self.token,
            "ram_gb": (hw.ram_mb + 512) // 1024,
            "gpu": hw.gpu_name if hw.gpu_kind != "none" else "",
            "vram_gb": hw.vram_mb // 1024,
            "gpu_unused": hw.gpu_kind in ("nvidia", "gpu") and not hw.gpu_usable,
            "mode": "gpu" if gpu or hw.gpu_kind == "apple" else "cpu",
            "llama_server": bool(llama["found"] and llama["works"]),     # found AND runs (rule 3)
            "llama": llama,
            "llama_install": install_hint("llama-cpp", self.probe),
            "installed": ms.state_get("installed"),
            "os": os_name(self.probe.system),
            "serve_cmd": serve_cmd(self.probe.system),
            "chat": self.chat.status(),
        }

    # --- Start chatting ------------------------------------------------------------------------------
    def _chat_model(self, mid):
        """An offered, fully downloaded model -> (path of its first part, title), or (http status, error body)."""
        offer = self.offered.get(mid) if isinstance(mid, str) else None
        if not offer:
            return None, (404, {"error": "Unknown model. Reload the page."})
        paths = [self.ms.local_path(offer["repo"], f, size) for f, size in offer["files"]]
        if not all(have for _, have in paths):
            return None, (409, {"error": f"{offer['title']} is not downloaded yet. Get it first."})
        return (paths[0][0], offer["title"]), None

    def chat_status(self, mid=None) -> dict:
        out = {"chat": self.chat.status()}
        if mid:
            found, _ = self._chat_model(mid)
            if found:
                out["preview"] = self.chat.preview(found[0])
        return out

    def chat_start(self, body: dict):
        port = body.get("port")
        if port is not None and (type(port) is not int or not 1024 <= port <= 65535):
            return 400, {"error": "The port must be a number from 1024 to 65535."}
        found, refused = self._chat_model(body.get("id"))
        if refused:
            return refused
        return self.chat.start(found[0], found[1], port)

    def tools(self, ids=None, verbose: bool = False) -> dict:
        """Which of Ollama / llama.cpp / LM Studio / Unsloth are installed: detect_tools.py, plus next-step hints."""
        result = detect_tools.detect(self.probe, ids)
        system = self.probe.system
        for tool in result["tools"]:
            if not verbose:
                del tool["searched"]
            hint = install_hint(tool["id"], self.probe)
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
        offer = self.offered[mid] = {"repo": m["repo"], "files": files, "size": int(m["size"]),
                                     "name": m.get("name") or stem, "title": title}
        tps = int(m["tps"])
        return {"id": mid, "title": title, "repo": m["repo"], "quant": quant, "size": int(m["size"]),
                "size_h": ms.human_size(int(m["size"])), "tps": tps,
                "verdict": "tight" if m.get("mode") == "tight" else ms.verdict(tps),
                "where": m.get("mode", "cpu"), "gpu_share": m.get("gpu_share", 0), "note": m.get("note", ""),
                "have": all(ms.local_path(m["repo"], f, sz)[1] for f, sz in files),
                "commands": self.download_commands(offer)}

    def download_commands(self, offer: dict) -> list:
        """Terminal commands for one model, for this OS, built only from programs that were found (rule 3).
          resume  the project's launcher: continues the app's own partial download (.part) and records the model
          manual  plain curl into the exact file the app looks for. A fresh download (curl cannot continue the
                  app's .part file), so it is labelled as such. Only when curl is on PATH; Windows needs curl.exe,
                  because `curl` in Windows PowerShell 5 is an alias of Invoke-WebRequest and rejects -L / -o."""
        system, repo, files = self.probe.system, offer["repo"], offer["files"]
        single = len(files) == 1
        resume = f'{launcher(system, "radar")} --download "{repo}"' + (f' --file "{files[0][0]}"' if single else "")
        out = [{"kind": "resume", "label": "Download or resume it from a terminal", "cmd": resume}]
        if single and self.probe.which("curl"):
            f, size = files[0]
            dest, _ = self.ms.local_path(repo, f, size)
            url = offer.get("download_url") or f"{self.ms.HF_BASE}/{repo}/resolve/main/{f}"
            curl = "curl.exe" if system == "Windows" else "curl"
            out.append({"kind": "manual", "label": "Or download it by hand with curl (starts from zero)",
                        "cmd": f'{curl} -L -o "{shown_path(dest)}" "{url}"'})
        return out

    def _offer_hub_model(self, m: dict) -> None:
        """Make a radar/history model downloadable by id, and attach its terminal commands."""
        repo = m.get("repo", "")
        name = m.get("name") or repo.split("/")[-1] or "model"
        size = int(m.get("size_bytes") or m.get("size") or 0)
        fname = m.get("file") or (m.get("files")[0][0] if m.get("files") else f"{name}.gguf")
        files = m.get("files") or [(fname, size)]
        dl_url = m.get("download_url") or f"https://huggingface.co/{repo}/resolve/main/{fname}"
        mid = f"{repo}|{fname}"
        offer = self.offered[mid] = {"repo": repo, "file": fname, "files": files, "size": size, "name": name,
                                     "title": m.get("title") or name, "download_url": dl_url}
        m.update(id=mid, file=fname, files=files, download_url=dl_url, commands=self.download_commands(offer))

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

    def radar(self, gpu_only: bool = False, search: str | None = None,
              sync: bool = False, cluster: str | None = None) -> dict:
        """Dynamic Hugging Face radar of trending/new models and historical status."""
        import hf_radar
        if sync:
            latest = hf_radar.sync_radar(self.hw, search=search)
        else:
            latest = hf_radar.load_latest()
            if not latest:
                latest = hf_radar.sync_radar(self.hw, search=search)
        models = latest.get("models") or []
        for m in models:
            if "clusters" not in m:
                m["clusters"] = hf_radar.classify_clusters(m, m.get("name", ""))
        if gpu_only:
            models = [m for m in models if m.get("fit_mode") == "gpu"]
        if cluster and cluster != "all":
            models = [m for m in models if cluster in m.get("clusters", [])]
        for m in models:
            self._offer_hub_model(m)
        out = {"updated_at": latest.get("updated_at"), "models": models}
        if latest.get("offline"):
            out["offline"] = True           # the Hub could not be reached: these are the saved results
        return out

    def radar_history(self, base: str | None = None) -> dict:
        """Historical snapshot diff showing what changed since last sync."""
        import hf_radar
        diff = hf_radar.compute_sync_diff(base_snap=base)
        for cat in ("new_models", "top_movers", "all_movers"):
            for m in diff.get(cat) or []:
                self._offer_hub_model(m)
        return diff

    # --- download job ------------------------------------------------------------------------------
    def snapshot(self) -> dict:
        with self.lock:
            if self.job.get("state") in ("downloading", "testing"):
                return dict(self.job)
        ms = self.ms
        if ms.state_get("dl_active") == "1":
            repo, file, total = ms.state_get("dl_repo"), ms.state_get("dl_file"), ms.state_int("dl_total")
            return {
                "state": ms.state_get("dl_state") or "downloading",
                "title": ms.state_get("dl_title") or repo or "Terminal Download",
                "done": ms.state_int("dl_done"),
                "total": total,
                "source": "terminal",
                "repo": repo,
                "file": file,
                "commands": self.download_commands({"repo": repo, "files": [(file, total)]}) if repo and file else [],
            }
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
            self.job = {
                "state": "downloading",
                "id": mid,                      # the page starts the chat with this model when it is done
                "title": offer["title"],
                "done": 0,
                "total": offer["size"],
                "repo": offer["repo"],
                "file": offer.get("file", ""),
                "commands": self.download_commands(offer),
            }
        threading.Thread(target=self._install, args=(offer,), daemon=True).start()
        return 202, {"ok": True}

    def _install(self, offer: dict) -> None:
        ms = self.ms
        try:
            base, paths = 0, []
            total_size = offer.get("size") or sum(sz for _, sz in offer.get("files", []))
            ms.state_update({
                "dl_active": "1",
                "dl_state": "downloading",
                "dl_title": offer["title"],
                "dl_repo": offer["repo"],
                "dl_file": offer.get("file", ""),
                "dl_done": 0,
                "dl_total": total_size,
            })
            sys.stderr.write(f"\n[LAUNCHPAD] Starting download: {offer['repo']}\n")
            sys.stderr.write(f"[LAUNCHPAD] Total payload: {ms.human_size(total_size)}\n")
            sys.stderr.flush()

            for f, size in offer["files"]:                  # split models: every part, into the same folder
                dest, have = ms.local_path(offer["repo"], f, size)

                def on_chunk(done, b=base, sz=total_size, fn=f):
                    cur = b + done
                    self._set(done=cur)
                    ms.state_update({"dl_done": cur})
                    pct = int(cur * 100 // max(sz, 1))
                    bar_len = 25
                    filled = int(bar_len * pct // 100)
                    bar = "=" * filled + (">" if filled < bar_len else "")
                    bar = bar.ljust(bar_len, " ")
                    sys.stderr.write(
                        f"\r[LAUNCHPAD] [{bar}] {pct:3d}%  {ms.human_size(cur)} / {ms.human_size(sz)} ({fn})"
                    )
                    sys.stderr.flush()

                path = dest if have else ms.download(offer["repo"], f, size, on_chunk)
                if not path:
                    resume = self.download_commands(offer)[0]["cmd"]
                    sys.stderr.write(f"\n[LAUNCHPAD] Download stopped. It keeps what it has; to continue, run:\n  {resume}\n")
                    sys.stderr.flush()
                    ms.state_update({"dl_active": "0", "dl_state": "error"})
                    self._set(
                        state="error",
                        error="The download did not finish (disk space or connection). Press Try again to resume, "
                              "or resume it from a terminal.",
                        file=f,
                        repo=offer["repo"],
                    )
                    return
                base += size
                self._set(done=base)
                ms.state_update({"dl_done": base})
                paths.append(path)

            sys.stderr.write("\n[LAUNCHPAD] Download complete! Running speed test with llama-bench...\n")
            sys.stderr.flush()
            ms.record_installed(offer["name"], offer["repo"], offer["size"])
            self._set(state="testing")
            ms.state_update({"dl_state": "testing"})
            rc = ms.check_model_speed(paths[0], offer["size"], self.hw)
            tps = ms.state_int("measured_tps") if rc == 0 else 0
            ms.state_update({"dl_active": "0", "dl_state": "done"})
            cmd = serve_cmd(self.probe.system)
            sys.stderr.write(
                f"[LAUNCHPAD] Ready! Speed: ~{tps} tokens/s. Start server with: {cmd}\n\n"
            )
            sys.stderr.flush()
            self._set(state="done", bench="ok" if rc == 0 else "skipped" if rc == 2 else "failed", tps=tps)
        except Exception as e:                              # noqa: BLE001 - show the user something, never crash the page
            ms.state_update({"dl_active": "0", "dl_state": "error"})
            sys.stderr.write(f"\n[LAUNCHPAD] Error during download: {e}\n")
            sys.stderr.flush()
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
            if url.path == "/api/radar":
                gpu_only = (q.get("gpu_only") or ["0"])[0] == "1"
                search = (q.get("search") or [None])[0]
                sync = (q.get("sync") or ["0"])[0] == "1"
                cluster = (q.get("cluster") or [None])[0]
                return self.reply(200, app.radar(
                    gpu_only=gpu_only, search=search, sync=sync, cluster=cluster
                ))
            if url.path == "/api/radar/history":
                base = (q.get("base") or [None])[0]
                return self.reply(200, app.radar_history(base=base))
            if url.path == "/api/progress":
                return self.reply(200, app.snapshot())
            if url.path == "/api/chat":
                return self.reply(200, app.chat_status((q.get("id") or [None])[0]))
            if url.path == "/api/llama":
                return self.reply(200, app.llama_info())
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
            path = urlparse(self.path).path
            if not isinstance(body, dict):
                return self.reply(400, {"error": "bad request"})
            if path == "/api/install" and isinstance(body.get("id"), str):
                code, out = app.start_install(body["id"])
                return self.reply(code, out)
            if path == "/api/chat/start":
                code, out = app.chat_start(body)
                return self.reply(code, out)
            if path == "/api/chat/stop":
                return self.reply(200, app.chat.stop())
            if path == "/api/llama/install":
                code, out = app.llama_install(body)
                return self.reply(code, out)
            self.reply(404, {"error": "not found"})

    return Handler


class Server(ThreadingHTTPServer):
    allow_reuse_address = False         # on Windows reuse would let another program share (and read) our port


def serve(ms, port: int = 8765, open_browser: bool = True, initial_hash: str = "") -> int:
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
    target = f"{initial_hash}" if initial_hash else ""
    url = f"http://127.0.0.1:{server.server_address[1]}/{target}"
    print(f"\n  llama-cpp-launchpad setup page: {url}\n  Only this computer can open it. Press Ctrl+C to stop.\n")
    if open_browser:
        threading.Timer(0.6, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if hasattr(app, "close"):
            app.close()                 # stops the llama-server this page started, if any
    return 0
