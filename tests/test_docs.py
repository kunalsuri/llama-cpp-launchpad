"""The documentation: links that resolve, and pictures and videos that are what they say they are.

Every screenshot, GIF, MP4 and terminal recording under docs/media/ must be listed in docs/media/manifest.json with
the run that made it: date, machine, the llama-server it used and the model. A capture made with the test suite's
fake llama-server is refused, because it shows replies and speeds no real model produced (CLAUDE.md rule 3: never
show what did not happen). The checks on one entry live in tools/docs-media/capture.py, so the tool that writes the
manifest and this test agree on what a complete entry is.
"""
import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DOCS = ROOT / "docs"
MEDIA = DOCS / "media"
sys.path.insert(0, str(ROOT / "tools" / "docs-media"))
import capture  # noqa: E402

PAGES = [ROOT / "README.md"] + sorted(DOCS.rglob("*.md"))
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|<(?:img|video|source|a)\b[^>]*?(?:src|href)=\"([^\"]+)\"")
MEDIA_TYPES = {".png", ".gif", ".mp4", ".webm", ".cast", ".svg", ".jpg", ".jpeg", ".webp"}


def slug(heading):
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"<[^>]+>|[*_`]", "", heading).strip().lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def anchors(page):
    text = re.sub(r"(?ms)^```.*?^```", "", page.read_text(encoding="utf-8"))
    return {slug(m) for m in re.findall(r"(?m)^#{1,6}\s+(.+?)\s*#*$", text)}


def links(page):
    text = re.sub(r"(?ms)^```.*?^```", "", page.read_text(encoding="utf-8"))      # commands in code blocks are not links
    text = re.sub(r"`[^`\n]*`", "", text)
    return [a or b for a, b in LINK.findall(text)]


class TestLinks(unittest.TestCase):
    def test_every_relative_link_and_anchor_resolves(self):
        problems = []
        for page in PAGES:
            for target in links(page):
                if re.match(r"[a-z]+:", target) or target.startswith("//"):
                    continue                                   # web addresses are not checked offline
                path, _, anchor = target.partition("#")
                dest = (page.parent / path).resolve() if path else page
                if not dest.exists():
                    problems.append(f"{page.relative_to(ROOT)}: {target} does not exist")
                elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
                    problems.append(f"{page.relative_to(ROOT)}: {target} has no heading #{anchor}")
        self.assertEqual(problems, [])

    def test_slug_matches_github(self):
        self.assertEqual(slug("Model radar (`/#radar`) and What changed (`/#history`)"),
                         "model-radar-radar-and-what-changed-history")
        self.assertEqual(slug("Use it from other programs"), "use-it-from-other-programs")

    def test_the_documentation_home_lists_every_page(self):
        home = (DOCS / "README.md").read_text(encoding="utf-8")
        for page in sorted(DOCS.rglob("*.md")):
            if page.parent == DOCS and page.name == "README.md":
                continue
            rel = page.relative_to(DOCS).as_posix()
            self.assertIn(f"({rel})", home, f"docs/README.md never links to {rel}")

    def test_readme_points_to_the_documentation_home(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertTrue("(docs/README.md)" in readme, "README.md never links to docs/README.md")


class TestMediaManifest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((MEDIA / "manifest.json").read_text(encoding="utf-8"))

    def test_every_media_file_is_listed_and_every_listed_file_exists(self):
        on_disk = {p.relative_to(MEDIA).as_posix() for p in MEDIA.rglob("*") if p.suffix.lower() in MEDIA_TYPES}
        listed = {c["file"] for c in self.manifest["captures"]}
        self.assertEqual(sorted(on_disk - listed), [], "media without provenance in docs/media/manifest.json")
        self.assertEqual(sorted(listed - on_disk), [], "manifest entries whose file is missing")

    def test_every_entry_says_how_it_was_made(self):
        problems = []
        for entry in self.manifest["captures"]:
            problems += capture.entry_problems(entry, self.manifest.get("runs", {}))
        self.assertEqual(problems, [])

    def test_pages_show_only_listed_media(self):
        listed = {(MEDIA / c["file"]).resolve() for c in self.manifest["captures"]}
        for page in PAGES:
            for target in links(page):
                dest = (page.parent / target.partition("#")[0]).resolve()
                if dest.suffix.lower() in MEDIA_TYPES and not re.match(r"[a-z]+:", target):
                    self.assertIn(dest, listed, f"{page.relative_to(ROOT)} shows {target}, which has no provenance")

    def test_media_stays_small_enough_to_clone(self):
        # Git keeps every version of a binary for ever: a 30 MB GIF is paid by every clone.
        for p in MEDIA.rglob("*"):
            if p.suffix.lower() in MEDIA_TYPES:
                self.assertLessEqual(p.stat().st_size, capture.MAX_BYTES[p.suffix.lower()], f"{p.name} is too big")


if __name__ == "__main__":
    unittest.main()
