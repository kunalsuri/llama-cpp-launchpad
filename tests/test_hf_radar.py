"""Tests for utils/hf_radar.py (offline, mocked)."""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "utils"))
sys.path.insert(0, str(HERE))

import hardware
import hf_radar


class TestRadarClusters(unittest.TestCase):
    def test_classify_coding(self):
        meta = {"id": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF", "tags": ["code"]}
        clusters = hf_radar.classify_clusters(meta, "qwen2.5-coder-7b")
        self.assertIn("coding", clusters)

    def test_classify_agentic(self):
        meta = {"id": "pragmaticcs/MiMo-HERO-Frontier-Agentic-Coder-9B-GGUF"}
        clusters = hf_radar.classify_clusters(meta)
        self.assertIn("agentic", clusters)
        self.assertIn("coding", clusters)

    def test_classify_reasoning(self):
        meta = {"id": "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B-GGUF"}
        clusters = hf_radar.classify_clusters(meta)
        self.assertIn("reasoning", clusters)

    def test_classify_creative(self):
        meta = {"id": "JonathanColetti/Qwen3.8-27B-Uncensored-GGUF"}
        clusters = hf_radar.classify_clusters(meta)
        self.assertIn("creative", clusters)

    def test_classify_chat_fallback(self):
        meta = {"id": "author/plain-general-model"}
        clusters = hf_radar.classify_clusters(meta)
        self.assertEqual(clusters, ["chat"])


class TestRadarHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_record_and_load_latest(self):
        models = [
            {
                "repo": "test/model-1",
                "name": "model-1-Q4_K_M",
                "quant": "Q4_K_M",
                "size_bytes": 4000000000,
                "size_mb": 3814.7,
                "arch": "qwen2",
                "params_b": 7.0,
                "moe": False,
                "fit_mode": "gpu",
                "tps": 25,
                "verdict": "smooth",
                "downloads": 50000,
                "likes": 500,
                "created_at": "2026-10-01",
                "compat": "ok",
                "other_quants": 2,
            }
        ]
        hf_radar.record_history(models, self.tmp)
        latest = hf_radar.load_latest(self.tmp)
        self.assertIsNotNone(latest)
        self.assertEqual(len(latest["models"]), 1)
        self.assertEqual(latest["models"][0]["repo"], "test/model-1")
        self.assertIn("clusters", latest["models"][0])

        # History log check
        entries = hf_radar.load_history_entries(self.tmp, days=30)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["repo"], "test/model-1")

    def test_compute_sync_diff(self):
        snap_dir = self.tmp / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)

        snap1 = {
            "updated_at": "2026-10-31T00:00:00Z",
            "models": [
                {
                    "repo": "common/model",
                    "name": "common-model",
                    "fit_mode": "gpu",
                    "tps": 20,
                    "downloads": 1000,
                    "likes": 50,
                },
                {
                    "repo": "old/retired-model",
                    "name": "retired-model",
                    "fit_mode": "cpu",
                    "tps": 10,
                    "downloads": 500,
                    "likes": 20,
                },
            ],
        }
        (snap_dir / "2026-10-31.json").write_text(json.dumps(snap1), encoding="utf-8")

        snap2 = {
            "updated_at": "2026-11-01T00:00:00Z",
            "models": [
                {
                    "repo": "common/model",
                    "name": "common-model",
                    "fit_mode": "gpu",
                    "tps": 20,
                    "downloads": 1500,
                    "likes": 75,
                },
                {
                    "repo": "new/agentic-coder",
                    "name": "agentic-coder-q4",
                    "fit_mode": "gpu",
                    "tps": 35,
                    "downloads": 800,
                    "likes": 120,
                },
            ],
        }
        (snap_dir / "2026-11-01.json").write_text(json.dumps(snap2), encoding="utf-8")
        (self.tmp / "latest.json").write_text(json.dumps(snap2), encoding="utf-8")

        diff = hf_radar.compute_sync_diff(self.tmp)
        self.assertTrue(diff["has_previous"])
        self.assertEqual(diff["summary"]["new_count"], 1)
        self.assertEqual(diff["summary"]["removed_count"], 1)
        self.assertEqual(diff["summary"]["persisted_count"], 1)
        self.assertEqual(diff["summary"]["gpu_ready_new"], 1)
        self.assertEqual(diff["new_models"][0]["repo"], "new/agentic-coder")
        self.assertEqual(diff["removed_models"][0]["repo"], "old/retired-model")
        self.assertEqual(diff["top_movers"][0]["delta_downloads"], 500)
        self.assertEqual(diff["top_movers"][0]["delta_likes"], 25)

        rendered = hf_radar.render_history_diff(diff)
        self.assertIn("WHAT CHANGED SINCE LAST SYNC", rendered)
        self.assertIn("new/agentic-coder", rendered)
        self.assertIn("common/model", rendered)
        self.assertIn("old/retired-model", rendered)

    def test_render_dashboard_with_cluster_filter(self):
        data = {
            "updated_at": "2026-11-01T00:00:00Z",
            "models": [
                {
                    "repo": "test/coder-7b",
                    "name": "coder-7b-q4",
                    "quant": "Q4_K_M",
                    "size_mb": 4000.0,
                    "fit_mode": "gpu",
                    "tps": 20,
                    "clusters": ["coding", "chat"],
                },
                {
                    "repo": "test/chat-7b",
                    "name": "chat-7b-q4",
                    "quant": "Q4_K_M",
                    "size_mb": 4000.0,
                    "fit_mode": "gpu",
                    "tps": 20,
                    "clusters": ["chat"],
                },
            ],
        }
        text_coding = hf_radar.render_dashboard(data, cluster="coding", limit=10)
        self.assertIn("test/coder-7b", text_coding)
        self.assertNotIn("test/chat-7b", text_coding)

        text_all = hf_radar.render_dashboard(data, cluster="all", limit=10)
        self.assertIn("test/coder-7b", text_all)
        self.assertIn("test/chat-7b", text_all)


