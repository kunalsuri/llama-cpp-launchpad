"""llama-cpp-launchpad: what is in the models folder, and deleting a model from it ("My models" on the setup page).

Python standard library only. Deleting is the one destructive thing the page can do, so it is kept small:
  - only an id that scan() itself listed can be deleted; the browser never sends a path
  - every file removed is a direct child of the models folder (checked on the path itself, not on where a link
    points: deleting a link removes the link, never the file it points to)
  - what goes is the model's own files: every part of a split model, its .source record and its unfinished .part
"""
from __future__ import annotations

import re
from pathlib import Path

SHARD = re.compile(r"^(?P<stem>.+)-(?P<n>\d{5})-of-(?P<total>\d{5})\.gguf$", re.I)
NOT_HERE = "That file is not in the models folder (reload the page)."


def _source(path: Path) -> str:
    rec = path.with_name(path.name + ".source")
    try:
        return rec.read_text(encoding="utf-8").strip() if rec.is_file() else ""
    except OSError:
        return ""


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def is_projector(name: str) -> bool:
    """A vision projector (mmproj) file: llama.cpp loads it next to a model, it is not a model itself."""
    return "mmproj" in name.lower()


def scan(models_dir) -> list:
    """Everything in the folder that is part of a model -> [{id, kind, files, size, repo, modified}], largest first.
    kind: model | incomplete (a split model with parts missing) | projector | partial (an unfinished download)."""
    d = Path(models_dir)
    try:
        names = sorted(p.name for p in d.iterdir() if p.is_file() or p.is_symlink())
    except OSError:
        return []
    have, out, sets = set(names), [], {}
    for name in names:
        low = name.lower()
        if low.endswith(".gguf.part"):
            out.append({"id": name, "kind": "partial", "files": [name], "size": _size(d / name), "repo": "",
                        "modified": _mtime(d / name)})
            continue
        if not low.endswith(".gguf"):
            continue
        m = SHARD.match(name)
        if m:
            sets.setdefault((m.group("stem"), m.group("total")), []).append(name)
            continue
        out.append({"id": name, "kind": "projector" if is_projector(name) else "model", "files": [name],
                    "size": _size(d / name), "repo": _source(d / name), "modified": _mtime(d / name)})
    for (stem, total), parts in sets.items():
        first = f"{stem}-00001-of-{total}.gguf"
        parts = sorted(parts)
        complete = len(parts) == int(total) and first in parts
        out.append({"id": parts[0], "kind": "model" if complete else "incomplete", "files": parts,
                    "size": sum(_size(d / p) for p in parts), "repo": _source(d / parts[0]),
                    "modified": max(_mtime(d / p) for p in parts)})
    for e in out:                                           # each model's own records go with it
        extra = [f + ".source" for f in e["files"] if f + ".source" in have]
        extra += [f + ".part" for f in e["files"] if f + ".part" in have and e["kind"] != "partial"]
        e["files"] = e["files"] + extra
    return sorted(out, key=lambda e: (-e["size"], e["id"]))


def _inside(models_dir: Path, name: str) -> bool:
    """A plain file name whose path is a direct child of the folder (the link itself, not its target)."""
    if not name or name != Path(name).name or name in (".", ".."):
        return False
    return (models_dir / name).parent.resolve() == models_dir.resolve()


def delete(models_dir, entry_id: str) -> tuple:
    """Delete one entry that scan() lists -> (names removed, "" or why nothing was removed)."""
    d = Path(models_dir)
    entry = next((e for e in scan(d) if e["id"] == entry_id), None) if isinstance(entry_id, str) else None
    if entry is None or not all(_inside(d, f) for f in entry["files"]):
        return [], NOT_HERE
    removed = []
    for name in entry["files"]:
        try:
            (d / name).unlink()
            removed.append(name)
        except FileNotFoundError:
            continue
        except OSError as e:
            return removed, f"Could not delete {name}: {e}"
    return removed, ""
