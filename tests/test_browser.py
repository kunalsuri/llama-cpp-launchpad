"""The setup page in a real browser (tests/browser_check.js, Chromium via Playwright).

The fake-DOM harness (page_harness.js) tests behaviour; this tests what only a browser can show: layout at phone,
tablet and desktop widths in light and dark, script errors, words like "null" leaking onto the page, buttons without
a name, tap targets, the clipboard and real browser history.

The server is the real one, on a random localhost port, with a fake computer: pinned hardware and PATH, a seeded
radar folder, a fake downloader and no network. Needs Node and Playwright (`npm ci && npx playwright install chromium`);
skipped with that reason otherwise. CI runs it on Linux, macOS and Windows (the `browser` job).
"""
import json
import os
import shutil
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "utils"))
sys.path.insert(0, str(HERE))
import hf_radar  # noqa: E402
import model_setup as ms  # noqa: E402
import test_ui_server as tui  # noqa: E402  (module import: its test classes are not collected twice)
from fakes import FakeProbe  # noqa: E402


def node_env() -> dict:
    """Find Playwright in this project's node_modules (npm ci) or, failing that, in the global npm folder."""
    env = dict(os.environ)
    npm = shutil.which("npm")
    if npm and not (ROOT / "node_modules" / "playwright").is_dir():
        try:
            root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True, timeout=30).stdout.strip()
            env["NODE_PATH"] = os.pathsep.join(p for p in (root, env.get("NODE_PATH", "")) if p)
        except (OSError, subprocess.SubprocessError):
            pass
    return env


def playwright_ready() -> bool:
    if not shutil.which("node"):
        return False
    probe = "const {chromium}=require('playwright');chromium.launch().then(b=>b.close()).then(()=>process.exit(0),()=>process.exit(1))"
    try:
        return subprocess.run(["node", "-e", probe], cwd=str(ROOT), env=node_env(), capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


RADAR = [
    {"repo": "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF", "name": "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M", "quant": "Q4_K_M",
     "size_mb": 17800, "size_bytes": 17800 << 20, "tps": 14, "fit_mode": "cpu", "clusters": ["coding", "agentic"],
     "downloads": 90000, "likes": 400, "created_at": "2026-10-20", "params_b": 30, "arch": "qwen3moe", "moe": True},
    {"repo": "bartowski/Llama-3.2-3B-Instruct-GGUF", "name": "Llama-3.2-3B-Instruct-Q4_K_M", "quant": "Q4_K_M",
     "size_mb": 2020, "size_bytes": 2020 << 20, "tps": 120, "fit_mode": "gpu", "clusters": ["chat"],
     "downloads": 45000, "likes": 200, "created_at": "2026-10-21", "params_b": 3, "arch": "llama"},
    {"repo": "lmstudio-community/Mistral-Small-3.2-24B-Instruct-2506-GGUF", "name": "Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M",
     "quant": "Q4_K_M", "size_mb": 40000, "size_bytes": 40000 << 20, "tps": 2, "fit_mode": "tight", "clusters": ["chat"],
     "downloads": 18000, "likes": 80, "created_at": "2026-10-24", "params_b": 24, "arch": "mistral"},
]


READY = playwright_ready()


@unittest.skipUnless(READY, "needs node + playwright with chromium: npm ci && npx playwright install chromium")
class TestBrowser(tui.UiBase):
    def setUp(self):
        super().setUp()
        radar = self.tmp / "radar"
        (radar / "snapshots").mkdir(parents=True)
        for day, models in (("2026-10-31", RADAR[1:]), ("2026-11-01", RADAR)):
            (radar / "snapshots" / f"{day}.json").write_text(json.dumps({"updated_at": day + "T08:00:00Z", "models": models}))
        (radar / "latest.json").write_text(json.dumps({"updated_at": "2026-11-01T08:00:00Z", "models": RADAR}))
        for p in (unittest.mock.patch.dict(os.environ, {"LP_RADAR_DIR": str(radar)}),
                  unittest.mock.patch.object(hf_radar, "http_json", side_effect=AssertionError("network")),
                  unittest.mock.patch.object(ms, "find_llama_server", return_value="")):
            p.start()
            self.addCleanup(p.stop)
        # A Linux machine with curl and Homebrew; Ollama installed and on PATH; llama.cpp missing.
        self.app.probe = FakeProbe("Linux", files=["/usr/bin/ollama"], path={
            "curl": "/usr/bin/curl", "brew": "/home/linuxbrew/.linuxbrew/bin/brew", "ollama": "/usr/bin/ollama"},
            output={"/usr/bin/ollama": "ollama version is 0.5.1"})

    def test_layout_rendering_and_flows_in_a_real_browser(self):
        done = subprocess.run(["node", str(HERE / "browser_check.js"), str(self.port)], cwd=str(ROOT), env=node_env(),
                              capture_output=True, text=True, timeout=600)
        rows = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
        self.assertGreaterEqual(len(rows), 26, done.stdout + done.stderr)
        failed = [f"{r['name']}: {r['detail']}" for r in rows if not r["ok"]]
        self.assertEqual(failed, [], "\n".join(failed))
        self.assertEqual(done.returncode, 0, done.stderr)



class TestBrowserRequired(unittest.TestCase):
    def test_ci_browser_job_cannot_pass_by_skipping(self):
        """The CI `browser` job sets LP_REQUIRE_BROWSER=1: there, a missing browser is a failure, not a skip."""
        if os.environ.get("LP_REQUIRE_BROWSER") == "1":
            self.assertTrue(READY, "LP_REQUIRE_BROWSER=1 but node/playwright/chromium is not usable")
