"""Tests for utils/ui_server.py (the `model-setup --ui` page). A real server on a random localhost port,
a fake Hugging Face, a fake downloader. No network, GPU or llama.cpp needed.
Run: python3 -m unittest discover -s tests -v
"""
import http.client
import io
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import unittest
import unittest.mock
import urllib.error
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "utils"))
sys.path.insert(0, str(HERE))
import model_setup as ms  # noqa: E402
import test_hf_discover as thd  # noqa: E402  (module import: its test classes are not collected twice)
import test_model_setup as tms  # noqa: E402
import ui_server  # noqa: E402
from fakes import FakeProbe  # noqa: E402


class UiBase(tms.Base):
    def setUp(self):
        super().setUp()
        hw = ms.Hw(ram_mb=16384, cores=8, gpu_kind="nvidia", gpu_name="Test GPU", vram_mb=8192, gpu_usable=True)
        self.hw = hw
        # Rule 2: whether this machine has llama.cpp must not change the answers; tests say what is "found".
        self.found_server = ""
        for target, value in (("detect_hw", lambda: self.hw), ("download", self.fake_download),
                              ("check_model_speed", self.fake_speed), ("find_llama_server", lambda: self.found_server)):
            p = unittest.mock.patch.object(ms, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.app = ui_server.App(ms)
        self.app.probe = FakeProbe("Linux")     # rule 2: commands and hints must not depend on the host
        self.app.llama_version = lambda argv: (True, "version: 4242 (abc1234)")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ui_server.make_handler(self.app))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def fake_http_get(self, url, timeout=25):
        if "/models?" in url:
            return json.dumps(thd.TestDiscoverCommand.LIST)
        repo = url.split("/api/models/", 1)[1].split("?", 1)[0]
        if repo in thd.TestDiscoverCommand.DETAIL:
            return json.dumps(thd.TestDiscoverCommand.DETAIL[repo])
        raise urllib.error.HTTPError(url, 404, "nf", None, None)

    def fake_download(self, repo, f, size, on_progress=None):
        path, _ = ms.local_path(repo, f, size)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        ms.claim_file(path, repo)
        if on_progress:
            on_progress(size)
        return path

    def fake_speed(self, path, size, hw):
        ms.state_set("measured_tps", 42)
        return 0

    def call(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = dict(headers or {})
        if body is not None:
            h.setdefault("Content-Type", "application/json")
        conn.putrequest(method, path, skip_host=True)
        conn.putheader("Host", host or f"127.0.0.1:{self.port}")
        for k, v in h.items():
            conn.putheader(k, v)
        data = json.dumps(body).encode() if body is not None else None
        conn.putheader("Content-Length", str(len(data or b"")))
        conn.endheaders(data)
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        return r.status, r, raw

    def get_json(self, path):
        status, _, raw = self.call("GET", path)
        self.assertEqual(status, 200, raw)
        return json.loads(raw)

    def post(self, path, body, token=True, **kw):
        headers = {"X-LP-Token": self.app.token} if token else {}
        headers.update(kw.pop("headers", {}))
        status, _, raw = self.call("POST", path, body, headers, **kw)
        return status, json.loads(raw)


class TestPage(UiBase):
    def test_page_is_served_with_a_strict_policy(self):
        status, resp, raw = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"What will you use it for?", raw)
        csp = resp.getheader("Content-Security-Policy")
        self.assertIn("default-src 'none'", csp)
        self.assertIn("connect-src 'self'", csp)
        self.assertEqual(resp.getheader("X-Frame-Options"), "DENY")
        self.assertEqual(resp.getheader("Cache-Control"), "no-store")

    def test_page_loads_nothing_from_elsewhere(self):
        text = ui_server.PAGE.read_text(encoding="utf-8")
        self.assertNotRegex(text, r'(src|href)\s*=\s*"https?://')
        self.assertNotRegex(text, r"@import|url\(\s*[\"']?https?:")
        self.assertEqual(re.findall(r"fetch\(([^,)]*)", text), ["path"])        # one place talks to the server

    def test_page_has_the_installed_tools_view(self):
        text = ui_server.PAGE.read_text(encoding="utf-8")
        for needle in ('id="v-tools"', 'id="tools-btn"', 'id="tools-list"', 'id="tools-recheck"', "/api/tools"):
            self.assertIn(needle, text)
        self.assertNotIn("innerHTML", text, "text from the server is only ever inserted as text")
        # Opening /#tools by link is a behaviour: tests/page_harness.js checks it ("the /#tools link opens ...").

    def test_page_draws_its_symbols_instead_of_relying_on_emoji_fonts(self):
        """Regression: tabs and badges used emoji (🔥 ⚡ 💻 ...). Linux machines without a colour-emoji font show
        empty boxes, and Windows/macOS draw them in different styles. The page uses its own SVG icons instead."""
        text = ui_server.PAGE.read_text(encoding="utf-8")
        emoji = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]")
        found = sorted({(text[:m.start()].count("\n") + 1, m.group()) for m in emoji.finditer(text)})
        self.assertEqual(found[:10], [], f"{len(found)} emoji in the page (line, char)")

    def test_every_view_has_a_heading_that_can_take_focus(self):
        """Moving focus to the heading tells screen readers that the view changed (checked in the page harness)."""
        text = ui_server.PAGE.read_text(encoding="utf-8")
        views = re.findall(r'<section class="view" id="v-([a-z]+)"', text)
        self.assertGreaterEqual(len(views), 8)
        for v in views:
            self.assertTrue(re.search(rf'<h1 id="{v}-title"[^>]*\btabindex="-1"', text), f"v-{v} has no focusable <h1 id={v}-title>")

    def test_unknown_paths_are_404_and_there_is_no_file_serving(self):
        for path in ("/etc/passwd", "/../README.md", "/utils/model_setup.py", "/ui/setup/index.html"):
            self.assertEqual(self.call("GET", path)[0], 404, path)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the page script")
