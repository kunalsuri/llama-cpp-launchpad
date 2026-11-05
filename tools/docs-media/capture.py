"""Make the documentation's screenshots, GIFs and videos from the real program, and record how each one was made.

    python tools/docs-media/capture.py --list          what it would capture, and anything missing to do it
    python tools/docs-media/capture.py                 capture everything into docs/media/
    python tools/docs-media/capture.py --only setup    one scene (see --list)
    python tools/docs-media/capture.py --out DIR       a trial run somewhere else (this may use the test suite's fake)

It drives what a person would use: the setup page started by model-setup.py --ui (as ui.sh does), the serve.sh
menu in a real terminal, and the Tasks and Translation pages served by llama-server. Nothing on screen is edited.
Two things are changed, and both are written into docs/media/manifest.json next to the file they affect:
  - a wait longer than a few seconds (a download, a model loading) is sped up, and a card before it says how long it
    really took and by how much it was sped up;
  - in terminal recordings, pauses longer than IDLE_LIMIT_S are shortened to it (as asciinema's idle limit does).

Publishing into docs/media/ is refused unless llama-server is a real build (not tests/fake_llama_server.py) and every
model used has its Hugging Face repository and SHA-256 recorded. tests/test_docs.py checks the manifest the same way.

Needs: Python 3, Node with Playwright and Chromium (npm ci && npx playwright install chromium), ffmpeg with libx264,
and for terminal recordings a Unix terminal (Linux or macOS). Writes only inside --out and a temporary folder.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MEDIA = ROOT / "docs" / "media"
sys.path.insert(0, str(ROOT / "utils"))

KINDS = ("screenshot", "video", "gif", "terminal")
MAX_BYTES = {".png": 1_500_000, ".jpg": 1_500_000, ".jpeg": 1_500_000, ".webp": 1_500_000, ".svg": 1_000_000,
             ".gif": 6_000_000, ".mp4": 8_000_000, ".webm": 8_000_000, ".cast": 1_000_000}
SIZE = (1280, 800)           # browser videos and screenshots (CSS pixels; screenshots are taken at 2x)
FPS = 25
WAIT_TARGET_S = 4            # a long wait is sped up to last about this long
MIN_WAIT_S = 8               # waits shorter than this play at real speed
IDLE_LIMIT_S = 2.0           # terminal pauses longer than this are shortened to it
CARD_S = 2.5


# --- What may be published ---------------------------------------------------------------------------------------
def llama_problem(path: str, version_text: str) -> str:
    """'' when `path` is a real llama-server; otherwise why a capture made with it would not show the real program."""
    if not path:
        return "no llama-server was found (the setup page's Get llama.cpp, or set LLAMA_SERVER)"
    p = Path(path)
    tests = ROOT / "tests"
    if "fake" in version_text.lower() or "fake_llama_server" in p.name:
        return "llama-server says it is a fake (tests/fake_llama_server.py or another stand-in), not llama.cpp"
    if p.parts[:1] == ("tests",) or tests in p.resolve().parents:
        return f"llama-server at {path} is inside tests/, where the test suite's fake lives"
    if not re.search(r"version:\s*\d+", version_text):
        return f"{path} did not print a version (llama-server --version)"
    return ""


def publish_problem(out_dir: Path, llama: str) -> str:
    """Refuse to write into docs/media/ with anything but a real llama-server; a trial run elsewhere may."""
    out = Path(out_dir).resolve()
    if llama and (out == MEDIA.resolve() or MEDIA.resolve() in out.parents):
        return f"refusing to write to docs/media: {llama}"
    return ""


def entry_problems(entry: dict, runs: dict) -> list:
    """Everything an entry of docs/media/manifest.json lacks to say truthfully how its file was made."""
    name = entry.get("file") or "?"
    problems = []
    if not entry.get("file"):
        problems.append("an entry has no file")
    if entry.get("kind") not in KINDS:
        problems.append(f"{name}: kind {entry.get('kind')!r} is not one of {', '.join(KINDS)}")
    if not str(entry.get("shows") or "").strip():
        problems.append(f"{name}: no 'shows' text saying what it shows")
    for s in entry.get("speedup") or []:
        if not (s.get("what") and isinstance(s.get("real_s"), (int, float)) and isinstance(s.get("factor"), (int, float))
                and s["factor"] > 1):
            problems.append(f"{name}: a speedup must say what was sped up, its real seconds and its speed factor")
    run = runs.get(entry.get("run"))
    if run is None:
        problems.append(f"{name}: run {entry.get('run')!r} is not in the manifest's runs")
        return problems
    if not re.match(r"\d{4}-\d{2}-\d{2}", str(run.get("date") or "")):
        problems.append(f"{name}: its run has no date")
    machine = run.get("machine") or {}
    for key in ("os", "cpu", "ram_gb", "gpu"):
        if machine.get(key) in (None, ""):
            problems.append(f"{name}: its run does not record the machine's {key}")
    server = run.get("llama_server") or {}
    why = llama_problem(server.get("path") or "", server.get("version") or "")
    if why:
        problems.append(f"{name}: {why}")
    for m in run.get("models") or []:
        label = m.get("file") or "a model"
        if not re.fullmatch(r"[0-9a-f]{64}", str(m.get("sha256") or "")):
            problems.append(f"{name}: {label} has no sha256")
        if not m.get("repo"):
            problems.append(f"{name}: {label} has no Hugging Face repo")
    return problems


def write_manifest(path: Path, run_id: str, run: dict, captures: list) -> None:
    """Add this run's captures, replacing older entries for the same files; drop runs no entry uses any more."""
    try:
        m = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        m = {}
    m.setdefault("about", "How each file in docs/media was made. Written by tools/docs-media/capture.py; "
                          "checked by tests/test_docs.py.")
    made = {c["file"] for c in captures}
    kept = [c for c in m.get("captures", []) if c.get("file") not in made]
    m["captures"] = sorted(kept + [dict(c, run=run_id) for c in captures], key=lambda c: c["file"])
    runs = dict(m.get("runs", {}), **{run_id: run})
    used = {c["run"] for c in m["captures"]}
    m["runs"] = {k: v for k, v in sorted(runs.items()) if k in used}
    Path(path).write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --- The machine and the run -------------------------------------------------------------------------------------
