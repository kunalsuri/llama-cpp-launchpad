"""llama-cpp-launchpad: every downloaded model behind one address, with llama-server's router mode.

llama-server started without -m, with --models-preset FILE, is a router: a request names a model ("model" in the
JSON body) and the router loads it on demand (llama.cpp tools/server/README.md, "Using multiple models"). The preset
is an INI file with one [section] per model, `model = PATH` and, for a vision model, `mmproj = PATH`.
--models-max 1 keeps one model in memory at a time: asking for another unloads the last one used.

Python standard library only. The one file it writes is the preset (.launchpad-models.ini in the project folder),
replaced whole each time.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import local_models

PRESET_NAME = ".launchpad-models.ini"
SAFE_NAME = re.compile(r"[A-Za-z0-9._-]+")
NEEDS = ("--models-preset", "--models-max")


def _name(stem: str, taken: set) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]", "_", stem).strip(".") or "model"
    name, n = base, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    taken.add(name)
    return name


def entries(models_dir) -> list:
    """Each complete model in the folder -> {name (what a client asks for), model (path of its first file), mmproj}."""
    d = Path(models_dir)
    out, taken = [], set()
    for e in sorted(local_models.scan(d), key=lambda e: e["id"]):
        if e["kind"] != "model":
            continue
        first = e["files"][0]
        m = local_models.SHARD.match(first)
        stem = m.group("stem") if m else first[:-5]
        proj = local_models.projector_for(d, first)
        out.append({"name": _name(stem, taken), "model": str(d / first), "mmproj": str(d / proj) if proj else ""})
    return sorted(out, key=lambda x: x["name"])


def preset_ini(rows: list, shared: dict) -> str:
    """The INI text: shared settings in [*], then one section per model."""
    lines = ["version = 1", "", "[*]"] + [f"{k} = {v}" for k, v in shared.items()]
    for r in rows:
        for value in (r["name"], r["model"], r["mmproj"]):
            if any(c in str(value) for c in "\r\n"):
                raise ValueError(f"a line break in {value!r} would change the preset file")
        lines += ["", f"[{r['name']}]", f"model = {r['model']}"] + ([f"mmproj = {r['mmproj']}"] if r["mmproj"] else [])
    return "\n".join(lines) + "\n"


def write_preset(path, text: str) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def router_args(preset_path, flags: set) -> tuple:
    """-> (llama-server arguments for router mode, "") or ([], why not)."""
    missing = [f for f in NEEDS if f not in flags]
    if missing:
        return [], (f"This llama-server does not list {', '.join(missing)} in its --help: serving several models "
                    "needs a newer llama.cpp.")
    return ["--models-preset", str(preset_path), "--models-max", "1"], ""
