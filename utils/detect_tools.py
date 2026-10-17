#!/usr/bin/env python3
"""llama-cpp-launchpad: which local-LLM tools are installed on this computer?

Checks for Ollama, llama.cpp, LM Studio and Unsloth on Windows, macOS and Linux, and says
*why* it thinks so: every finding lists the path or package it was based on.

Python standard library only. Strictly read-only: it looks at PATH, a fixed list of well-known
install locations and Python package metadata, and runs `<tool> --version` on the command-line
tools it finds (never on Unsloth, which would import PyTorch). It writes nothing, uses no network,
and records no host name, user name or IP address.

Status per tool:
  installed   an executable, app bundle or Python package was found (strong evidence)
  data-only   only a data folder was found, e.g. ~/.ollama after an uninstall (weak evidence)
  not-found   nothing found

Limits (by design): Python packages are found in the Python running this script and in common
conda / virtualenv folders under your home directory. A tool installed somewhere unusual and not
on PATH will not be seen; put it on PATH or set LLAMA_SERVER for llama.cpp.

Usage:
  detect_tools.py                    one line per tool
  detect_tools.py --json             machine-readable result (schema 1)
  detect_tools.py --verbose          also list every location that was checked
  detect_tools.py --tool ollama      only these tools (repeatable): ollama, llama-cpp, lmstudio, unsloth
  detect_tools.py --strict           exit 1 if any selected tool is not installed
  detect_tools.py --no-version       do not run any program (PATH and file checks only)
"""
from __future__ import annotations

import argparse
import glob
import importlib.metadata
import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

from hardware import run_cmd

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = 1
STRONG = "strong"
WEAK = "weak"


class Probe:
    """Everything the checks need from the machine. Tests replace it with a fake one."""

    def __init__(self):
        self.system = platform.system()                 # Windows | Darwin | Linux
        self.machine = platform.machine()
        self.home = str(Path.home())
        self.root = str(ROOT)
        self.env = dict(os.environ)

    def join(self, *parts: str) -> str:
        pure = PureWindowsPath if self.system == "Windows" else PurePosixPath
        return str(pure(*parts))

    def norm(self, path: str) -> str:
        path = path.replace("\\", "/")
        return path.lower() if self.system in ("Windows", "Darwin") else path

    def which(self, name: str) -> str:
        return shutil.which(name) or ""

    def is_exe(self, path: str) -> bool:
        return os.path.isfile(path) and (self.system == "Windows" or os.access(path, os.X_OK))

    def is_dir(self, path: str) -> bool:
        return os.path.isdir(path)

    def glob(self, pattern: str) -> list:
        return sorted(glob.glob(pattern))

    def run(self, args: list, timeout: int = 10) -> str:
        return run_cmd(args, timeout=timeout)

    def py_package(self, name: str) -> str:
        """Version of a package installed in the Python running this script, or ''."""
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return ""


# --------------------------------------------------------------------------------------------
# What to look for. One function per tool returns a plain dict "spec"; nothing here touches disk.
#   path_names   programs looked up on PATH
#   env_file     env var that names an executable (llama.cpp: LLAMA_SERVER)
#   exe_paths    well-known executable locations
#   app_globs    well-known app bundles / app executables (never run)
#   packages     Python distribution names (checked in this Python and in common env folders)
#   data_dirs    folders the tool leaves behind (weak evidence)
#   version_args arguments for `<exe> ...`; None = never run it
#   version_re   how to pull the version out of that output
# --------------------------------------------------------------------------------------------

def _local_appdata(p: Probe) -> str:
    return p.env.get("LOCALAPPDATA") or p.join(p.home, "AppData", "Local")


def _exe(p: Probe, name: str) -> str:
    return name + ".exe" if p.system == "Windows" else name


def spec_ollama(p: Probe) -> dict:
    j, h = p.join, p.home
    exe = {"Windows": [j(_local_appdata(p), "Programs", "Ollama", "ollama.exe"),
                       j(p.env.get("ProgramFiles", r"C:\Program Files"), "Ollama", "ollama.exe")],
           "Darwin": ["/usr/local/bin/ollama", "/opt/homebrew/bin/ollama",
                      "/Applications/Ollama.app/Contents/Resources/ollama"],
           "Linux": ["/usr/local/bin/ollama", "/usr/bin/ollama", "/bin/ollama", "/opt/ollama/bin/ollama",
                     "/snap/bin/ollama", j(h, ".local", "bin", "ollama")]}.get(p.system, [])
    apps = ["/Applications/Ollama.app", j(h, "Applications", "Ollama.app")] if p.system == "Darwin" else []
    data = [j(h, ".ollama")] + (["/usr/share/ollama"] if p.system == "Linux" else [])
    return dict(id="ollama", label="Ollama", path_names=["ollama"], env_file="", exe_paths=exe,
                app_globs=apps, packages=[], data_dirs=data,
                version_args=["--version"], version_re=r"(\d+\.\d+\.\d+\S*)")