def machine(hw, os_name: str, arch: str, cpu: str) -> dict:
    """Hardware facts for the manifest: no host name, user name or address."""
    if hw.gpu_kind == "none":
        gpu = "none"
    else:
        size = f", {hw.vram_mb / 1024:.1f} GB" if hw.vram_mb else ""
        gpu = hw.gpu_name + size + (", used by llama.cpp" if hw.gpu_usable else ", not used by this llama.cpp build")
    return {"os": os_name, "arch": arch, "cpu": cpu, "threads": hw.cores, "ram_gb": round(hw.ram_mb / 1024, 1),
            "gpu": gpu}


def caption(run: dict) -> str:
    """One line for under a picture: when, on what, with which llama.cpp and model."""
    m = run["machine"]
    gpu = "no GPU" if m["gpu"] == "none" else m["gpu"]
    build = re.search(r"version:\s*(\d+)", run["llama_server"]["version"])
    models = ", ".join(x["file"] for x in run.get("models") or []) or "no model"
    return (f"Recorded {run['date']} on {m['os']} ({m['cpu']}, {m['threads']} threads, {m['ram_gb']} GB RAM, {gpu}) "
            f"with llama.cpp {build.group(1) if build else '?'} and {models}.")


def model_record(path: Path) -> dict:
    """A model file as the manifest lists it: its Hugging Face repo (the .source file the downloader writes), SHA-256."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    source = path.with_name(path.name + ".source")
    repo = source.read_text(encoding="utf-8").strip() if source.exists() else ""
    return {"file": path.name, "repo": repo, "sha256": h.hexdigest(), "bytes": path.stat().st_size}


def shown_path(path: str) -> str:
    """A path for the manifest: relative to the project, or with the home folder as ~ (no user name)."""
    p = Path(path).resolve()
    if ROOT in p.parents:
        return p.relative_to(ROOT).as_posix()
    home = Path.home()
    return "~/" + p.relative_to(home).as_posix() if home in p.parents else str(p)


# --- Words --------------------------------------------------------------------------------------------------------
def duration_text(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s} s" if s < 60 else f"{s // 60} min {s % 60} s"


def speedup_note(what: str, real_s: float, factor: int) -> str:
    return f"{what} took {duration_text(real_s)}. Shown {factor}x faster."


# --- ffmpeg (argument lists, never a shell) ----------------------------------------------------------------------
def _encode(fps=FPS):
    return ["-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-an"]


def segment_args(src, dst, start: float, end: float, factor: int, size=SIZE, fps=FPS) -> list:
    """Cut [start, end) seconds out of a recording, sped up `factor` times, in the format every segment shares."""
    pts = "setpts=PTS-STARTPTS" if factor == 1 else f"setpts=(PTS-STARTPTS)/{factor}"
    return (["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(src),
             "-filter:v", f"{pts},fps={fps},scale={size[0]}:{size[1]}:flags=lanczos,format=yuv420p"]
            + _encode(fps) + [str(dst)])


def card_args(png, seconds: float, dst, size=SIZE, fps=FPS) -> list:
    """A still card (a PNG) held for `seconds`, in the same format as the segments around it."""
    return (["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-t", str(seconds),
             "-vf", f"scale={size[0]}:{size[1]}:flags=lanczos,format=yuv420p"] + _encode(fps) + [str(dst)])


def concat_list(paths) -> str:
    """The list file for ffmpeg's concat demuxer, with forward slashes (ffmpeg reads them on every OS); a quote in a
    path is written as '\\''."""
    return "".join("file '" + p.as_posix().replace("'", "'\\''") + "'\n" for p in paths)


