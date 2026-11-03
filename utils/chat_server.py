"""llama-cpp-launchpad: "Start chatting" on the setup page. Runs llama-server for one model and reports on it.

The command is the one the serve scripts run (serve.sh / serve.ps1):
    llama-server -m MODEL --port PORT [EXTRA_ARGS split on whitespace]
with PORT (default 8080) and EXTRA_ARGS read from the page server's environment when the command is built.

Rules this file keeps:
  - it only ever stops the one process it started itself (no "stop every llama-server", unlike KILL_EXISTING)
  - stopping works the same on Windows, macOS and Linux: Popen.terminate(), then Popen.kill() if it does not exit
    (TerminateProcess on Windows; no POSIX signals are named here)
  - a busy port is never taken over: it says what is using it (and where it looked) and offers the next free port
  - no command is shown or run unless llama-server was found

Python standard library only. Writes nothing to disk: the server's output is kept in memory (the last lines).
"""
from __future__ import annotations

import collections
import http.client
import json
import os
import platform
import re
import shlex
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DEFAULT_PORT = 8080
LOG_LINES = 200
NOT_FOUND = ("llama-server was not found (looked in LLAMA_SERVER, your PATH, this project's bin folder and "
             "~/llama.cpp/build/bin), so a chat cannot be started yet.")


# --- Ports ---------------------------------------------------------------------------------------
class _BindProbe(HTTPServer):
    # Windows: SO_REUSEADDR would let us bind a port another program is listening on, so never set it there.
    # Elsewhere set it as llama-server's HTTP library does, so a port in TIME_WAIT is not reported as busy.
    allow_reuse_address = platform.system() != "Windows"

    def server_bind(self):
        # HTTPServer.server_bind also looks up the host name (socket.getfqdn), which can take seconds on macOS and
        # is done for every port tried. Binding is all this probe needs: call socketserver.TCPServer.server_bind.
        super(HTTPServer, self).server_bind()


def port_in_use(port: int) -> bool:
    """Is something listening on 127.0.0.1:port, or would llama-server fail to bind it?"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
    try:
        conn.connect()
        return True
    except OSError:
        pass
    finally:
        conn.close()
    try:
        probe = _BindProbe(("127.0.0.1", port), BaseHTTPRequestHandler)
    except OSError:
        return True
    probe.server_close()
    return False


def next_free_port(port: int) -> int:
    for p in range(port + 1, min(port + 101, 65536)):
        if not port_in_use(p):
            return p
    return 0


def http_get(port: int, path: str, timeout: float = 1.0):
    """GET http://127.0.0.1:port/path, directly (never through a proxy) -> (status, headers, body) or None."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path)
        r = conn.getresponse()
        return r.status, r, r.read(65536)
    except (OSError, http.client.HTTPException):
        return None
    finally:
        conn.close()


