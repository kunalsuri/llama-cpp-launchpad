"""llama-cpp-launchpad: install llama.cpp from the setup page, when no working llama-server was found or the one
found cannot use this computer's GPU.

  Windows, Linux  download the build that fits this machine (CUDA for NVIDIA, Vulkan for another GPU, else CPU) from
                  the official ggml-org/llama.cpp GitHub releases, over HTTPS, and unpack it into the project's bin/
                  folder. No admin rights, nothing system-wide. CUDA builds come with the CUDA runtime archive the
                  release publishes next to them.
  macOS           run `brew install llama.cpp`, only if Homebrew was found. Otherwise the page keeps its instructions.

Checks: the release listing must point at github.com/ggml-org/llama.cpp/releases/download/...; redirects may only go
to GitHub's own download hosts over HTTPS; the size must match the listing; the SHA-256 must match when GitHub
publishes one for the asset (its "digest" field), and the page says so when none is published; the unpacked
llama-server must answer `--version` before anything is moved into bin/. Archives that would write outside bin/ are
refused. Work happens in bin/.launchpad-install, which is removed afterwards.

Python standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

REPO = "ggml-org/llama.cpp"
LATEST_RELEASE = f"https://api.github.com/repos/{REPO}/releases/latest"
# llama.cpp publishes binaries in bNNNN releases marked prerelease (release-publish.yml); /releases/latest skips
# those and returns the stable vX.Y release, whose only asset is nightly-tag.txt naming the bNNNN release with the
# binaries (make-release.yml). So: follow that tag, else take the newest listed release that has a build.
RELEASE_BY_TAG = f"https://api.github.com/repos/{REPO}/releases/tags/{{tag}}"
RELEASES_LIST = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
NIGHTLY_TAG_FILE = "nightly-tag.txt"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
REDIRECT_HOSTS = ("github.com",)
REDIRECT_SUFFIX = ".githubusercontent.com"
STAGING = ".launchpad-install"
USER_AGENT = "llama-cpp-launchpad"
BREW_CMD = ["install", "llama.cpp"]
KIND_LABEL = {"cuda": "CUDA build for your NVIDIA graphics card", "vulkan": "Vulkan build for your graphics card",
              "cpu": "CPU build"}


# --- Choosing the archive ----------------------------------------------------------------------------
def arch_of(machine: str) -> str:
    m = (machine or "").lower()
    if m in ("x86_64", "amd64", "x64"):
        return "x64"
    if m in ("aarch64", "arm64"):
        return "arm64"
    return ""


def download_url_ok(url: str) -> bool:
    """Only https://github.com/ggml-org/llama.cpp/releases/download/<tag>/<file>."""
    return url.startswith(DOWNLOAD_PREFIX) and urlparse(url).hostname == "github.com" and ".." not in url


def redirect_ok(url: str) -> bool:
    """GitHub sends release downloads on to its own storage hosts; nowhere else, and never over plain HTTP."""
    u = urlparse(url)
    host = u.hostname or ""
    return u.scheme == "https" and (host in REDIRECT_HOSTS or host.endswith(REDIRECT_SUFFIX))