def mp4_args(src, dst, concat: bool = False) -> list:
    """The published MP4: H.264, yuv420p and faststart so browsers and GitHub play it; no audio (there is none)."""
    return (["ffmpeg", "-y", "-loglevel", "error"] + (["-f", "concat", "-safe", "0"] if concat else [])
            + ["-i", str(src), "-c:v", "libx264", "-preset", "slow", "-crf", "26", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", "-an", str(dst)])


def gif_args(src, dst, fps: int = 10, width: int = 960) -> list:
    """A looping GIF with a palette made for this clip (a shared 256-colour palette blurs text)."""
    graph = (f"[0:v]fps={fps},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];"
             f"[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
    return ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-filter_complex", graph, "-loop", "0", str(dst)]


def plan_segments(length: float, waits: list, target_s: float = WAIT_TARGET_S, min_wait_s: float = MIN_WAIT_S) -> list:
    """Split a recording of `length` seconds: long waits sped up to about `target_s`, everything else at real speed."""
    plan, at = [], 0.0
    for w in sorted(waits, key=lambda w: w["start"]):
        start, end = max(at, float(w["start"])), min(length, float(w["end"]))
        if end - start < min_wait_s:
            continue
        if start > at:
            plan.append({"start": at, "end": start, "factor": 1})
        plan.append({"start": start, "end": end, "factor": max(2, math.ceil((end - start) / target_s)),
                     "what": w["what"]})
        at = end
    if length > at:
        plan.append({"start": at, "end": length, "factor": 1})
    return plan


# --- Terminal recordings (asciicast v2: https://docs.asciinema.org/manual/asciicast/v2/) --------------------------
class Cast:
    def __init__(self, cols: int, rows: int, title: str, home: str = ""):
        self.cols, self.rows, self.title, self.home = cols, rows, title, home
        self.events, self.last, self.redacted = [], 0.0, False

    def add(self, t: float, data: str) -> None:
        self.last = max(self.last, float(t))                # output never goes back in time
        if self.home and self.home in data:
            data, self.redacted = data.replace(self.home, "~"), True
        self.events.append([round(self.last, 6), "o", data])

    def text(self) -> str:
        head = {"version": 2, "width": self.cols, "height": self.rows, "title": self.title,
                "env": {"TERM": "xterm-256color"}, "idle_time_limit": IDLE_LIMIT_S}
        return "\n".join(json.dumps(x, ensure_ascii=False) for x in [head] + self.events) + "\n"


ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][0-9A-Za-z]|\x1b[=>]")


class Terminal:
    """An interactive bash in a real pseudo-terminal of a fixed size, recorded as it runs; commands are typed into it
    as a person would. Unix only (pty, termios)."""

    def __init__(self, cast: Cast, env: dict, cwd: Path):
        import fcntl
        import pty
        import struct
        import termios
        self.cast, self.screen = cast, ""
        env = dict(env, TERM="xterm-256color", PS1="$ ", COLUMNS=str(cast.cols), LINES=str(cast.rows))
        env.pop("PROMPT_COMMAND", None)
        self.pid, self.master = pty.fork()                  # the child gets the terminal as its controlling one
        if self.pid == 0:
            os.chdir(str(cwd))
            os.execvpe("bash", ["bash", "--norc", "--noprofile", "-i"], env)
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", cast.rows, cast.cols, 0, 0))
        self.t0 = time.monotonic()
        self.lock = threading.Lock()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.expect("$ ", 15)

    def _read(self):
        # Always drained, so a chatty program (llama-server's log) never blocks on a full terminal.
        while True:
            try:
                data = os.read(self.master, 65536)
            except OSError:
                return
            if not data:
                return
            text = data.decode("utf-8", "replace")
            with self.lock:
                self.cast.add(time.monotonic() - self.t0, text)
                self.screen = (self.screen + ANSI.sub("", text))[-20000:]

    def expect(self, needle: str, timeout: float, after: int = 0) -> int:
        """Wait until `needle` is on screen after position `after`; -> the position just past it."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self.lock:
                at = self.screen.find(needle, after)
                if at >= 0:
                    return at + len(needle)
            if not self.reader.is_alive():
                break
            time.sleep(0.05)
        raise RuntimeError(f"the terminal never showed {needle!r}; last output:\n{self.screen[-1500:]}")

    def mark(self) -> int:
        with self.lock:
            return len(self.screen)

    def type(self, keys: str, pause: float = 0.6) -> None:
        time.sleep(pause)                                   # a person's pace, so the recording can be followed
        os.write(self.master, keys.encode())

    def run(self, command: str) -> int:
        """Type a command at the prompt, a key at a time, and press Enter. -> screen position where its output starts."""
        time.sleep(0.8)
        for ch in command:
            os.write(self.master, ch.encode())
            time.sleep(0.04)
        start = self.mark()
        self.type("\r", 0.4)
        return start

    def now(self) -> float:
        return time.monotonic() - self.t0

    def stop(self) -> None:
        """Ctrl+C, then exit the shell, as a person would; killed only if that does not end it."""
        import signal
        for keys, wait in (("\x03", 5), ("exit\r", 5)):
            try:
                os.write(self.master, keys.encode())
            except OSError:
                break
            end = time.monotonic() + wait
            while time.monotonic() < end and os.waitpid(self.pid, os.WNOHANG) == (0, 0):
                time.sleep(0.1)
            if not self.alive():
                break
        if self.alive():
            os.killpg(self.pid, signal.SIGKILL)
            os.waitpid(self.pid, 0)
        self.reader.join(2)
        os.close(self.master)

    def alive(self) -> bool:
        try:
            return os.waitpid(self.pid, os.WNOHANG) == (0, 0)
        except ChildProcessError:
            return False


def cut_cast(cast: Cast, until_t: float) -> Cast:
    """The recording up to `until_t` seconds (the moment the scene was over), for publishing."""
    out = Cast(cast.cols, cast.rows, cast.title)
    out.events = [e for e in cast.events if e[0] <= until_t]
    return out


# --- Running the scenes -------------------------------------------------------------------------------------------
SCENES = {
    "setup": "Setup page, end to end: use -> recommended model -> download -> speed test -> Start chatting -> a reply",
    "views": "Setup page views: Installed tools, Get llama.cpp, My models, Model radar",
    "detect": "Terminal: detect-tools.sh",
    "serve": "Terminal: serve.sh menu (model, then Tasks), then the Tasks page: summarize, explain code, rewrite",
    "translate": "The Translation page, served by serve.sh with UI=translation",
}
LAUNCHER = "scripts/unix" if os.name != "nt" else "scripts/win"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def missing(need_terminal: bool) -> list:
    """Every program this capture needs and could not find or run (CLAUDE.md rules 3 and 5: say what is missing)."""
    out = []
    if not shutil.which("ffmpeg"):
        out.append("ffmpeg (https://ffmpeg.org/download.html)")
    elif "libx264" not in subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True,
                                         text=True).stdout:
        out.append("an ffmpeg built with libx264")
    if not shutil.which("node"):
        out.append("Node.js (https://nodejs.org)")
    elif subprocess.run(["node", "-e", "require('playwright').chromium.executablePath()"], cwd=str(ROOT),
                        capture_output=True).returncode != 0:
        out.append("Playwright with Chromium (npm ci && npx playwright install chromium)")
    elif not (ROOT / "node_modules" / "@xterm" / "xterm" / "lib" / "xterm.js").exists() and need_terminal:
        out.append("xterm.js, to draw terminal recordings (npm ci)")
    if need_terminal and os.name == "nt":
        out.append("a Unix terminal: terminal scenes record a pseudo-terminal (run them on Linux or macOS)")
    return out


def llama_server() -> tuple:
    """(path, --version output) of the llama-server the project itself would use (hardware.find_llama_server)."""
    import hardware
    path = hardware.find_llama_server()
    if not path:
        return "", ""
    done = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=60)
    return path, (done.stdout + done.stderr).strip()


def node(script: str, *args, timeout=3600) -> list:
    """Run one of this folder's Node scripts; it prints one JSON object per line, and errors on stderr."""
    done = subprocess.run(["node", str(HERE / script)] + [str(a) for a in args], cwd=str(ROOT), capture_output=True,
                          text=True, timeout=timeout)
    if done.returncode != 0:
        raise RuntimeError(f"{script} failed (exit {done.returncode}):\n{done.stderr[-3000:]}")
    return [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]


def run(args_list: list, what: str) -> None:
    done = subprocess.run(args_list, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"{what} failed: {done.stderr[-2000:]}")


def edit_video(video: dict, work: Path, out: Path) -> list:
    """A recorded clip -> MP4 and GIF, long waits sped up with a card that says so. -> manifest entries."""
    src = Path(video["webm"])
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
                           capture_output=True, text=True)
    length = float(probe.stdout.strip() or video["length"])
    size = tuple(video.get("size") or SIZE)
    lead = float(video.get("start") or 0)                   # the blank moment before the scene began
    waits = [dict(w, start=w["start"] - lead, end=w["end"] - lead) for w in video.get("waits", [])]
    parts, speedup = [], []
    for i, seg in enumerate(plan_segments(length - lead, waits)):
        if seg["factor"] > 1:
            note = speedup_note(seg["what"], seg["end"] - seg["start"], seg["factor"])
            png = work / f"{video['name']}-card{i}.png"
            node("render.js", "card", png, note, *size)
            parts.append(work / f"{video['name']}-card{i}.mp4")
            run(card_args(png, CARD_S, parts[-1], size=size), "card")
            speedup.append({"what": seg["what"], "real_s": round(seg["end"] - seg["start"], 1),
                            "factor": seg["factor"]})
        parts.append(work / f"{video['name']}-{i}.mp4")
        run(segment_args(src, parts[-1], seg["start"] + lead, seg["end"] + lead, seg["factor"], size=size), "cut")
    listing = work / f"{video['name']}.txt"
    listing.write_text(concat_list(parts), encoding="utf-8")
    mp4, gif = out / f"{video['name']}.mp4", out / f"{video['name']}.gif"
    run(mp4_args(listing, mp4, concat=True), "mp4")
    for fps, width in ((10, 960), (8, 800), (6, 640)):        # smallest GIF that still reads, within MAX_BYTES
        run(gif_args(mp4, gif, fps=fps, width=width), "gif")
        if gif.stat().st_size <= MAX_BYTES[".gif"]:
            break
    extra = {"speedup": speedup} if speedup else {}
    return [dict({"file": mp4.name, "kind": "video", "shows": video["shows"]}, **extra),
            dict({"file": gif.name, "kind": "gif", "shows": video["shows"]}, **extra)]


def record_terminal(name: str, shows: str, steps, env: dict, work: Path, out: Path, rows: int = 28,
                    keep=None) -> list:
    """A shell in a terminal; `steps(term)` types into it. Published as .cast, MP4, GIF and the last frame as PNG.
    `keep(term)` runs after the recording ends but before the shell is stopped (the serve scene uses the server it
    started). Settings passed through the environment rather than typed are listed in the entries ("env")."""
    cast = Cast(100, rows, name, home=str(Path.home()))
    term = Terminal(cast, env, ROOT)
    try:
        steps(term)
        time.sleep(1.5)
        until = term.now()
        if keep:
            keep(term)
    finally:
        term.stop()
    path = out / f"{name}.cast"
    path.write_text(cut_cast(cast, until).text(), encoding="utf-8")
    drawn = node("render.js", "cast", path, work / f"{name}-term", out / f"{name}.png")[0]
    video = dict(drawn, name=name, shows=shows, length=until, waits=[])
    notes = {"idle_limit_s": IDLE_LIMIT_S, "env": {k: env[k] for k in HIDDEN_ENV if k in env}}
    if cast.redacted:
        notes["edits"] = ["the home folder is shown as ~"]
    entries = [{"file": path.name, "kind": "terminal", "shows": shows},
               {"file": f"{name}.png", "kind": "screenshot", "shows": shows + " (last frame)"}]
    return [dict(e, **notes) for e in entries + edit_video(video, work, out)]


# Set for every scene, so nothing waits on a browser window or a network check and no running llama-server is
# stopped; listed in the manifest next to each terminal recording.
HIDDEN_ENV = ("OPEN_BROWSER", "KILL_EXISTING", "CHECK_DAYS")


def menu_keys(term: Terminal, title: str, label: str, after: int) -> str:
    """Arrow-down presses, then Enter, to reach the row starting with `label` in a serve.sh menu, counted from what
    the menu printed (never assumed: rule 6)."""
    with term.lock:
        text = term.screen[after:]
    menu = text[text.find(title):].splitlines()[1:]
    rows = []
    for line in menu:
        line = line.replace("❯", " ").strip()
        if not line and rows:
            break
        if line:
            rows.append(line)
    hits = [i for i, row in enumerate(rows) if row.startswith(label)]
    if not hits:
        raise RuntimeError(f"{label!r} is not in serve.sh's {title!r} menu: {rows}")
    return "\x1b[B" * hits[0] + "\r"


def capture(scenes: list, out: Path, work: Path, used_models: set, chosen: str = "") -> list:
    """Run the scenes; -> manifest entries. Raises RuntimeError naming what went wrong."""
    import model_setup
    entries = []
    env = dict(os.environ, OPEN_BROWSER="0", KILL_EXISTING="0", CHECK_DAYS="0")
    if "setup" in scenes or "views" in scenes:
        port = free_port()
        ui = subprocess.Popen([sys.executable, str(ROOT / "utils" / "model_setup.py"), "--ui", "--port", str(port),
                               "--no-browser"], cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)
        try:
            base = f"http://127.0.0.1:{port}/"
            for _ in range(200):
                try:
                    socket.create_connection(("127.0.0.1", port), 0.2).close()
                    break
                except OSError:
                    time.sleep(0.1)
            for item in node("scenes.js", "setup-page", base, work, out, ",".join(s for s in scenes
                                                                                  if s in ("setup", "views"))):
                entries += edit_video(item, work, out) if item.get("webm") else [item]
            installed = model_setup.state_get("installed")
            if "setup" in scenes and installed:
                used_models.add(installed)
        finally:
            ui.terminate()
            ui.wait(10)
    if "detect" in scenes:
        def detect(t):
            start = t.run(f"./{LAUNCHER}/detect-tools.sh")
            t.expect("$ ", 120, t.expect("Unsloth", 120, start))
        entries += record_terminal("terminal-detect-tools", "detect-tools.sh lists the local AI tools it finds",
                                   detect, env, work, out, rows=12)
    for ui_name, scene in (("tasks", "serve"), ("translation", "translate")):
        if scene not in scenes:
            continue
        model = pick_model(used_models, chosen)
        port = 8080 if port_free(8080) else free_port()      # the default, when nothing else holds it
        command = ("" if port == 8080 else f"PORT={port} ") + ("UI=translation " if ui_name == "translation" else "")
        command += f"./{LAUNCHER}/serve.sh"

        def steps(t, ui_name=ui_name, model=model, command=command):
            start = t.run(command)
            t.expect("Choose a model", 60, start)
            t.type(menu_keys(t, "Choose a model", model.name, start), 1.2)
            if ui_name == "tasks":
                t.expect("Choose an interface", 60, start)
                t.type(menu_keys(t, "Choose an interface", "Tasks", start), 1.2)
            t.expect("server is listening", 900, start)

        def keep(t, ui_name=ui_name, port=port):
            for item in node("scenes.js", ui_name, f"http://127.0.0.1:{port}/", work, out, ""):
                entries.extend(edit_video(item, work, out) if item.get("webm") else [item])

        senv = dict(env, MODELS_DIR=str(model.parent))
        name = "terminal-serve" if ui_name == "tasks" else "terminal-serve-translation"
        shows = (f"serve.sh: choose {model.name}, then the Tasks interface; llama-server starts" if ui_name == "tasks"
                 else f"UI=translation serve.sh: choose {model.name}; llama-server starts")
        entries += record_terminal(name, shows, steps, senv, work, out, keep=keep)
        used_models.add(model.stem)
    return entries


def port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def pick_model(used: set, chosen: str = "") -> Path:
    """The model the scenes chat with: --model, else the one the setup scene installed, else the setup page's
    'installed' model. It has to be in the models folder, because serve.sh lists only that folder."""
    import model_setup
    models = Path(os.environ.get("MODELS_DIR") or ROOT / "models")
    names = [Path(chosen).stem] if chosen else list(used) + [model_setup.state_get("installed")]
    for stem in names:
        if stem and (models / f"{stem}.gguf").exists():
            return models / f"{stem}.gguf"
    looked = ", ".join(f"{n}.gguf" for n in names if n) or "no model named"
    raise RuntimeError(f"no model to chat with in {models} (looked for: {looked}); run the setup scene first, "
                       f"or pass --model FILE")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=MEDIA, help="where to write (default docs/media)")
    p.add_argument("--only", action="append", choices=sorted(SCENES), help="capture only this scene (repeatable)")
    p.add_argument("--model", metavar="FILE", default="", help="the .gguf in the models folder to chat with "
                   "(default: the one the setup scene installed)")
    p.add_argument("--list", action="store_true", help="show the scenes and what is missing, capture nothing")
    a = p.parse_args(argv)
    scenes = a.only or list(SCENES)
    terminal = any(s in scenes for s in ("detect", "serve", "translate"))
    path, version = llama_server()
    llama = llama_problem(path, version)
    lacking = missing(terminal)
    if a.list:
        for name, text in SCENES.items():
            print(f"  {name:10} {text}")
        print(f"\nllama-server: {path or 'not found'}" + (f" ({version.splitlines()[0]})" if version else ""))
        for why in ([llama] if llama else []) + lacking:
            print(f"  missing: {why}")
        return 0 if not (llama or lacking) else 1
    refuse = publish_problem(a.out, llama)
    if refuse or lacking:
        for why in ([refuse] if refuse else []) + lacking:
            print(f"capture: {why}", file=sys.stderr)
        return 2
    import hardware
    hw = hardware.detect_hw()
    a.out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="lp-capture-"))
    used = set()
    try:
        entries = capture(scenes, a.out, work, used, a.model)
    except RuntimeError as e:
        print(f"capture: {e}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(work, True)
    models = Path(os.environ.get("MODELS_DIR") or ROOT / "models")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), capture_output=True,
                            text=True).stdout.strip()
    run_rec = {"date": dt.date.today().isoformat(), "launchpad_commit": commit,
               "machine": machine(hw, f"{platform.system()} {platform.release()}", platform.machine(),
                                  hardware.read_cpu_name()),
               "llama_server": {"version": version, "path": shown_path(path)},
               "models": [model_record(models / f"{s}.gguf") for s in sorted(used) if (models / f"{s}.gguf").exists()]}
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_manifest(a.out / "manifest.json", run_id, run_rec, entries)
    problems = [x for e in entries for x in entry_problems(dict(e, run=run_id), {run_id: run_rec})]
    print(f"capture: {len(entries)} files in {a.out}\n  {caption(run_rec)}")
    for why in problems:
        print(f"  not publishable: {why}", file=sys.stderr)
    return 1 if problems and publish_problem(a.out, "x") else 0


if __name__ == "__main__":
    sys.exit(main())