class TestRadarEvaluation(unittest.TestCase):
    def test_evaluate_repo_no_siblings(self):
        hw = hardware.Hw(
            ram_mb=49152,
            cores=14,
            gpu_kind="apple",
            gpu_name="Apple Silicon",
            vram_mb=0,
            gpu_usable=True,
        )
        res = hf_radar.evaluate_repo({"id": "some/repo"}, [], hw)
        self.assertIsNone(res)

    def test_evaluate_repo_valid_gguf(self):
        hw = hardware.Hw(
            ram_mb=49152,
            cores=14,
            gpu_kind="apple",
            gpu_name="Apple Silicon",
            vram_mb=0,
            gpu_usable=True,
        )
        meta = {
            "id": "author/test-7b-gguf",
            "modelId": "author/test-7b-gguf",
            "downloads": 12000,
            "likes": 340,
            "createdAt": "2026-10-15T00:00:00.000Z",
            "tags": ["gguf", "code"],
        }
        siblings = [
            {"rfilename": "test-7b-Q4_K_M.gguf", "size": 4500000000},
            {"rfilename": "test-7b-Q8_0.gguf", "size": 8000000000},
        ]
        res = hf_radar.evaluate_repo(meta, siblings, hw)
        self.assertIsNotNone(res)
        self.assertEqual(res["repo"], "author/test-7b-gguf")
        self.assertIn(res["quant"], ("Q8_0", "Q4_K_M"))
        self.assertEqual(res["fit_mode"], "gpu")
        self.assertGreater(res["tps"], 0)
        self.assertIn("clusters", res)
        self.assertIn("coding", res["clusters"])