def spec_llamacpp(p: Probe) -> dict:
    j, h = p.join, p.home
    names = ["llama-server", "llama-cli", "llama-bench", "llama-quantize"]
    dirs = [j(p.root, "bin"), j(h, "llama.cpp", "build", "bin"), j(h, "llama.cpp", "build", "bin", "Release"),
            j(h, ".local", "bin")]
    if p.system != "Windows":
        dirs += ["/usr/local/bin", "/opt/homebrew/bin"]
    return dict(id="llama-cpp", label="llama.cpp", path_names=names, env_file="LLAMA_SERVER",
                exe_paths=[j(d, _exe(p, n)) for d in dirs for n in names],
                app_globs=[], packages=["llama-cpp-python"], data_dirs=[],
                version_args=["--version"], version_re=r"version:\s*([^\n]+)")


def spec_lmstudio(p: Probe) -> dict:
    j, h = p.join, p.home
    exe = [j(h, ".lmstudio", "bin", _exe(p, "lms"))]
    apps = {"Windows": [j(_local_appdata(p), "Programs", "LM Studio", "LM Studio.exe"),
                        j(p.env.get("ProgramFiles", r"C:\Program Files"), "LM Studio", "LM Studio.exe")],
            "Darwin": ["/Applications/LM Studio.app", j(h, "Applications", "LM Studio.app")],
            "Linux": [j(h, "Applications", "LM-Studio*.AppImage"), j(h, "Applications", "LM Studio*.AppImage"),
                      "/opt/lm-studio", "/opt/LM-Studio*", "/opt/lmstudio"]}.get(p.system, [])
    return dict(id="lmstudio", label="LM Studio", path_names=["lms"], env_file="", exe_paths=exe,
                app_globs=apps, packages=[], data_dirs=[j(h, ".lmstudio"), j(h, ".cache", "lm-studio")],
                version_args=["--version"], version_re=r"commit:\s*(\w+)")   # the CLI reports a commit id, not a release number


def spec_unsloth(p: Probe) -> dict:
    return dict(id="unsloth", label="Unsloth", path_names=["unsloth"], env_file="", exe_paths=[],
                app_globs=[], packages=["unsloth"], data_dirs=[p.join(p.home, ".unsloth")],
                version_args=None, version_re="")       # never run: importing unsloth loads PyTorch


SPECS = {"ollama": spec_ollama, "llama-cpp": spec_llamacpp, "lmstudio": spec_lmstudio, "unsloth": spec_unsloth}


def env_site_packages(p: Probe) -> list:
    """Glob patterns for site-packages folders of conda envs / virtualenvs in common places."""
    j, h = p.join, p.home
    roots = [j(h, d) for d in ("miniconda3", "anaconda3", "miniforge3", "mambaforge", "micromamba", ".conda",
                               ".virtualenvs", ".venv", "venv")]
    roots += [j(p.root, ".venv")]
    if p.system == "Windows":
        roots += [j(p.env.get("ProgramData", r"C:\ProgramData"), d) for d in ("miniconda3", "anaconda3")]
        pats = [j(r, "Lib", "site-packages") for r in roots]
        pats += [j(r, "envs", "*", "Lib", "site-packages") for r in roots]
        pats += [j(r, "*", "Lib", "site-packages") for r in roots]
        pats += [j(_local_appdata(p), "Programs", "Python", "Python3*", "Lib", "site-packages")]
        pats += [j(h, ".unsloth", "*", "*", "Lib", "site-packages")]
    else:
        pats = [j(r, "lib", "python3*", "site-packages") for r in roots]
        pats += [j(r, "envs", "*", "lib", "python3*", "site-packages") for r in roots]
        pats += [j(r, "*", "lib", "python3*", "site-packages") for r in roots]
        pats += [j(h, ".unsloth", "*", "*", "lib", "python3*", "site-packages")]
    return pats


def _dist_glob_name(package: str) -> str:
    return re.sub(r"[-_.]+", "_", package)


def _dist_version(path: str, package: str) -> str:
    base = re.split(r"[\\/]", path)[-1]
    m = re.match(rf"{re.escape(_dist_glob_name(package))}-(.+)\.dist-info$", base, re.I)
    return m.group(1) if m else ""


def parse_version(output: str, pattern: str) -> str:
    """Pull a version out of `--version` output; fall back to the first non-empty line."""
    output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)       # colour codes (lms prints a banner)
    if pattern:
        m = re.search(pattern, output)
        if m:
            return " ".join(m.group(1).split())
    for line in output.splitlines():
        if line.strip():
            return line.strip()[:80]
    return ""


