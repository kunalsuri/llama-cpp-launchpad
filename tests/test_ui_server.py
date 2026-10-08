"""Tests for utils/ui_server.py (the `model-setup --ui` page). A real server on a random localhost port,
a fake Hugging Face, a fake downloader. No network, GPU or llama.cpp needed.
Run: python3 -m unittest discover -s tests -v
"""
import http.client
import json
import re
import sys
import threading
import time
import unittest
import unittest.mock
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "utils"))
sys.path.insert(0, str(HERE))
import model_setup as ms  # noqa: E402
import test_hf_discover as thd  # noqa: E402  (module import: its test classes are not collected twice)
import test_model_setup as tms  # noqa: E402
import ui_server  # noqa: E402


class UiBase(tms.Base):
    def setUp(self):
        super().setUp()
        hw = ms.Hw(ram_mb=16384, cores=8, gpu_kind="nvidia", gpu_name="Test GPU", vram_mb=8192, gpu_usable=True)
        for target, value in (("detect_hw", lambda: hw), ("download", self.fake_download),
                              ("check_model_speed", self.fake_speed)):
            p = unittest.mock.patch.object(ms, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.app = ui_server.App(ms)
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
        path = ms.models_dir() / Path(f).name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
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

    def test_unknown_paths_are_404_and_there_is_no_file_serving(self):
        for path in ("/etc/passwd", "/../README.md", "/utils/model_setup.py", "/ui/setup/index.html"):
            self.assertEqual(self.call("GET", path)[0], 404, path)


class TestGuards(UiBase):
    def test_wrong_host_is_refused(self):
        for host in ("evil.example", f"evil.example:{self.port}", f"127.0.0.1:{self.port + 1}", "127.0.0.1"):
            self.assertEqual(self.call("GET", "/api/state", host=host)[0], 403, host)
        self.assertEqual(self.call("GET", "/api/state", host=f"localhost:{self.port}")[0], 200)

    def test_post_needs_the_token(self):
        self.assertEqual(self.post("/api/install", {"id": "x"}, token=False)[0], 403)
        self.assertEqual(self.post("/api/install", {"id": "x"}, headers={"X-LP-Token": "wrong"})[0], 403)

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


class TestServe(unittest.TestCase):
    def test_busy_port_falls_forward(self):
        busy = ThreadingHTTPServer(("127.0.0.1", 0), ui_server.BaseHTTPRequestHandler)
        self.addCleanup(busy.server_close)
        port = busy.server_address[1]
        started = []

        class Stop(Exception):
            pass

        def fake_forever(self_):
            started.append(self_.server_address[1])
            raise KeyboardInterrupt

        with unittest.mock.patch.object(ui_server, "App", lambda ms_: None), \
                unittest.mock.patch.object(ui_server, "make_handler", lambda app: ui_server.BaseHTTPRequestHandler), \
                unittest.mock.patch.object(ThreadingHTTPServer, "serve_forever", fake_forever):
            self.assertEqual(ui_server.serve(None, port, open_browser=False), 0)
        self.assertEqual(len(started), 1)
        self.assertNotEqual(started[0], port)


if __name__ == "__main__":
    unittest.main()