class TestRadarSync(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    @mock.patch("hf_radar.fetch_hf_repos")
    def test_sync_radar_mocked(self, mock_repos):
        mock_repos.return_value = [
            {
                "id": "test/model-gguf",
                "downloads": 500,
                "likes": 50,
                "createdAt": "2026-10-20T00:00:00Z",
                "siblings": [{"rfilename": "model-Q4_K_M.gguf", "size": 2000000000}],
            }
        ]
        hw = hardware.Hw(
            ram_mb=49152,
            cores=14,
            gpu_kind="apple",
            gpu_name="Apple Silicon",
            vram_mb=0,
            gpu_usable=True,
        )
        data = hf_radar.sync_radar(hw, hdir=self.tmp, max_repos=5)
        self.assertEqual(data["total_compatible"], 1)
        self.assertTrue((self.tmp / "latest.json").is_file())


class TestRadarMain(unittest.TestCase):
    @mock.patch("hf_radar.load_latest")
    def test_main_cli_dashboard(self, mock_load):
        mock_load.return_value = {
            "updated_at": "2026-11-01T00:00:00Z",
            "models": [],
        }
        ret = hf_radar.main(["--cli", "--dashboard", "--cluster", "coding"])
        self.assertEqual(ret, 0)

    @mock.patch("hf_radar.compute_sync_diff")
    def test_main_cli_history(self, mock_diff):
        mock_diff.return_value = {
            "has_previous": True,
            "latest_sync": "2026-11-01T00:00:00Z",
            "previous_sync": "2026-10-31T00:00:00Z",
            "summary": {"new_count": 0, "removed_count": 0, "persisted_count": 0, "gpu_ready_new": 0},
            "new_models": [],
            "top_movers": [],
            "removed_models": [],
        }
        ret = hf_radar.main(["--history", "--cli"])
        self.assertEqual(ret, 0)

    @mock.patch("hf_radar.load_latest")
    def test_main_json(self, mock_load):
        mock_load.return_value = {
            "updated_at": "2026-11-01T00:00:00Z",
            "models": [],
        }
        ret = hf_radar.main(["--json"])
        self.assertEqual(ret, 0)

    @mock.patch("ui_server.serve")
    @mock.patch("hf_radar.load_latest")
    def test_main_ui_launch(self, mock_load, mock_serve):
        mock_load.return_value = {
            "updated_at": "2026-11-01T00:00:00Z",
            "models": [],
        }
        mock_serve.return_value = 0
        ret = hf_radar.main(["--ui", "--port", "9999", "--no-browser"])
        self.assertEqual(ret, 0)
        mock_serve.assert_called_once()
        _, kwargs = mock_serve.call_args
        self.assertEqual(kwargs.get("port"), 9999)
        self.assertEqual(kwargs.get("initial_hash"), "#radar")
        self.assertEqual(kwargs.get("open_browser"), False)


class TestAppRadarApi(unittest.TestCase):
    """Regression (rule 2): this used to read the real radar folder, the real hardware and, with no saved scan,
    the real Hugging Face, so it passed only on a machine that had synced before. Now everything is pinned."""

    def setUp(self):
        import model_setup
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict("os.environ", {"LP_RADAR_DIR": str(self.tmp / "radar"),
                                             "STATE_FILE": str(self.tmp / "state"), "MODELS_DIR": str(self.tmp / "m")})
        env.start()
        self.addCleanup(env.stop)
        hw = hardware.Hw(ram_mb=16384, cores=8, gpu_kind="nvidia", gpu_name="Test GPU", vram_mb=8192, gpu_usable=True)
        for target, value in ((model_setup, "detect_hw"), (hf_radar, "http_json")):
            fake = (lambda: hw) if value == "detect_hw" else self.no_network
            p = mock.patch.object(target, value, fake)
            p.start()
            self.addCleanup(p.stop)
        old = [{"repo": "a/old-coder-GGUF", "name": "old-coder-Q4_K_M", "size_bytes": 2 << 30, "downloads": 10,
                "fit_mode": "gpu", "tps": 40, "clusters": ["coding"]}]
        new = old + [{"repo": "b/new-chat-GGUF", "name": "new-chat-Q4_K_M", "size_bytes": 3 << 30, "downloads": 5,
                      "fit_mode": "cpu", "tps": 9, "clusters": ["chat"]}]
        snaps = self.tmp / "radar" / "snapshots"
        snaps.mkdir(parents=True)
        for day, models in (("2026-10-31", old), ("2026-11-01", new)):
            (snaps / f"{day}.json").write_text(json.dumps({"updated_at": day + "T08:00:00Z", "models": models}))
        (self.tmp / "radar" / "latest.json").write_text(json.dumps({"updated_at": "2026-11-01T08:00:00Z", "models": new}))

    def no_network(self, url, timeout=25):
        raise AssertionError("tried to reach the network: " + url)

    def test_app_radar_clusters_and_history(self):
        import model_setup
        import ui_server

        app = ui_server.App(model_setup)
        data = app.radar()
        self.assertEqual(data["updated_at"], "2026-11-01T08:00:00Z")
        self.assertEqual(len(data["models"]), 2)
        for m in data["models"]:
            self.assertIn("clusters", m)
            self.assertIn("file", m)
            self.assertIn("download_url", m)

        coding_data = app.radar(cluster="coding")
        self.assertEqual([m["repo"] for m in coding_data["models"]], ["a/old-coder-GGUF"])

        hist = app.radar_history()
        self.assertIn("summary", hist)
        self.assertEqual([m["repo"] for m in hist["new_models"]], ["b/new-chat-GGUF"])
        self.assertIn("snapshots", hist)
        self.assertEqual(len(app.offered), 2)

        # Verify offered entries have exact file and download_url
        for mid, offer in app.offered.items():
            self.assertIn("file", offer)
            self.assertIn("files", offer)
            self.assertIn("download_url", offer)
            self.assertTrue(offer["download_url"].startswith("https://huggingface.co/"))

    def test_app_snapshot_reflects_terminal_download(self):
        import model_setup
        import ui_server

        app = ui_server.App(model_setup)        # setUp pins the hardware and the state file
        # Mock active terminal download in model_setup state
        state_vals = {
            "dl_active": "1",
            "dl_state": "downloading",
            "dl_title": "Qwen2.5-Coder",
            "dl_repo": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
            "dl_file": "qwen2.5-coder-7b-instruct-q8_0.gguf",
            "dl_done": "500000000",
            "dl_total": "1000000000",
        }
        with mock.patch.object(model_setup, "state_get", side_effect=lambda k: state_vals.get(k, "")), \
             mock.patch.object(model_setup, "state_int", side_effect=lambda k: int(state_vals.get(k, 0))):
            snap = app.snapshot()
            self.assertEqual(snap["state"], "downloading")
            self.assertEqual(snap["source"], "terminal")
            self.assertEqual(snap["done"], 500000000)
            self.assertEqual(snap["total"], 1000000000)
            self.assertEqual(snap["file"], "qwen2.5-coder-7b-instruct-q8_0.gguf")


class TestSyncOffline(unittest.TestCase):
    """A sync that reaches nothing must say so; the page used to show "No matching models" instead."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.hw = hardware.Hw(ram_mb=16384, cores=8, gpu_kind="none", gpu_name="", vram_mb=0, gpu_usable=False)

    def test_no_listing_means_offline_and_nothing_is_recorded(self):
        with mock.patch.object(hf_radar, "fetch_hf_repos", return_value=[]):
            out = hf_radar.sync_radar(self.hw, hdir=self.tmp)
        self.assertTrue(out["offline"])
        self.assertEqual(out["models"], [])
        self.assertFalse((self.tmp / "latest.json").exists())

    def test_a_listing_that_came_back_is_not_offline(self):
        with mock.patch.object(hf_radar, "fetch_hf_repos", return_value=[{"id": "a/b-GGUF", "siblings": []}]):
            out = hf_radar.sync_radar(self.hw, hdir=self.tmp)
        self.assertFalse(out["offline"])


class TestRadarDownloadCli(unittest.TestCase):
    @mock.patch("hf_radar.load_latest")
    @mock.patch("model_setup.download", return_value=None)
    @mock.patch("model_setup.local_path", return_value=(Path("m.gguf"), False))
    @mock.patch("model_setup.state_update")
    def test_a_failed_download_names_the_command_that_really_resumes(self, _state, _path, _dl, load):
        load.return_value = {"models": [{"repo": "t/m", "file": "m.gguf", "size_bytes": 5}]}
        out = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch.object(hf_radar.sys, "platform", "win32"):
            self.assertEqual(hf_radar.download_model_cli("t/m"), 1)
        text = out.getvalue()
        self.assertIn('scripts\\win\\radar.bat --download "t/m"', text)
        self.assertNotIn("python3", text)
        self.assertNotIn("-C -", text, "curl cannot continue the app's .part file")

    def test_normalize_model_entry(self):
        m = {"repo": "author/model-name", "size_bytes": 1024}
        hf_radar._normalize_model_entry(m)
        self.assertEqual(m["file"], "model-name.gguf")
        self.assertEqual(m["files"], [("model-name.gguf", 1024)])
        self.assertEqual(m["download_url"], "https://huggingface.co/author/model-name/resolve/main/model-name.gguf")
        self.assertIn("clusters", m)

    @mock.patch("hf_radar.load_latest")
    @mock.patch("model_setup.download")
    @mock.patch("model_setup.local_path")
    @mock.patch("model_setup.record_installed")
    @mock.patch("model_setup.check_model_speed")
    @mock.patch("model_setup.state_update")
    def test_download_model_cli(self, mock_state, mock_speed, mock_record, mock_path, mock_dl, mock_load):
        mock_load.return_value = {
            "updated_at": "2026-11-01T00:00:00Z",
            "models": [{
                "repo": "test/model",
                "name": "test-model-q4",
                "file": "test-model-q4.gguf",
                "files": [("test-model-q4.gguf", 5000)],
                "size_bytes": 5000,
                "quant": "Q4_K_M",
                "fit_mode": "gpu",
                "tps": 30,
            }],
        }
        mock_path.return_value = (Path("/tmp/models/test-model-q4.gguf"), False)
        mock_dl.return_value = Path("/tmp/models/test-model-q4.gguf")
        mock_speed.return_value = 0

        rc = hf_radar.download_model_cli("test/model")
        self.assertEqual(rc, 0)
        mock_dl.assert_called_once()
        mock_record.assert_called_once()

    @mock.patch("hf_radar.download_model_cli")
    def test_main_download_flag(self, mock_cli_dl):
        mock_cli_dl.return_value = 0
        ret = hf_radar.main(["--download", "test/repo", "--file", "test.gguf"])
        self.assertEqual(ret, 0)
        mock_cli_dl.assert_called_once_with("test/repo", custom_file="test.gguf")


if __name__ == "__main__":
    unittest.main()