def http_post_json(port: int, path: str, body: dict, timeout: float = 600.0):
    """POST JSON to http://127.0.0.1:port/path, directly (never through a proxy) -> (status, parsed JSON or None),
    or None when nothing answered."""
    data = json.dumps(body).encode("utf-8")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("POST", path, body=data, headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        raw = r.read()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, None
    except (OSError, http.client.HTTPException):
        return None
    finally:
        conn.close()


def http_probe(port: int) -> tuple:
    """What answers HTTP on the port? -> (description or "", what was checked, for the log)."""
    where = f"HTTP on 127.0.0.1:{port}"
    props = http_get(port, "/props")
    if props is None:
        return "", f"{where}: no answer over HTTP"
    if props[0] == 200:
        try:
            model = json.loads(props[2]).get("model_path") or ""
        except (ValueError, AttributeError):
            model = ""
        if model:
            name = re.split(r"[\\/]", model)[-1]
            return f"another llama-server (model {name})", f"{where}: a llama-server answered /props"
    server = props[1].getheader("Server") or ""
    if server:
        return f"a web server that calls itself {server}", f"{where}: answered, Server header {server!r}"
    return "a program that answers HTTP", f"{where}: answered, but did not say what it is"


def _lsof(port, which, run):
    exe = which("lsof")
    if not exe:
        return "", "lsof: not found"
    out = run([exe, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpc"])
    pid = re.search(r"(?m)^p(\d+)$", out)
    cmd = re.search(r"(?m)^c(.+)$", out)
    if pid and cmd:
        return f"{cmd.group(1).strip()} (process {pid.group(1)})", f"lsof: process {pid.group(1)} listens on {port}"
    return "", f"lsof: no listener on {port} that this user can see"


def _ss(port, which, run):
    exe = which("ss")
    if not exe:
        return "", "ss: not found"
    out = run([exe, "-ltnpH", f"sport = :{port}"])
    m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', out)
    if m:
        return f"{m.group(1)} (process {m.group(2)})", f"ss: process {m.group(2)} listens on {port}"
    return "", f"ss: no listener on {port} that this user can see"


def _netstat(port, which, run):
    exe = which("netstat")
    if not exe:
        return "", "netstat: not found"
    pid = ""
    for line in run([exe, "-ano", "-p", "TCP"]).splitlines():
        cols = line.split()
        if len(cols) >= 5 and cols[0].upper() == "TCP" and cols[1].endswith(f":{port}") and cols[3].upper() == "LISTENING":
            pid = cols[4]
            break
    if not pid:
        return "", f"netstat: no listener on {port}"
    tasklist = which("tasklist")
    if not tasklist:
        return f"process {pid}", f"netstat: process {pid} listens on {port}; tasklist: not found"
    m = re.match(r'\s*"([^"]+)"', run([tasklist, "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]))
    name = m.group(1) if m else ""
    return (f"{name} (process {pid})" if name else f"process {pid}"), f"netstat: process {pid} listens on {port}"


def who_uses(port: int, system: str, which, run) -> tuple:
    """-> (what is using the port, or "" if nothing could tell; every place looked, hit or miss)."""
    http_desc, looked_http = http_probe(port)
    looked = [looked_http]
    finders = [_netstat] if system == "Windows" else [_lsof] + ([_ss] if system == "Linux" else [])
    proc_desc = ""
    for find in finders:
        proc_desc, note = find(port, which, run)
        looked.append(note)
        if proc_desc:
            break
    return ", ".join(d for d in (proc_desc, http_desc) if d), looked


# --- Settings: plain-language presets that map to real llama-server flags --------------------------------
# A preset is only offered when this llama-server lists every flag it needs in its --help (rule 3). Tokens are
# about 3/4 of an English word, so 4096 tokens hold roughly 3,000 words.
PRESETS = {
    "auto": {"label": "Let llama.cpp decide", "ctx": 0,
             "text": "llama.cpp picks the context length and how much goes on the graphics card."},
    "short": {"label": "Short chats", "ctx": 4096,
              "text": "Remembers about 3,000 words of the conversation. Uses the least memory."},
    "long": {"label": "Long documents", "ctx": 32768, "type_k": "q8_0",
             "text": "Remembers about 24,000 words, so you can paste long documents. Uses much more memory; "
                     "part of it is stored at 8 bits to save space."},
    "fast": {"label": "Fastest replies", "ctx": 2048, "gpu": True,
             "text": "A short memory, and every layer of the model on the graphics card."},
}
PRESET_ORDER = ("short", "long", "fast", "auto")
FLAG_FOR = {"-c": "--ctx-size", "-ctk": "--cache-type-k", "-ngl": "--n-gpu-layers"}
CTX_MIN, CTX_MAX = 256, 1048576


def server_flags(help_text: str) -> set:
    """The long flags a llama-server --help lists. Only the flag column is read (the leading parts of a line, split
    on wide gaps, that start with a dash: "-m,    --model FNAME      model path"), so a flag named in another
    flag's description does not count."""
    flags = set()
    for line in (help_text or "").splitlines():
        for part in re.split(r"\s{2,}", line.strip()):
            if not part.startswith("-"):
                break
            flags.update(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", part))
    return flags


def default_preset(flags: set) -> str:
    """A build with --fit sizes the context to the memory it finds: let it. Without --fit, -c 0 means the model's
    whole trained context (often 128k tokens), so ask for a short one instead, when -c can be set at all."""
    return "short" if "--ctx-size" in flags and "--fit" not in flags else "auto"


def settings_args(preset: str, flags: set, ctx=None, gpu: bool = False, train_ctx: int = 0) -> tuple:
    """-> (arguments for llama-server, "") or ([], why this preset cannot run here). ctx: a context length the
    user typed, replacing the preset's. train_ctx: the model's own limit (from its header); never asked to exceed it."""
    p = PRESETS.get(preset)
    if p is None:
        return [], f"Unknown setting {preset!r}."
    if ctx is not None and (type(ctx) is not int or not CTX_MIN <= ctx <= CTX_MAX):
        return [], f"The context length must be a whole number from {CTX_MIN} to {CTX_MAX}."
    if p.get("gpu") and not gpu:
        return [], "This needs a graphics card that llama.cpp can use, and none was found."
    args = []
    want = ctx if ctx is not None else p["ctx"]
    if want:
        args += ["-c", str(min(want, train_ctx) if train_ctx else want)]
    if p.get("type_k"):
        args += ["-ctk", p["type_k"]]
    if p.get("gpu"):
        args += ["-ngl", "99"]
    missing = [FLAG_FOR[a] for a in args if a in FLAG_FOR and FLAG_FOR[a] not in flags]
    if missing:
        return [], f"This llama-server does not list {', '.join(missing)} in its --help (it may be an old build)."
    return args, ""


# --- The server this page runs -----------------------------------------------------------------
class ChatServer:
    """One llama-server started by the setup page. All state lives here; status() is safe to call any time."""

    def __init__(self, find_server, environ=None, system=None, which=None, run=None, help=None):
        import shutil
        from hardware import run_cmd
        self.find_server = find_server                     # -> argument list that starts llama-server, or []
        self.environ = os.environ if environ is None else environ
        self._system = system                               # "Windows" | "Darwin" | "Linux", or a function giving it
        self.which = which or shutil.which
        self.run = run or run_cmd
        self.help = help or (lambda argv: run_cmd(argv + ["--help"], 20))      # -> llama-server --help output
        self._flags = {}                                    # llama-server argv -> its flags (asked once per program)
        self.lock = threading.Lock()
        self.proc = None
        self.job = {"state": "idle"}
        self.log = collections.deque(maxlen=LOG_LINES)

    @property
    def system(self) -> str:
        s = self._system() if callable(self._system) else self._system
        return s or platform.system()

    # --- the command ---
    def port(self, chosen=None) -> int:
        if chosen:
            return int(chosen)
        value = str(self.environ.get("PORT") or "").strip()
        return int(value) if value.isdigit() and 0 < int(value) < 65536 else DEFAULT_PORT

    def help_flags(self) -> set:
        """The flags this llama-server lists in --help (asked once per program; none when it is not found)."""
        argv = tuple(self.find_server())
        if not argv:
            return set()
        if argv not in self._flags:
            self._flags[argv] = server_flags(self.help(list(argv)))
        return self._flags[argv]

    def command(self, model: Path, port=None, settings=None) -> tuple:
        """settings (from settings_args) go before EXTRA_ARGS: for a flag given twice the last wins, so flags the
        user set in the environment keep winning, as in the serve scripts."""
        port = self.port(port)
        extra = str(self.environ.get("EXTRA_ARGS") or "").split()
        model_args = ["-m", str(model)] if model is not None else []          # None: router mode (router.py)
        return (list(self.find_server()) + model_args + ["--port", str(port)] + list(settings or []) + extra, port)

    def shown(self, argv: list) -> str:
        return subprocess.list2cmdline(argv) if self.system == "Windows" else shlex.join(argv)

    def preview(self, model: Path, port=None, check_port: bool = True, settings=None) -> dict:
        """What Start chatting would run, and whether its port is free. Starts nothing."""
        argv, port = self.command(model, port, settings)
        if not self.find_server():
            return {"missing": NOT_FOUND, "port": port}
        out = {"cmd": self.shown(argv), "port": port, "busy": None}
        if check_port and port_in_use(port):
            out["busy"] = self.busy(port)
        return out

    def busy(self, port: int) -> dict:
        used_by, looked = who_uses(port, self.system, self.which, self.run)
        return {"port": port, "used_by": used_by, "looked": looked, "free_port": next_free_port(port)}

    # --- status ---
    def status(self) -> dict:
        with self.lock:
            out = dict(self.job)
            out["log"] = list(self.log)
        return out

    def _set(self, **kw) -> None:
        with self.lock:
            self.job.update(kw)

    # --- start / stop ---
    def start(self, model: Path, title: str, port=None, settings=None, ready: str = "/health") -> tuple:
        """-> (http status, body). 202 when llama-server was started (it is then "starting" until it answers).
        The slot is reserved under the lock first, so two Start requests at once cannot both launch a server."""
        with self.lock:
            state = self.job.get("state")
            if state in ("starting", "running", "reserved"):
                return 409, {"error": "A chat server is already running. Stop it first.", **self.job}
            if state == "stopping":
                return 409, {"error": "The chat server is still stopping. Try again in a moment.", **self.job}
            previous = dict(self.job)
            self.job = {"state": "reserved"}

        def release(code, body):
            with self.lock:
                self.job = previous
            return code, body
        if not self.find_server():
            return release(409, {"error": NOT_FOUND, "missing": True})
        argv, port = self.command(model, port, settings)
        if port_in_use(port):
            busy = self.busy(port)
            who = busy["used_by"] or "another program (it could not be identified)"
            free = f" Port {busy['free_port']} is free." if busy["free_port"] else ""
            return release(409, {"error": f"Port {port} is already in use by {who}.{free}", "port_busy": busy})
        env = dict(os.environ)
        libdir = str(Path(argv[0]).parent)           # release builds keep their libraries next to llama-server
        for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            env[var] = libdir + (os.pathsep + env[var] if env.get(var) else "")
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    env=env, text=True, encoding="utf-8", errors="replace")
        except OSError as e:
            error = f"llama-server could not be started: {e}"
            with self.lock:
                self.job = {"state": "failed", "error": error, "cmd": self.shown(argv), "port": port, "model": title}
            return 500, {"error": error}
        with self.lock:
            self.proc = proc
            self.log.clear()
            self.job = {"state": "starting", "cmd": self.shown(argv), "port": port, "model": title,
                        "model_path": str(model) if model is not None else "",
                        "url": f"http://127.0.0.1:{port}/", "pid": proc.pid, "started": time.time()}
        reader = threading.Thread(target=self._read, args=(proc,), daemon=True)
        reader.start()
        threading.Thread(target=self._watch, args=(proc, port, reader, ready), daemon=True).start()
        return 202, self.status()

    def _read(self, proc) -> None:
        with proc.stdout:                                   # closed when llama-server's output ends
            for line in proc.stdout:
                with self.lock:
                    self.log.append(line.rstrip("\r\n"))

    def _watch(self, proc, port: int, reader=None, ready: str = "/health") -> None:
        while True:
            code = proc.poll()
            with self.lock:
                if proc is not self.proc:
                    return
                state = self.job.get("state")
            if code is not None:
                if reader is not None:
                    reader.join(10)                         # report the failure with llama-server's last words
                if state in ("starting", "running"):
                    why = ("llama-server stopped unexpectedly" if state == "running"
                           else "llama-server stopped before it was ready")
                    self._set(state="failed", exit_code=code, error=f"{why} (exit code {code}). Its output is below.")
                return
            if state == "starting":
                answer = http_get(port, ready)
                if answer and answer[0] == 200:
                    self._set(state="running")
            time.sleep(0.25)

    def stop(self) -> dict:
        """Stop the llama-server this page started, and nothing else."""
        with self.lock:
            proc = self.proc
            if proc is None or self.job.get("state") not in ("starting", "running"):
                return dict(self.job, log=list(self.log))
            self.job["state"] = "stopping"
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(10)
        self._set(state="stopped", exit_code=proc.poll())
        return self.status()