class TestPageScript(unittest.TestCase):
    """The real <script> of the setup page, run by Node against a fake DOM / fetch / timers (tests/page_harness.js)."""

    def test_script_is_valid_javascript(self):
        text = ui_server.PAGE.read_text(encoding="utf-8")
        script = text[text.index("<script>") + 8:text.index("</script>")]
        done = subprocess.run(["node", "--check", "-"], input=script, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_scenarios(self):
        done = subprocess.run(["node", str(HERE / "page_harness.js"), str(ui_server.PAGE)],
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
        results = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
        self.assertGreaterEqual(len(results), 12, done.stdout + done.stderr)
        for r in results:
            with self.subTest(r["name"]):
                self.assertTrue(r["ok"], r["detail"])
        self.assertEqual(done.returncode, 0, done.stderr)


class TestGuards(UiBase):
    def test_wrong_host_is_refused(self):
        for host in ("evil.example", f"evil.example:{self.port}", f"127.0.0.1:{self.port + 1}", "127.0.0.1"):
            self.assertEqual(self.call("GET", "/api/state", host=host)[0], 403, host)
        self.assertEqual(self.call("GET", "/api/state", host=f"localhost:{self.port}")[0], 200)

    def test_post_needs_the_token(self):
        self.assertEqual(self.post("/api/install", {"id": "x"}, token=False)[0], 403)
        self.assertEqual(self.post("/api/install", {"id": "x"}, headers={"X-LP-Token": "wrong"})[0], 403)

    def test_refused_post_with_a_body_is_answered_cleanly(self):
        """Regression: the server used to answer 403 without reading the body, so the client got a
        connection reset (WinError 10054) instead of the 403. Seen as a random failure of the suite."""
        body = {"id": "x" * 3000}
        for i in range(40):
            self.assertEqual(self.post("/api/install", body, token=False)[0], 403, i)
            self.assertEqual(self.post("/api/install", body, headers={"Origin": "https://evil.example"})[0], 403, i)
            self.assertEqual(self.call("POST", "/api/install", body, host="evil.example")[0], 403, i)

    def test_post_from_another_origin_is_refused(self):
        self.assertEqual(self.post("/api/install", {"id": "x"}, headers={"Origin": "https://evil.example"})[0], 403)

    def test_cannot_download_what_was_never_offered(self):
        status, out = self.post("/api/install", {"id": "evil/Repo|payload.gguf"})
        self.assertEqual(status, 404)
        self.assertEqual(self.app.snapshot()["state"], "idle")
        self.assertEqual(self.post("/api/install", {"repo": "a/b", "file": "c.gguf"})[0], 404)   # no raw names accepted

    def test_bad_bodies(self):
        status, _, _ = self.call("POST", "/api/install", None, {"X-LP-Token": self.app.token})
        self.assertEqual(status, 404)           # empty body: nothing to install


class TestToolsApi(UiBase):
    """/api/tools: the dashboard's view of utils/detect_tools.py (same code as the command line)."""

    def setUp(self):
        super().setUp()
        self.probe = FakeProbe("Linux", files=["/usr/local/bin/ollama"], path={"ollama": "/usr/local/bin/ollama"},
                               output={"/usr/local/bin/ollama": "ollama version is 0.5.1"},
                               pkgs={"unsloth": "2025.9.1"}, dirs=["/home/me/.lmstudio"])
        self.app.probe = self.probe

    def tools(self, query=""):
        data = self.get_json("/api/tools" + query)
        return data, {t["id"]: t for t in data["tools"]}

    def test_reports_every_tool_with_status_and_version(self):
        data, by_id = self.tools()
        self.assertEqual(data["schema"], 1)
        self.assertEqual(list(by_id), ["ollama", "llama-cpp", "lmstudio", "unsloth"])
        self.assertEqual((by_id["ollama"]["status"], by_id["ollama"]["version"]), ("installed", "0.5.1"))
        self.assertEqual(by_id["unsloth"]["status"], "installed")
        self.assertEqual(by_id["lmstudio"]["status"], "data-only")
        self.assertEqual(by_id["llama-cpp"]["status"], "not-found")

    def test_same_answer_as_the_command_line(self):
        import detect_tools
        cli = detect_tools.detect(FakeProbe("Linux", files=["/usr/local/bin/ollama"],
                                            path={"ollama": "/usr/local/bin/ollama"},
                                            output={"/usr/local/bin/ollama": "ollama version is 0.5.1"},
                                            pkgs={"unsloth": "2025.9.1"}, dirs=["/home/me/.lmstudio"]))
        _, by_id = self.tools()
        for t in cli["tools"]:
            for key in ("status", "version", "evidence"):
                self.assertEqual(by_id[t["id"]][key], t[key], (t["id"], key))

    def test_evidence_is_included_and_checked_locations_only_on_request(self):
        _, by_id = self.tools()
        self.assertEqual(by_id["ollama"]["evidence"][0]["kind"], "on-PATH")
        self.assertNotIn("searched", by_id["ollama"])
        _, verbose = self.tools("?verbose=1")
        self.assertIn({"check": "PATH", "target": "lms", "found": False}, verbose["lmstudio"]["searched"])

    def test_tool_filter(self):
        data, by_id = self.tools("?tool=unsloth&tool=ollama")
        self.assertEqual([t["id"] for t in data["tools"]], ["unsloth", "ollama"])
        self.assertEqual(self.call("GET", "/api/tools?tool=nope")[0], 400)

    def test_hints_tell_the_user_what_to_do_next(self):
        _, by_id = self.tools()
        for t in by_id.values():
            self.assertTrue(t["hint"]["install"], t["id"])
            self.assertNotRegex(t["hint"]["install"], r"https?://", "hints are plain text, never links")
        self.assertTrue(by_id["ollama"]["hint"]["start"], "installed: how to start it")
        self.assertNotIn("start", by_id["llama-cpp"]["hint"], "not installed: nothing to start")

    def hint_for(self, tool_id, probe):
        self.app.probe = probe
        data = self.get_json("/api/tools?tool=" + tool_id)
        return data["tools"][0]["status"], data["tools"][0]["hint"]

    def test_start_hint_needs_the_program_that_the_command_runs(self):
        """Regression: 'installed' via a Python package, an app bundle, or llama-cli alone used to show a start
        command that could not work (the serve script needs llama-server; `lms` may not be on PATH)."""
        cases = [
            # (tool, fake machine, expect a start command?)
            ("llama-cpp", FakeProbe("Linux", pkgs={"llama-cpp-python": "0.3.1"}), False),
            ("llama-cpp", FakeProbe("Linux", files=["/usr/local/bin/llama-cli"],
                                    path={"llama-cli": "/usr/local/bin/llama-cli"}), False),
            ("llama-cpp", FakeProbe("Linux", files=["/usr/local/bin/llama-server"],
                                    path={"llama-server": "/usr/local/bin/llama-server"}), True),
            ("lmstudio", FakeProbe("Darwin", dirs=["/Applications/LM Studio.app"]), False),
            ("lmstudio", FakeProbe("Darwin", files=["/Users/me/.lmstudio/bin/lms"],
                                   path={"lms": "/Users/me/.lmstudio/bin/lms"}), True),
            ("ollama", FakeProbe("Darwin", dirs=["/Applications/Ollama.app"]), False),
            ("ollama", FakeProbe("Linux", files=["/usr/local/bin/ollama"],
                                 path={"ollama": "/usr/local/bin/ollama"}), True),
            ("ollama", FakeProbe("Windows", files=[r"C:\Users\me\AppData\Local\Programs\Ollama\ollama.exe"],
                                 path={"ollama": r"C:\Users\me\AppData\Local\Programs\Ollama\ollama.exe"}), True),
            # found, but not where the command will look: a bare command would fail
            ("ollama", FakeProbe("Windows", files=[r"C:\Users\me\AppData\Local\Programs\Ollama\ollama.exe"]), False),
            ("lmstudio", FakeProbe("Darwin", files=["/Users/me/.lmstudio/bin/lms"]), False),
            ("llama-cpp", FakeProbe("Linux", files=["/usr/local/bin/llama-server"]), False),
            ("llama-cpp", FakeProbe("Linux", files=["/home/me/.local/bin/llama-server"]), False),
            # the serve script itself looks in the project's bin folder and ~/llama.cpp/build/bin
            ("llama-cpp", FakeProbe("Linux", files=["/home/me/proj/bin/llama-server"]), True),
            ("llama-cpp", FakeProbe("Linux", files=["/home/me/llama.cpp/build/bin/llama-server"]), True),
            ("llama-cpp", FakeProbe("Windows", files=[r"C:\proj\bin\llama-server.exe"]), True),
            ("llama-cpp", FakeProbe("Linux", files=["/opt/x/llama-server"], env={"LLAMA_SERVER": "/opt/x/llama-server"}), True),
        ]
        for tool_id, probe, expect_start in cases:
            with self.subTest(tool=tool_id, machine=probe.system, expect_start=expect_start):
                status, hint = self.hint_for(tool_id, probe)
                self.assertEqual(status, "installed")
                self.assertEqual("start" in hint, expect_start, hint)
                self.assertEqual("setup" in hint, not expect_start, "no start command means: say what is missing")
                self.assertTrue(hint["install"])

    def test_setup_message_names_the_missing_piece(self):
        _, hint = self.hint_for("llama-cpp", FakeProbe("Linux", pkgs={"llama-cpp-python": "0.3.1"}))
        self.assertIn("llama-server", hint["setup"])
        _, hint = self.hint_for("lmstudio", FakeProbe("Darwin", dirs=["/Applications/LM Studio.app"]))
        self.assertIn("lms", hint["setup"])
        _, hint = self.hint_for("ollama", FakeProbe("Darwin", dirs=["/Applications/Ollama.app"]))
        self.assertIn("ollama", hint["setup"])

    def test_setup_hint_says_where_the_program_is_when_it_is_not_reachable(self):
        _, hint = self.hint_for("lmstudio", FakeProbe("Darwin", files=["/Users/me/.lmstudio/bin/lms"]))
        self.assertIn("/Users/me/.lmstudio/bin/lms", hint["setup"])
        self.assertIn("PATH", hint["setup"])
        _, hint = self.hint_for("llama-cpp", FakeProbe("Linux", files=["/usr/local/bin/llama-server"]))
        self.assertIn("/usr/local/bin/llama-server", hint["setup"])
        self.assertIn("LLAMA_SERVER", hint["setup"])

    def test_nothing_to_set_up_when_not_installed_or_when_there_is_nothing_to_start(self):
        _, hint = self.hint_for("ollama", FakeProbe("Linux"))
        self.assertEqual(sorted(hint), ["install"])
        status, hint = self.hint_for("unsloth", FakeProbe("Linux", pkgs={"unsloth": "1.0"}))
        self.assertEqual((status, sorted(hint)), ("installed", ["install"]), "unsloth has no start command")

    def test_checking_only_runs_version_flags(self):
        self.tools()
        self.assertEqual(self.probe.ran, [["/usr/local/bin/ollama", "--version"]])

    def test_it_is_read_only(self):
        self.assertEqual(self.post("/api/tools", {})[0], 404)
        self.assertEqual(self.probe.ran, [])

    def test_wrong_host_is_refused(self):
        self.assertEqual(self.call("GET", "/api/tools", host="evil.example")[0], 403)

    def test_a_crash_in_detection_is_a_clean_error_not_a_dead_page(self):
        def boom(name):
            raise RuntimeError("disk on fire")
        self.probe.which = boom
        status, _, raw = self.call("GET", "/api/tools")
        self.assertEqual(status, 500)
        self.assertIn("error", json.loads(raw))
        self.assertEqual(self.call("GET", "/api/state")[0], 200, "server still alive")


class TestToolHintsCoverEveryTool(unittest.TestCase):
    def test_every_detected_tool_has_an_install_hint(self):
        self.assertEqual(set(ui_server.INSTALL_HINTS), set(ui_server.detect_tools.SPECS))

    def test_every_tool_gets_a_text_install_hint_on_every_system(self):
        """The page shows hint.install as-is: a missing 'default' key or a non-text value would break /api/tools."""
        for system in ("Windows", "Darwin", "Linux"):
            app = ui_server.App.__new__(ui_server.App)
            app.probe = FakeProbe(system)
            for tool in app.tools()["tools"]:
                with self.subTest(system=system, tool=tool["id"]):
                    install = tool["hint"]["install"]
                    self.assertIsInstance(install, str)
                    self.assertTrue(install.strip())


class TestApi(UiBase):
    def test_state(self):
        s = self.get_json("/api/state")
        self.assertEqual((s["ram_gb"], s["vram_gb"], s["mode"]), (16, 8, "gpu"))
        self.assertTrue(s["token"])
        self.assertIn("serve", s["serve_cmd"])

    def test_recommend_comes_from_the_catalog(self):
        m = self.get_json("/api/recommend?use=coding")["models"]
        self.assertTrue(m)
        self.assertTrue(all(x["id"] in self.app.offered for x in m))
        self.assertTrue({"title", "size_h", "verdict", "where", "tps", "have"} <= set(m[0]))
        self.assertNotIn("Q4_K_M", m[0]["title"])                       # the quantization is not part of the headline
        self.assertEqual(self.get_json("/api/recommend?use=nonsense")["models"], self.get_json("/api/recommend?use=chat")["models"])

    def test_more_searches_the_hub(self):
        d = self.get_json("/api/more?use=chat")
        repos = [x["repo"] for x in d["models"]]
        self.assertIn("bartowski/Mid-8B-GGUF", repos)
        self.assertNotIn("random/Hyped-7B-GGUF", repos)
        self.assertIn("random/Hyped-7B-GGUF", [x["repo"] for x in self.get_json("/api/more?use=chat&all=1")["models"]])

    def test_more_when_offline(self):
        self.fake_http_get = unittest.mock.Mock(side_effect=urllib.error.URLError("offline"))
        unittest.mock.patch.object(ms, "http_get", self.fake_http_get).start()
        self.addCleanup(unittest.mock.patch.stopall)
        self.assertIn("Could not reach", self.get_json("/api/more?use=chat")["error"])

    def test_radar(self):
        with unittest.mock.patch("hf_radar.load_latest") as mock_load, \
             unittest.mock.patch("hf_radar.sync_radar") as mock_sync:
            mock_load.return_value = None
            mock_sync.return_value = {
                "updated_at": "2026-11-01T00:00:00Z",
                "models": [
                    {"repo": "test/gpu-model", "fit_mode": "gpu", "tps": 25},
                    {"repo": "test/cpu-model", "fit_mode": "cpu", "tps": 5},
                ],
            }
            d = self.get_json("/api/radar?gpu_only=1")
            self.assertEqual(d["updated_at"], "2026-11-01T00:00:00Z")
            self.assertEqual(len(d["models"]), 1)
            self.assertEqual(d["models"][0]["repo"], "test/gpu-model")

    def test_radar_history(self):
        with unittest.mock.patch("hf_radar.compute_sync_diff") as mock_diff:
            mock_diff.return_value = {
                "latest_sync": "2026-11-01T00:00:00Z",
                "previous_sync": "2026-10-31T00:00:00Z",
                "summary": {"new_count": 1, "removed_count": 0, "persisted_count": 1, "gpu_ready_new": 1},
                "new_models": [{"repo": "test/new-model", "name": "new-model", "fit_mode": "gpu", "tps": 30}],
                "top_movers": [],
                "removed_models": [],
                "snapshots": [],
            }
            d = self.get_json("/api/radar/history")
            self.assertEqual(d["latest_sync"], "2026-11-01T00:00:00Z")
            self.assertEqual(len(d["new_models"]), 1)
            self.assertEqual(d["new_models"][0]["repo"], "test/new-model")


class TestInstall(UiBase):
    def wait_for(self, *states):
        for _ in range(100):
            j = self.app.snapshot()
            if j["state"] in states:
                return j
            time.sleep(0.05)
        self.fail(f"job stuck: {self.app.snapshot()}")

    def test_download_test_and_record(self):
        top = self.get_json("/api/recommend?use=chat")["models"][0]
        status, _ = self.post("/api/install", {"id": top["id"]})
        self.assertEqual(status, 202)
        j = self.wait_for("done", "error")
        self.assertEqual((j["state"], j["bench"], j["tps"]), ("done", "ok", 42))
        self.assertEqual(j["done"], j["total"])
        self.assertEqual(self.get_json("/api/progress")["state"], "done")
        self.assertTrue(any(ms.models_dir().glob("*.gguf")))
        self.assertEqual(ms.state_get("installed_repo"), top["repo"])
        self.assertTrue(self.get_json("/api/recommend?use=chat")["models"][0]["have"])

    def test_same_filename_from_another_repo_is_downloaded_not_reused(self):
        row = {"name": "Same-Q4", "size": 5, "tps": 20, "mode": "gpu", "files": [("model.gguf", 5)]}
        a = self.app.card({**row, "repo": "o/A-GGUF"})
        b = self.app.card({**row, "repo": "o/B-GGUF"})
        self.post("/api/install", {"id": a["id"]})
        self.wait_for("done")
        self.assertTrue(self.app.card({**row, "repo": "o/A-GGUF"})["have"])
        self.assertFalse(self.app.card({**row, "repo": "o/B-GGUF"})["have"])
        parts = []
        unittest.mock.patch.object(ms, "download", lambda repo, f, size, on_progress=None: parts.append(repo) or self.fake_download(repo, f, size, on_progress)).start()
        self.addCleanup(unittest.mock.patch.stopall)
        self.post("/api/install", {"id": b["id"]})
        self.wait_for("done")
        self.assertEqual(parts, ["o/B-GGUF"])
        self.assertEqual(len(list(ms.models_dir().glob("*.gguf"))), 2)

    def test_one_download_at_a_time(self):
        gate = threading.Event()

        def slow(repo, f, size, on_progress=None):
            gate.wait(5)
            return self.fake_download(repo, f, size, on_progress)
        unittest.mock.patch.object(ms, "download", slow).start()
        self.addCleanup(unittest.mock.patch.stopall)
        ids = [m["id"] for m in self.get_json("/api/recommend?use=chat")["models"]]
        self.assertEqual(self.post("/api/install", {"id": ids[0]})[0], 202)
        self.assertEqual(self.post("/api/install", {"id": ids[1]})[0], 409)
        gate.set()
        self.wait_for("done")

    def test_failed_download_reports_an_error(self):
        unittest.mock.patch.object(ms, "download", lambda *a, **k: None).start()
        self.addCleanup(unittest.mock.patch.stopall)
        mid = self.get_json("/api/recommend?use=chat")["models"][0]["id"]
        self.post("/api/install", {"id": mid})
        j = self.wait_for("error")
        self.assertIn("resume", j["error"])

    def test_split_model_downloads_every_part(self):
        parts = []
        unittest.mock.patch.object(ms, "download", lambda repo, f, size, on_progress=None: parts.append(f) or self.fake_download(repo, f, size, on_progress)).start()
        self.addCleanup(unittest.mock.patch.stopall)
        card = self.app.card({"repo": "o/Big-GGUF", "name": "Big-Q4_K_M", "size": 9, "tps": 20, "mode": "gpu",
                              "files": [("Big-Q4_K_M-00001-of-00002.gguf", 5), ("Big-Q4_K_M-00002-of-00002.gguf", 4)]})
        self.assertEqual(card["title"], "Big")
        self.post("/api/install", {"id": card["id"]})
        self.wait_for("done")
        self.assertEqual(parts, ["Big-Q4_K_M-00001-of-00002.gguf", "Big-Q4_K_M-00002-of-00002.gguf"])

    def test_missing_llama_bench_is_not_an_error(self):
        unittest.mock.patch.object(ms, "check_model_speed", lambda *a: 2).start()
        self.addCleanup(unittest.mock.patch.stopall)
        self.post("/api/install", {"id": self.get_json("/api/recommend?use=chat")["models"][0]["id"]})
        self.assertEqual(self.wait_for("done")["bench"], "skipped")


WIN_CURL = {"curl": r"C:\Windows\System32\curl.exe"}


class TestOsAwareHelp(UiBase):
    """Every command the page shows is built here, for the OS the server runs on, and only from programs that were
    found (rule 3). Regressions: Linux was told `brew install llama.cpp`; Windows got `python3 ...` (usually the
    Microsoft Store stub) and `curl` (an Invoke-WebRequest alias in Windows PowerShell 5, which rejects -L -C)."""

    def use(self, system, path=None):
        self.app.probe = FakeProbe(system, path=path or {})

    def install_hint(self, system, path=None):
        self.use(system, path)
        return self.get_json("/api/tools?tool=llama-cpp")["tools"][0]["hint"]

    def test_llama_cpp_install_hint_fits_the_os_and_needs_its_package_manager(self):
        cases = [
            ("Windows", {"winget": r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\winget.exe"}, "winget install ggml.llamacpp"),
            ("Darwin", {"brew": "/opt/homebrew/bin/brew"}, "brew install llama.cpp"),
            ("Linux", {"brew": "/home/linuxbrew/.linuxbrew/bin/brew"}, "brew install llama.cpp"),
        ]
        for system, path, cmd in cases:
            with self.subTest(system=system):
                hint = self.install_hint(system, path)
                self.assertEqual(hint["install_cmd"], cmd)
                self.assertIn(cmd, hint["install"])
        for system in ("Windows", "Darwin", "Linux"):
            with self.subTest(system=system, package_manager="missing"):
                hint = self.install_hint(system)
                self.assertNotIn("install_cmd", hint, "no command when its program is missing")
                self.assertNotRegex(hint["install"], r"^(brew|winget) ", hint["install"])
                self.assertNotRegex(hint["install"], r"https?://", "plain text, never links")
        self.assertIn("releases", self.install_hint("Linux")["install"])
        self.assertIn("Homebrew", self.install_hint("Darwin")["install"])

    def test_state_tells_the_page_the_os_and_how_to_get_llama_cpp(self):
        for system, name, serve in (("Windows", "windows", "scripts\\win\\serve.bat"),
                                    ("Darwin", "mac", "./scripts/unix/serve.sh"), ("Linux", "linux", "./scripts/unix/serve.sh")):
            with self.subTest(system=system):
                self.use(system, {"brew": "/usr/local/bin/brew"} if system == "Darwin" else {})
                s = self.get_json("/api/state")
                self.assertEqual((s["os"], s["serve_cmd"]), (name, serve))
                self.assertTrue(s["llama_install"]["install"])
        self.assertEqual(s["llama_install"].get("install_cmd"), None)                   # Linux without brew
        self.use("Darwin", {"brew": "/usr/local/bin/brew"})
        self.assertEqual(self.get_json("/api/state")["llama_install"]["install_cmd"], "brew install llama.cpp")

    def commands(self, system, path=None):
        self.use(system, path)
        return {c["kind"]: c for c in self.get_json("/api/recommend?use=chat")["models"][0]["commands"]}

    def test_download_commands_use_this_os_launcher_and_only_programs_that_were_found(self):
        win = self.commands("Windows", WIN_CURL)
        self.assertRegex(win["resume"]["cmd"], r'^scripts\\win\\radar\.bat --download "[^"]+/[^"]+" --file "[^"]+\.gguf"$')
        self.assertTrue(win["manual"]["cmd"].startswith("curl.exe -L -o "), win["manual"]["cmd"])
        lin = self.commands("Linux", {"curl": "/usr/bin/curl"})
        self.assertTrue(lin["resume"]["cmd"].startswith("./scripts/unix/radar.sh --download "))
        self.assertTrue(lin["manual"]["cmd"].startswith("curl -L -o "))
        self.assertEqual(set(self.commands("Linux")), {"resume"}, "no curl on PATH: no curl command")
        for cmds in (win, lin):
            self.assertNotIn("python3", " ".join(c["cmd"] for c in cmds.values()))
            self.assertNotIn("-C -", cmds["manual"]["cmd"], "curl cannot resume the app's .part file: do not claim it")

    def test_manual_download_lands_exactly_where_the_app_looks_for_the_model(self):
        top = self.get_json("/api/recommend?use=chat")["models"][0]
        offer = self.app.offered[top["id"]]
        f, size = offer["files"][0]
        dest, _ = ms.local_path(offer["repo"], f, size)
        self.use("Linux", {"curl": "/usr/bin/curl"})
        cmd = {c["kind"]: c for c in self.app.download_commands(offer)}["manual"]["cmd"]
        self.assertIn(f'-o "{dest}"', cmd)
        self.assertIn(f'/{offer["repo"]}/resolve/main/{f}"', cmd)

    def test_split_models_are_resumed_whole_not_by_their_first_part(self):
        self.use("Linux", {"curl": "/usr/bin/curl"})
        card = self.app.card({"repo": "o/Big-GGUF", "name": "Big-Q4_K_M", "size": 9, "tps": 20, "mode": "gpu",
                              "files": [("Big-00001-of-00002.gguf", 5), ("Big-00002-of-00002.gguf", 4)]})
        kinds = {c["kind"]: c["cmd"] for c in card["commands"]}
        self.assertEqual(kinds, {"resume": './scripts/unix/radar.sh --download "o/Big-GGUF"'})

    def test_a_split_download_started_in_a_terminal_is_resumed_whole(self):
        """Review finding: the state file only names the first shard (with the whole model's size). Rebuilding a
        one-file offer from it gave `--file <first shard>` and a shard-only curl command, which checked that shard
        against the whole size and never fetched the other parts."""
        self.use("Linux", {"curl": "/usr/bin/curl"})
        values = {"dl_active": "1", "dl_state": "downloading", "dl_repo": "o/Big-GGUF",
                  "dl_file": "Big-Q4_K_M-00001-of-00003.gguf", "dl_done": "1", "dl_total": "30"}
        with unittest.mock.patch.object(ms, "state_get", side_effect=lambda k: values.get(k, "")):
            snap = self.app.snapshot()
        self.assertEqual([(c["kind"], c["cmd"]) for c in snap["commands"]],
                         [("resume", './scripts/unix/radar.sh --download "o/Big-GGUF"')])

    def test_a_failed_download_offers_the_resume_that_really_resumes(self):
        self.use("Windows", WIN_CURL)
        unittest.mock.patch.object(ms, "download", lambda *a, **k: None).start()
        self.addCleanup(unittest.mock.patch.stopall)
        mid = self.get_json("/api/recommend?use=chat")["models"][0]["id"]
        self.post("/api/install", {"id": mid})
        for _ in range(100):
            j = self.get_json("/api/progress")
            if j["state"] == "error":
                break
            time.sleep(0.05)
        self.assertEqual(j["state"], "error")
        self.assertEqual(j["commands"][0]["kind"], "resume")
        self.assertTrue(j["commands"][0]["cmd"].startswith("scripts\\win\\radar.bat --download"))
        self.assertNotIn("curl_cmd", j)

    def test_radar_and_terminal_downloads_carry_commands_too(self):
        self.use("Linux")
        with unittest.mock.patch("hf_radar.load_latest") as load:
            load.return_value = {"updated_at": "2026-11-01T00:00:00Z",
                                 "models": [{"repo": "t/m-GGUF", "file": "m.gguf", "size_bytes": 7, "fit_mode": "gpu"}]}
            m = self.get_json("/api/radar")["models"][0]
        self.assertEqual(m["commands"][0]["cmd"], './scripts/unix/radar.sh --download "t/m-GGUF" --file "m.gguf"')
        values = {"dl_active": "1", "dl_state": "downloading", "dl_repo": "t/m-GGUF", "dl_file": "m.gguf",
                  "dl_done": "1", "dl_total": "7"}
        with unittest.mock.patch.object(ms, "state_get", side_effect=lambda k: values.get(k, "")):
            snap = self.app.snapshot()
        self.assertEqual(snap["source"], "terminal")
        self.assertEqual(snap["commands"][0]["kind"], "resume")


FAKE_SERVER = [sys.executable, str(HERE / "fake_llama_server.py")]


class TestChatApi(UiBase):
    """Start chatting: /api/chat (status and what it would run), /api/chat/start and /api/chat/stop.
    llama-server is tests/fake_llama_server.py, a real process on a free localhost port."""

    def setUp(self):
        super().setUp()
        import test_chat_server as tcs
        self.tcs = tcs
        self.chat_port = tcs.free_port()
        p = unittest.mock.patch.dict("os.environ", {"PORT": str(self.chat_port), "EXTRA_ARGS": "-c 4096"})
        p.start()
        self.addCleanup(p.stop)
        self.app.chat.find_server = lambda: list(FAKE_SERVER)
        self.addCleanup(self.app.chat.stop)
        self.top = self.get_json("/api/recommend?use=chat")["models"][0]

    def download(self):
        self.assertEqual(self.post("/api/install", {"id": self.top["id"]})[0], 202)
        for _ in range(100):
            if self.app.snapshot()["state"] == "done":
                return self.app.snapshot()
            time.sleep(0.05)
        self.fail(self.app.snapshot())

    def chat(self, path="/api/chat"):
        return self.get_json(path)

    def wait_chat(self, *states):
        for _ in range(400):
            s = self.chat()["chat"]
            if s["state"] in states:
                return s
            time.sleep(0.05)
        self.fail(f"chat never reached {states}: {self.chat()}")

    def test_finished_download_names_the_model_to_chat_with(self):
        self.assertEqual(self.download()["id"], self.top["id"])

    def test_preview_shows_the_exact_command_with_port_and_extra_args_from_the_environment(self):
        self.download()
        offer = self.app.offered[self.top["id"]]
        model, _ = ms.local_path(offer["repo"], *offer["files"][0])
        p = self.chat("/api/chat?id=" + urllib.parse.quote(self.top["id"]))["preview"]
        self.assertTrue(p["cmd"].endswith(f"--port {self.chat_port} -c 4096"), p["cmd"])
        self.assertIn(str(model), p["cmd"])
        self.assertIsNone(p["busy"])

    def test_start_runs_and_stop_stops(self):
        self.download()
        status, body = self.post("/api/chat/start", {"id": self.top["id"]})
        self.assertEqual(status, 202, body)
        s = self.wait_chat("running")
        self.assertEqual(s["url"], f"http://127.0.0.1:{self.chat_port}/")
        self.assertEqual(s["model"], self.top["title"])
        self.assertEqual(self.get_json("/api/state")["chat"]["state"], "running")
        status, body = self.post("/api/chat/stop", {})
        self.assertEqual((status, body["state"]), (200, "stopped"))

    def test_a_failed_start_is_reported_with_its_log(self):
        self.download()
        with unittest.mock.patch.dict("os.environ", {"FAKE_LLAMA_EXIT": "1"}):
            self.post("/api/chat/start", {"id": self.top["id"]})
            s = self.wait_chat("failed")
        self.assertIn("failed to load model", "\n".join(s["log"]))

    def test_busy_port_is_explained_and_the_next_free_port_can_be_used(self):
        self.download()
        occ = self.tcs.Occupied(self)
        with unittest.mock.patch.dict("os.environ", {"PORT": str(occ.port)}):
            preview = self.chat("/api/chat?id=" + urllib.parse.quote(self.top["id"]))["preview"]
            self.assertEqual(preview["busy"]["port"], occ.port)
            status, body = self.post("/api/chat/start", {"id": self.top["id"]})
            self.assertEqual(status, 409)
            free = body["port_busy"]["free_port"]
            self.assertIn("OtherApp/1.0", body["error"])
            self.assertEqual(self.post("/api/chat/start", {"id": self.top["id"], "port": free})[0], 202)
            self.assertEqual(self.wait_chat("running")["port"], free)

    def test_only_downloaded_models_that_were_offered_can_be_started(self):
        self.assertEqual(self.post("/api/chat/start", {"id": "evil/Repo|x.gguf"})[0], 404)
        status, body = self.post("/api/chat/start", {"id": self.top["id"]})        # offered, not downloaded
        self.assertEqual(status, 409)
        self.assertIn("not downloaded", body["error"])
        self.assertEqual(self.post("/api/chat/start", {"model": "/etc/passwd"})[0], 404)   # no raw paths
        self.assertEqual(self.app.chat.status()["state"], "idle")

    def test_port_from_the_page_must_be_a_real_unprivileged_port(self):
        self.download()
        for bad in (0, 80, 65536, "8081", 8081.5, True):
            with self.subTest(port=bad):
                self.assertEqual(self.post("/api/chat/start", {"id": self.top["id"], "port": bad})[0], 400)

    def test_start_and_stop_are_post_only_behind_the_token_host_and_origin_checks(self):
        self.download()
        for path, body in (("/api/chat/start", {"id": self.top["id"]}), ("/api/chat/stop", {})):
            with self.subTest(path=path):
                self.assertEqual(self.post(path, body, token=False)[0], 403)
                self.assertEqual(self.post(path, body, headers={"Origin": "https://evil.example"})[0], 403)
                self.assertEqual(self.call("POST", path, body, {"X-LP-Token": self.app.token}, host="evil.example")[0], 403)
                self.assertEqual(self.call("GET", path)[0], 404, "changing things is POST only")
        self.assertEqual(self.app.chat.status()["state"], "idle")

    def test_without_llama_server_there_is_no_command_and_no_start(self):
        """Rule 3: say what is missing instead of showing a command."""
        self.download()
        self.app.chat.find_server = lambda: []
        p = self.chat("/api/chat?id=" + urllib.parse.quote(self.top["id"]))["preview"]
        self.assertNotIn("cmd", p)
        self.assertIn("llama-server was not found", p["missing"])
        self.assertEqual(self.post("/api/chat/start", {"id": self.top["id"]})[0], 409)

    def test_closing_the_page_server_stops_the_chat_it_started(self):
        self.download()
        self.post("/api/chat/start", {"id": self.top["id"]})
        self.wait_chat("running")
        self.app.close()
        self.assertEqual(self.app.chat.status()["state"], "stopped")

    def test_who_uses_the_port_is_asked_of_the_pinned_machine_not_the_host(self):
        """Rule 2: the lookup programs come from the (fake) probe, and the OS rules from its system."""
        self.download()
        occ = self.tcs.Occupied(self)
        self.app.probe = FakeProbe("Windows", path={"netstat": r"C:\Windows\System32\netstat.exe"},
                                   output={r"C:\Windows\System32\netstat.exe": ""})
        with unittest.mock.patch.dict("os.environ", {"PORT": str(occ.port)}):
            busy = self.chat("/api/chat?id=" + urllib.parse.quote(self.top["id"]))["preview"]["busy"]
        self.assertTrue(any(line.startswith("netstat:") for line in busy["looked"]), busy["looked"])
        self.assertEqual(self.app.probe.ran[0][0], r"C:\Windows\System32\netstat.exe")


class TestLlamaApi(UiBase):
    """Install llama.cpp from the page: /api/llama (what was found, why an install is offered, how) and
    /api/llama/install. The installer's own behaviour is in test_llama_install.py; this is the wiring and the rules."""

    def setUp(self):
        super().setUp()
        import test_llama_install as tli
        self.tli = tli
        self.bin = self.tmp / "proj" / "bin"
        self.release = json.loads(json.dumps(tli.RELEASE))
        data = tli.tar_bytes("llama-b7777", {"llama-server": b"FAKE-OK"})
        for a in self.release["assets"]:
            if a["name"] == "llama-b7777-bin-ubuntu-x64.tar.gz":
                a.update(size=len(data), digest=None)
                self.archives = {a["browser_download_url"]: data}
        self.app.bin_dir = self.bin
        # as hardware.find_llama_server: a copy found earlier in the lookup order wins, else the one in bin/
        exe = self.bin / "llama-server"
        p = unittest.mock.patch.object(ms, "find_llama_server", lambda: self.found_server or (str(exe) if exe.is_file() else ""))
        p.start()
        self.addCleanup(p.stop)
        self.app.installer = self.app.make_installer(fetch_json=lambda url: self.release, fetch_file=self.fetch_file,
                                                     version=tli.fake_version)
        self.hw = ms.Hw(ram_mb=16384, cores=8)                  # no GPU unless a test says so
        self.app.hw = self.hw

    def fetch_file(self, url, dest, on_progress=None):
        Path(dest).write_bytes(self.archives[url])

    def llama(self):
        return self.get_json("/api/llama")

    def test_why_an_install_is_offered(self):
        self.assertEqual(self.llama()["need"], "missing")
        self.found_server = "/opt/llama/llama-server"
        self.app.llama_version = lambda argv: (False, "error while loading shared libraries")
        s = self.llama()
        self.assertEqual((s["need"], s["found"], s["works"]), ("broken", "/opt/llama/llama-server", False))
        self.assertFalse(self.get_json("/api/state")["llama_server"], "found but cannot run is not 'llama-server found'")
        self.app.llama_version = lambda argv: (True, "version: 4242 (abc1234)")
        self.app.hw = ms.Hw(ram_mb=16384, cores=8, gpu_kind="nvidia", gpu_name="G", vram_mb=8192, gpu_usable=False)
        self.assertEqual(self.llama()["need"], "no-gpu")
        self.app.hw.gpu_usable = True
        s = self.llama()
        self.assertEqual((s["need"], s["version"]), ("", "version: 4242 (abc1234)"))
        self.assertTrue(self.get_json("/api/state")["llama_server"])

    def test_offer_depends_on_the_os_and_on_brew_being_found(self):
        self.assertEqual(self.llama()["offer"]["how"], "download")
        self.app.probe = FakeProbe("Darwin")
        self.assertEqual(self.llama()["offer"]["how"], "manual")
        self.app.probe = FakeProbe("Darwin", path={"brew": "/opt/homebrew/bin/brew"})
        self.assertEqual(self.llama()["offer"], {"how": "brew", "cmd": "brew install llama.cpp"})

    def test_installs_into_bin_and_the_page_then_finds_it(self):
        status, body = self.post("/api/llama/install", {})
        self.assertEqual(status, 202, body)
        for _ in range(200):
            job = self.llama()["job"]
            if job["state"] in ("done", "failed"):
                break
            time.sleep(0.02)
        self.assertEqual(job["state"], "done", job)
        self.assertTrue((self.bin / "llama-server").is_file())
        self.found_server = str(self.bin / "llama-server")
        self.assertEqual(self.llama()["need"], "")

    def test_install_is_refused_when_a_working_llama_server_can_use_the_gpu(self):
        self.found_server = "/opt/llama/llama-server"
        status, body = self.post("/api/llama/install", {})
        self.assertEqual(status, 409)
        self.assertIn("already", body["error"])

    def test_install_is_refused_while_the_chat_is_running(self):
        """Windows cannot replace a running llama-server.exe; and a chat should not lose its server mid-answer."""
        self.app.chat.job = {"state": "running"}
        self.addCleanup(setattr, self.app.chat, "job", {"state": "idle"})
        status, body = self.post("/api/llama/install", {})
        self.assertEqual(status, 409)
        self.assertIn("Stop the chat", body["error"])

    def test_install_is_post_only_behind_the_token_host_and_origin_checks(self):
        self.assertEqual(self.post("/api/llama/install", {}, token=False)[0], 403)
        self.assertEqual(self.post("/api/llama/install", {}, headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.call("POST", "/api/llama/install", {}, {"X-LP-Token": self.app.token}, host="evil.example")[0], 403)
        self.assertEqual(self.call("GET", "/api/llama/install")[0], 404)
        self.assertEqual(self.post("/api/llama/install", {"variant": "../../x"})[0], 400)
        self.assertEqual(self.app.installer.status()["state"], "idle")

    def test_an_amd_gpu_gets_the_vulkan_build_and_the_page_says_it_is_unused(self):
        """AMD / Intel Arc: the installer picks Vulkan, and the page says the current build cannot use the card.
        Recommendations stay CPU-based (gpu_kind is unchanged), as for existing users."""
        self.app.hw = ms.Hw(ram_mb=16384, cores=8)
        self.app.hw.other_gpu, self.app.hw.other_gpu_usable = "AMD Radeon RX 6800", False
        self.found_server = "/opt/llama/llama-server"
        offer = self.llama()["offer"]
        self.assertEqual((offer["how"], offer["kind"]), ("download", "vulkan"))
        self.assertEqual(self.llama()["need"], "no-gpu")
        s = self.get_json("/api/state")
        self.assertTrue(s["gpu_unused"])
        self.assertEqual(s["mode"], "cpu")

    def test_the_installer_is_told_the_drivers_cuda_version(self):
        self.app.hw = ms.Hw(ram_mb=16384, cores=8, gpu_kind="nvidia", gpu_name="G", vram_mb=8192, gpu_usable=False)
        self.app.hw.cuda_version = "12.4"
        self.assertEqual(self.app.installer.cuda_max(), "12.4")

    def test_hardware_is_detected_again_after_an_install(self):
        """A CUDA build makes the GPU usable: recommendations must follow."""
        calls = []
        unittest.mock.patch.object(ms, "detect_hw", lambda: calls.append(1) or self.hw).start()
        self.addCleanup(unittest.mock.patch.stopall)
        self.post("/api/llama/install", {})
        for _ in range(200):
            if self.llama()["job"]["state"] in ("done", "failed"):
                break
            time.sleep(0.02)
        self.llama()
        self.assertTrue(calls, "hardware was not detected again after the install")


class TestRadarOffline(UiBase):
    def test_a_sync_that_cannot_reach_the_hub_says_so_and_keeps_the_saved_scan(self):
        saved = {"updated_at": "2026-10-30T00:00:00Z", "models": [{"repo": "t/saved-GGUF", "fit_mode": "gpu"}]}
        with unittest.mock.patch("hf_radar.http_json", return_value=None), \
                unittest.mock.patch("hf_radar.load_latest", return_value=saved):
            d = self.get_json("/api/radar?sync=1")
        self.assertTrue(d["offline"])
        self.assertEqual([m["repo"] for m in d["models"]], ["t/saved-GGUF"])
        self.assertEqual(d["updated_at"], "2026-10-30T00:00:00Z")


class TestServerBind(unittest.TestCase):
    def test_the_page_server_binds_without_a_host_name_lookup(self):
        """HTTPServer.server_bind calls socket.getfqdn(), which can take seconds on macOS (seen on the macOS CI
        runner), and serve() may try 20 ports. The page server only needs to bind."""
        import socket
        with unittest.mock.patch.object(socket, "getfqdn", side_effect=AssertionError("getfqdn called")):
            s = ui_server.Server(("127.0.0.1", 0), ui_server.BaseHTTPRequestHandler)
        self.addCleanup(s.server_close)
        self.assertEqual(s.server_address[0], "127.0.0.1")


class TestServe(unittest.TestCase):
    """serve() takes the first free port from `port` upward.

    Regression (rule 2): this used to hold a real OS-assigned port P and assume one of P+1..P+19 was free. On the
    Windows CI runner that whole range was unavailable (Windows reserves blocks of ports around 49xxx, and other
    test servers use ephemeral ports), so the test failed by machine, not by code. The ports are now simulated."""

    def run_serve(self, busy, port=8765):
        tried, started = [], []

        class FakeServer:
            def __init__(self, addr, handler):
                tried.append(addr[1])
                if addr[1] in busy:
                    raise OSError(98, "Address already in use")
                self.server_address = addr

            def serve_forever(self):
                started.append(self.server_address[1])
                raise KeyboardInterrupt

            def server_close(self):
                pass

        out = io.StringIO()
        with unittest.mock.patch.object(ui_server, "App", lambda ms_: None), \
                unittest.mock.patch.object(ui_server, "make_handler", lambda app: None), \
                unittest.mock.patch.object(ui_server, "Server", FakeServer), \
                unittest.mock.patch("sys.stdout", out):
            rc = ui_server.serve(None, port, open_browser=False)
        return rc, tried, started, out.getvalue()

    def test_busy_port_falls_forward(self):
        rc, tried, started, _ = self.run_serve(busy={8765, 8766})
        self.assertEqual(rc, 0)
        self.assertEqual(tried, [8765, 8766, 8767])
        self.assertEqual(started, [8767])

    def test_no_free_port_in_range_is_a_clear_error(self):
        rc, tried, started, text = self.run_serve(busy=set(range(8765, 8785)))
        self.assertEqual(rc, 1)
        self.assertEqual(tried, list(range(8765, 8785)))
        self.assertEqual(started, [])
        self.assertIn("Could not open a port between 8765 and 8784", text)


if __name__ == "__main__":
    unittest.main()