def _version_key(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def plan(release: dict, system: str, machine: str, gpu_kind: str, variant: str = "auto", cuda_max: str = "") -> dict:
    """The archive(s) for this machine -> {"kind", "tag", "assets", "why"} or {"error": text}.
    cuda_max: the newest CUDA the NVIDIA driver runs (nvidia-smi's "CUDA Version"), "" if unknown. A CUDA build newer
    than that would not start, so only builds at or below it are used; unknown keeps the oldest build."""
    arch = arch_of(machine)
    if system not in ("Windows", "Linux"):
        return {"error": "Release downloads are used on Windows and Linux only."}
    if not arch:
        return {"error": f"There is no llama.cpp release build for this processor ({machine})."}
    assets = [a for a in release.get("assets") or [] if isinstance(a, dict) and download_url_ok(str(a.get("browser_download_url", "")))]
    by_name = {a["name"]: a for a in assets if isinstance(a.get("name"), str)}
    tag = str(release.get("tag_name") or "")
    plat, ext = ("win", r"\.zip") if system == "Windows" else ("ubuntu", r"\.tar\.gz")
    t = re.escape(tag)

    def one(pattern):
        return next((a for n, a in sorted(by_name.items()) if re.fullmatch(pattern, n)), None)

    wanted = ["cpu"] if variant == "cpu" else {"nvidia": ["cuda", "vulkan", "cpu"], "gpu": ["vulkan", "cpu"]}.get(gpu_kind, ["cpu"])
    notes = []
    for kind in wanted:
        if kind == "cuda":
            builds = {}
            for n in by_name:
                m = re.fullmatch(rf"llama-{t}-bin-{plat}-cuda-(\d+(?:\.\d+)*)-{arch}{ext}", n)
                if m:
                    builds[m.group(1)] = by_name[n]
            limit = _version_key(cuda_max) if re.fullmatch(r"\d+(?:\.\d+)*", cuda_max or "") else None
            too_new = []
            for ver in sorted(builds, key=_version_key):         # oldest CUDA first: it runs on the oldest drivers
                if limit is not None and _version_key(ver) > limit:
                    too_new.append(ver)
                    continue
                rt = (rf"cudart-llama-bin-win-cuda-{re.escape(ver)}-{arch}\.zip" if system == "Windows"
                      else rf"cudart-llama-{t}-bin-ubuntu-cuda-{re.escape(ver)}-{arch}\.tar\.gz")
                runtime = one(rt)
                if runtime:
                    known = (f" (your driver runs CUDA up to {cuda_max})" if limit is not None
                             else " (your driver's CUDA version is not known, so the oldest build was chosen)")
                    return {"kind": "cuda", "tag": tag, "assets": [builds[ver], runtime],
                            "why": f"CUDA {ver} build, for your NVIDIA graphics card{known}."}
            if too_new:
                notes.append(f"Your NVIDIA driver runs CUDA up to {cuda_max}, but this release's CUDA builds need "
                             f"{' or '.join(too_new)}. Update the NVIDIA driver to get the CUDA build.")
            else:
                notes.append("No CUDA build with its CUDA runtime archive was found in this release.")
        elif kind == "vulkan":
            a = one(rf"llama-{t}-bin-{plat}-vulkan-{arch}{ext}")
            if a:
                return {"kind": "vulkan", "tag": tag, "assets": [a], "why": " ".join(notes + ["Vulkan build, for your graphics card."])}
            notes.append("No Vulkan build was found in this release.")
        else:
            cpu = rf"llama-{t}-bin-win-cpu-{arch}\.zip" if system == "Windows" else rf"llama-{t}-bin-ubuntu-{arch}\.tar\.gz"
            a = one(cpu)
            if a:
                return {"kind": "cpu", "tag": tag, "assets": [a], "why": " ".join(notes + ["CPU build."])}
    return {"error": f"The latest llama.cpp release ({tag or 'unknown'}) has no build for {system} {arch}. " + " ".join(notes)}


# --- Downloading and checking ------------------------------------------------------------------------
class _GitHubOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not redirect_ok(newurl):
            raise urllib.error.URLError(f"refused a redirect to {urlparse(newurl).hostname or newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str, accept: str = "*/*"):
    opener = urllib.request.build_opener(_GitHubOnly)
    return opener.open(urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept}), timeout=60)


def http_json(url: str):
    with _open(url, "application/vnd.github+json") as r:
        return json.loads(r.read().decode("utf-8"))


def http_text(url: str) -> str:
    """A small text asset of the official release (nightly-tag.txt): at most 1 KB is read."""
    if not download_url_ok(url):
        raise urllib.error.URLError(f"not an official llama.cpp release download: {url}")
    with _open(url) as r:
        return r.read(1024).decode("utf-8", "replace")


def find_release(fetch_json, fetch_text, system, machine, gpu_kind, variant="auto", cuda_max="", say=None) -> dict:
    """The release and archive(s) for this machine -> plan(), with "release" naming where it came from.
    1. /releases/latest (has the build only if llama.cpp ever publishes binaries there);
    2. the bNNNN release its nightly-tag.txt names (llama.cpp's current layout);
    3. the newest of the last 20 releases, prereleases included, that has a build for this machine."""
    say = say or (lambda _msg: None)

    def try_release(rel, label):
        p = plan(rel if isinstance(rel, dict) else {}, system, machine, gpu_kind, variant, cuda_max=cuda_max)
        if "error" not in p:
            p["release"] = label
        return p

    say(f"Looking up the latest release: {LATEST_RELEASE}")
    latest = fetch_json(LATEST_RELEASE)
    first = try_release(latest, str((latest or {}).get("tag_name") or "latest"))
    if "error" not in first:
        return first
    latest = latest if isinstance(latest, dict) else {}
    stable = str(latest.get("tag_name") or "")
    tag_asset = None
    for a in latest.get("assets") or []:
        if isinstance(a, dict) and a.get("name") == NIGHTLY_TAG_FILE and download_url_ok(str(a.get("browser_download_url", ""))):
            tag_asset = a
    if tag_asset:
        try:
            nightly = fetch_text(tag_asset["browser_download_url"]).strip()
        except (OSError, ValueError):
            nightly = ""
        if re.fullmatch(r"b\d+", nightly):
            say(f"Release {stable} has no binaries itself; its {NIGHTLY_TAG_FILE} names {nightly}")
            try:
                found = try_release(fetch_json(RELEASE_BY_TAG.format(tag=nightly)), f"{nightly} (the binaries of {stable})")
                if "error" not in found:
                    return found
            except (OSError, ValueError):
                pass
        else:
            say(f"{NIGHTLY_TAG_FILE} of {stable} does not name a bNNNN release: ignored")
    say(f"Looking through the latest releases: {RELEASES_LIST}")
    try:
        listing = fetch_json(RELEASES_LIST)
    except (OSError, ValueError):
        listing = []
    for rel in listing if isinstance(listing, list) else []:
        if isinstance(rel, dict) and not rel.get("draft"):
            found = try_release(rel, str(rel.get("tag_name") or "?"))
            if "error" not in found:
                return found
    return {"error": f"No recent llama.cpp release has a build for this computer. {first['error']}"}


def fetch_file(url: str, dest: Path, on_progress=None) -> None:
    if not download_url_ok(url):
        raise urllib.error.URLError(f"not an official llama.cpp release download: {url}")
    with _open(url) as r, open(dest, "wb") as out:
        done = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def server_version(argv: list, timeout: int = 60) -> tuple:
    """Run `llama-server --version` -> (it ran and printed a version, its output)."""
    env = dict(os.environ)
    libdir = str(Path(argv[0]).parent)              # release builds keep their libraries next to llama-server
    for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        env[var] = libdir + (os.pathsep + env[var] if env.get(var) else "")
    try:
        done = subprocess.run(list(argv) + ["--version"], capture_output=True, text=True, timeout=timeout, env=env,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    out = (done.stdout + done.stderr).strip()
    return done.returncode == 0 and bool(re.search(r"version", out, re.I)), out


def why_install(found: str, works: bool, hw) -> str:
    """Why the page offers to install llama.cpp: "missing", "broken", "no-gpu", or "" (nothing to do)."""
    if not found:
        return "missing"
    if not works:
        return "broken"
    if hw.gpu_kind in ("nvidia", "gpu") and not hw.gpu_usable:
        return "no-gpu"
    if getattr(hw, "other_gpu", "") and not getattr(hw, "other_gpu_usable", False):     # AMD / Intel Arc
        return "no-gpu"
    return ""


# --- Unpacking ----------------------------------------------------------------------------------------
class UnsafeArchive(Exception):
    pass


def _clean(name: str) -> PurePosixPath:
    name = name.replace("\\", "/")
    p = PurePosixPath(name)
    if not name or name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in p.parts:
        raise UnsafeArchive(f"unsafe path in the archive: {name}")
    return p


def _strip_top(paths: list) -> list:
    """Release tarballs wrap everything in one folder (llama-b1234/...): unpack its contents, not the folder."""
    firsts = {p.parts[0] for p in paths if p.parts}
    if len(firsts) == 1 and all(len(p.parts) > 1 for p in paths):     # a lone file at the top is a file, not a folder
        return [PurePosixPath(*p.parts[1:]) for p in paths]
    return paths


def extract(archive: Path, dest: Path) -> None:
    """Unpack a release archive into dest. Refuses absolute paths, '..', and links that point outside the folder."""
    dest.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            rels = _strip_top([_clean(i.filename) for i in infos])
            for info, rel in zip(infos, rels):
                if not rel.parts:
                    continue
                target = dest.joinpath(*rel.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                mode = (info.external_attr >> 16) & 0o777
                if os.name != "nt":
                    os.chmod(target, mode or 0o755)
        return
    with tarfile.open(archive, "r:gz") as tf:
        members = [m for m in tf.getmembers() if not m.isdir()]
        rels = _strip_top([_clean(m.name) for m in members])
        links = []
        for m, rel in zip(members, rels):
            if not rel.parts:
                continue
            if m.issym():
                if "/" in m.linkname or "\\" in m.linkname or m.linkname in ("", ".", ".."):
                    raise UnsafeArchive(f"unsafe link in the archive: {m.name} -> {m.linkname}")
                links.append((rel, m.linkname))
                continue
            if not m.isfile():
                raise UnsafeArchive(f"unsupported entry in the archive: {m.name}")
            target = dest.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with tf.extractfile(m) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            if os.name != "nt":
                os.chmod(target, (m.mode & 0o777) or 0o644)
        for rel, linkname in links:                         # same-folder links (libllama.so.0 -> libllama.so.0.0.1)
            target = dest.joinpath(*rel.parts)
            source = target.parent / linkname
            try:
                if os.name == "nt":
                    raise OSError("no symlinks")
                os.symlink(linkname, target)
            except OSError:
                if source.is_file():
                    shutil.copyfile(source, target)


# --- The installer ------------------------------------------------------------------------------------
def _run_streaming(argv: list, on_line) -> int:
    """Run a program, passing each output line to on_line. -> exit code."""
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    with proc.stdout:
        for line in proc.stdout:
            on_line(line.rstrip("\r\n"))
    return proc.wait()


class Installer:
    """One install at a time. status() is safe to call from any thread."""

    def __init__(self, bin_dir, system, machine, gpu_kind, find, which, fetch_json=http_json, fetch_file=fetch_file,
                 version=server_version, run=_run_streaming, on_done=None, cuda_max=lambda: "", fetch_text=http_text):
        # bin_dir, system and machine may be values or functions returning them (the setup page passes functions,
        # so they follow the machine description it was given).
        self._bin, self._system, self._machine = bin_dir, system, machine
        self.gpu_kind = gpu_kind                # function: "nvidia" | "gpu" | "apple" | "none"
        self.cuda_max = cuda_max                # function: newest CUDA the NVIDIA driver runs ("12.4"), or ""
        self.find, self.which = find, which     # find(): the llama-server the serve scripts would use, or ""
        self.fetch_json, self.fetch_file, self.version, self.run = fetch_json, fetch_file, version, run
        self.fetch_text = fetch_text
        self.on_done = on_done                  # called after a successful install, before "done" is reported
        self.lock = threading.Lock()
        self.job = {"state": "idle"}
        self.log = []

    @staticmethod
    def _value(v):
        return v() if callable(v) else v

    @property
    def bin(self) -> Path:
        return Path(self._value(self._bin))

    @property
    def system(self) -> str:
        return self._value(self._system)

    @property
    def machine(self) -> str:
        return self._value(self._machine)

    @property
    def staging(self) -> Path:
        return self.bin / STAGING

    def offer(self) -> dict:
        """How llama.cpp would be installed here. Nothing is contacted."""
        if self.system == "Darwin":
            if self.which("brew"):
                return {"how": "brew", "cmd": "brew install llama.cpp"}
            return {"how": "manual"}
        if self.system in ("Windows", "Linux") and arch_of(self.machine):
            kind = {"nvidia": "cuda", "gpu": "vulkan"}.get(self.gpu_kind(), "cpu")
            return {"how": "download", "kind": kind, "label": KIND_LABEL[kind], "into": str(self.bin)}
        return {"how": "manual"}

    def status(self) -> dict:
        with self.lock:
            return dict(self.job, log=list(self.log[-80:]))

    def _set(self, **kw) -> None:
        with self.lock:
            self.job.update(kw)

    def _say(self, line: str) -> None:
        with self.lock:
            self.log.append(line)

    def start(self, variant: str = "auto") -> tuple:
        how = self.offer()["how"]
        if how == "manual":
            return 409, {"error": "llama.cpp cannot be installed from this page on this computer. Follow the steps shown."}
        with self.lock:
            if self.job.get("state") in ("checking", "downloading", "verifying", "installing"):
                return 409, {"error": "llama.cpp is already being installed."}
            self.job = {"state": "checking", "how": how}
            self.log = []
        target = self._brew if how == "brew" else self._download
        threading.Thread(target=target, args=(variant,), daemon=True).start()
        return 202, self.status()

    def _fail(self, error: str, **kw) -> None:
        self._say(error)
        self._end(state="failed", error=error, **kw)

    def _end(self, **final) -> None:
        """Report the result, after removing the staging folder: a page that sees the result sees a clean bin/."""
        if self.job.get("how") == "download":
            shutil.rmtree(self.staging, ignore_errors=True)
        self._set(**final)

    # macOS -----------------------------------------------------------------------------------------
    def _brew(self, _variant) -> None:
        brew = self.which("brew")
        argv = [brew] + BREW_CMD
        self._set(state="installing", cmd="brew install llama.cpp")
        self._say("$ brew install llama.cpp")
        try:
            code = self.run(argv, self._say)
        except OSError as e:
            return self._fail(f"Homebrew could not be started: {e}")
        if code != 0:
            return self._fail(f"brew install llama.cpp failed (exit code {code}). Its output is below.")
        self._finish(None, "brew")

    # Windows / Linux -------------------------------------------------------------------------------
    def _download(self, variant) -> None:
        try:
            self._download_and_install(variant)
        except UnsafeArchive as e:
            self._fail(f"The download was refused as unsafe: {e}. Nothing was installed.")
        except Exception as e:                              # noqa: BLE001 - always end in a state the page can show
            self._fail(f"The install stopped: {e}. Nothing was installed.")

    def _download_and_install(self, variant) -> None:
        try:
            p = find_release(self.fetch_json, self.fetch_text, self.system, self.machine, self.gpu_kind(), variant,
                             cuda_max=self.cuda_max(), say=self._say)
        except (OSError, ValueError) as e:
            return self._fail(f"The page could not reach GitHub to find the latest llama.cpp release ({e}). "
                              "Check your connection and try again.")
        if "error" in p:
            return self._fail(p["error"])
        self._say(f"Using release {p['release']}")
        total = sum(int(a.get("size") or 0) for a in p["assets"])
        self._set(state="downloading", kind=p["kind"], tag=p["tag"], why=p["why"], done=0, total=total,
                  files=[a["name"] for a in p["assets"]])
        shutil.rmtree(self.staging, ignore_errors=True)
        (self.staging / "download").mkdir(parents=True)
        unpacked = self.staging / "files"
        checksum = "verified"
        base = 0
        for a in p["assets"]:
            url, name, size = a["browser_download_url"], a["name"], int(a.get("size") or 0)
            dest = self.staging / "download" / Path(name).name
            self._say(f"Downloading {url}")
            self.fetch_file(url, dest, lambda n, b=base: self._set(done=b + n))
            got = dest.stat().st_size
            if size and got != size:
                return self._fail(f"{name}: downloaded size {got} does not match the release listing ({size}). "
                                  "Nothing was installed.")
            digest = str(a.get("digest") or "")
            if digest.startswith("sha256:"):
                if sha256_of(dest) != digest.split(":", 1)[1].lower():
                    return self._fail(f"{name}: the SHA-256 checksum does not match the one GitHub publishes. "
                                      "Nothing was installed.")
                self._say(f"{name}: SHA-256 matches GitHub's published checksum")
            else:
                checksum = "none-published"
                self._say(f"{name}: GitHub publishes no checksum for it; checked its size only")
            base += size or got
            self._set(done=base)
            self._set(state="verifying")
            extract(dest, unpacked)
        exe = unpacked / ("llama-server.exe" if self.system == "Windows" else "llama-server")
        if not exe.is_file():
            return self._fail("The archive has no llama-server in it. Nothing was installed.")
        ok, out = self.version([str(exe)])
        for line in out.splitlines()[-20:]:
            self._say(line)
        if not ok:
            return self._fail(f"The downloaded {KIND_LABEL[p['kind']]} did not start (`llama-server --version` failed). "
                              "Nothing was installed. Its output is below.", cpu_fallback=p["kind"] != "cpu")
        self._set(state="installing")
        files = [s for s in sorted(unpacked.rglob("*")) if s.is_symlink() or not s.is_dir()]
        for n, src in enumerate(files):
            target = self.bin.joinpath(*src.relative_to(unpacked).parts)
            try:
                if target.is_dir() and not target.is_symlink():
                    raise IsADirectoryError(f"{target} is a folder")
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(src, target)
            except OSError as e:
                state = "Nothing in bin/ was changed." if n == 0 else (
                    f"{n} of {len(files)} files in {self.bin} were already replaced, so it now holds a mix of builds: "
                    "run the install again once the file is free.")
                return self._fail(f"Could not replace {target.name} ({e}). If llama-server is still running from that "
                                  f"folder (for example started by the serve script), close it and try again. {state}")
        self._finish(self.bin / exe.name, checksum)

    def _finish(self, installed, checksum) -> None:
        found = self.find()
        if not found:
            return self._fail("The install finished, but llama-server is still not found.")
        ok, out = self.version([found])
        if not ok:
            for line in out.splitlines()[-20:]:
                self._say(line)
            return self._fail(f"llama-server at {found} does not start (`--version` failed). Its output is below.")
        version = next((line for line in out.splitlines() if "version" in line.lower()), out.splitlines()[0] if out else "")
        shadowed = ""
        if installed is not None and os.path.normcase(os.path.abspath(found)) != os.path.normcase(os.path.abspath(installed)):
            shadowed = (f"Another llama-server comes first: {found}. The serve scripts and this page use it, not the "
                        f"one just installed in {self.bin}. Set LLAMA_SERVER={installed}, or remove the other copy "
                        "from your PATH.")
        self._say(f"Installed: {found} ({version})")
        if self.on_done:
            self.on_done()
        self._end(state="done", path=found, version=version, checksum=checksum, shadowed=shadowed)
