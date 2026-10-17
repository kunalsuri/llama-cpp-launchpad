"""Shared test doubles. FakeProbe is a whole fake computer for utils/detect_tools.py: a virtual file system,
a virtual PATH, canned program output and a record of every program it was asked to run (`.ran`).
It lets the Windows, macOS and Linux code paths be tested on any host, with nothing real executed.
"""
import fnmatch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))
import detect_tools as dt  # noqa: E402


class FakeProbe(dt.Probe):
    def __init__(self, system="Linux", files=(), dirs=(), path=None, output=None, env=None, pkgs=None):
        self.system, self.machine = system, "x86_64"
        self.home = {"Windows": r"C:\Users\me", "Darwin": "/Users/me"}.get(system, "/home/me")
        self.root = {"Windows": r"C:\proj", "Darwin": "/Users/me/proj"}.get(system, "/home/me/proj")
        self.env = dict(env or {})
        self.files = {self._n(f) for f in files}
        self.dirs = {self._n(d) for d in dirs}
        self.path = dict(path or {})        # program name -> full path
        self.output = dict(output or {})    # full path -> text printed by `--version`
        self.pkgs = dict(pkgs or {})        # pip name -> version, "in this Python"
        self.ran = []

    @staticmethod
    def _n(path):
        return str(path).replace("\\", "/")

    def which(self, name):
        return self.path.get(name, "")

    def is_exe(self, path):
        return self._n(path) in self.files

    def is_dir(self, path):
        return self._n(path) in self.dirs

    def glob(self, pattern):
        pat = self._n(pattern).split("/")
        hits = []
        for f in sorted(self.files | self.dirs):
            parts = f.split("/")
            if len(parts) == len(pat) and all(fnmatch.fnmatchcase(a, b) for a, b in zip(parts, pat)):
                hits.append(f)
        return hits

    def run(self, args, timeout=10):
        self.ran.append(list(args))
        return self.output.get(args[0], "")

    def py_package(self, name):
        return self.pkgs.get(name, "")