def check_tool(spec: dict, p: Probe, want_version: bool = True) -> dict:
    evidence, searched, seen = [], [], set()

    def add(kind: str, path: str, strength: str, version: str = "") -> None:
        key = p.norm(path)
        if key in seen:
            return
        seen.add(key)
        evidence.append({"kind": kind, "path": path, "strength": strength, "version": version})

    def note(check: str, target: str, hit: str) -> None:
        searched.append({"check": check, "target": target, "found": bool(hit)})

    for name in spec["path_names"]:
        hit = p.which(name)
        note("PATH", name, hit)
        if hit:
            add("on-PATH", hit, STRONG)
    if spec["env_file"]:
        value = p.env.get(spec["env_file"], "")
        hit = value if value and p.is_exe(value) else ""
        note("env", spec["env_file"], hit)
        if hit:
            add("env-" + spec["env_file"], hit, STRONG)
    for path in spec["exe_paths"]:
        hit = path if p.is_exe(path) else ""
        note("file", path, hit)
        if hit:
            add("known-location", hit, STRONG)
    for pattern in spec["app_globs"]:
        matches = p.glob(pattern)
        note("app", pattern, matches[0] if matches else "")
        for m in matches:
            add("app", m, STRONG)
    pkg_version = ""
    for package in spec["packages"]:
        v = p.py_package(package)
        note("python-package", package + " (this Python)", v)
        if v:
            add("python-package", "python:" + package, STRONG, v)
            pkg_version = pkg_version or v
        for pattern in env_site_packages(p):
            full = p.join(pattern, _dist_glob_name(package) + "-*.dist-info")
            matches = p.glob(full)
            note("python-package", full, matches[0] if matches else "")
            for m in matches:
                dv = _dist_version(m, package)
                add("python-package", m, STRONG, dv)
                pkg_version = pkg_version or dv
    for path in spec["data_dirs"]:
        hit = path if p.is_dir(path) else ""
        note("dir", path, hit)
        if hit:
            add("data-dir", hit, WEAK)

    version = ""
    runnable = [e for e in evidence if e["kind"] in ("on-PATH", "known-location") or e["kind"].startswith("env-")]
    if want_version and spec["version_args"] and runnable:
        out = p.run([runnable[0]["path"]] + spec["version_args"])
        version = parse_version(out, spec["version_re"])
        runnable[0]["version"] = version
    version = version or pkg_version
    strong = any(e["strength"] == STRONG for e in evidence)
    status = "installed" if strong else ("data-only" if evidence else "not-found")
    return {"id": spec["id"], "label": spec["label"], "status": status, "version": version,
            "evidence": evidence, "searched": searched}


def detect(p: Probe, ids: list | None = None, want_version: bool = True) -> dict:
    chosen = ids or list(SPECS)
    return {"schema": SCHEMA,
            "platform": {"system": p.system, "machine": p.machine, "python": platform.python_version()},
            "tools": [check_tool(SPECS[i](p), p, want_version) for i in chosen]}


def render(result: dict, verbose: bool = False) -> str:
    plat = result["platform"]
    lines = [f"Local LLM tools on {plat['system']} {plat['machine']} (python {plat['python']}):"]
    for t in result["tools"]:
        first = next((e for e in t["evidence"] if e["strength"] == STRONG), t["evidence"][0] if t["evidence"] else None)
        where = f"  {first['path']}  [{first['kind']}]" if first else ""
        ver = f"  ver {t['version']}" if t["version"] else ""
        lines.append(f"  {t['label']:<10} {t['status'].upper():<10}{ver}{where}")
        if verbose:
            lines += [f"      + {e['kind']}: {e['path']}" + (f" ({e['version']})" if e["version"] else "")
                      for e in t["evidence"] if e is not first]
            lines += [f"      {'hit ' if s['found'] else 'miss'} {s['check']}: {s['target']}" for s in t["searched"]]
    return "\n".join(lines)


def main(argv: list | None = None, probe: Probe | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check whether Ollama, llama.cpp, LM Studio and Unsloth are installed.")
    ap.add_argument("--json", action="store_true", help="print machine-readable JSON")
    ap.add_argument("--verbose", "-v", action="store_true", help="list every location that was checked")
    ap.add_argument("--tool", action="append", choices=sorted(SPECS), help="limit to this tool (repeatable)")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any selected tool is not installed")
    ap.add_argument("--no-version", action="store_true", help="do not run any program")
    args = ap.parse_args(argv)
    result = detect(probe or Probe(), args.tool, want_version=not args.no_version)
    if args.json:
        if not args.verbose:
            for t in result["tools"]:
                del t["searched"]
        print(json.dumps(result, indent=2))
    else:
        print(render(result, args.verbose))
    missing = [t for t in result["tools"] if t["status"] != "installed"]
    return 1 if args.strict and missing else 0


if __name__ == "__main__":
    sys.exit(main())
