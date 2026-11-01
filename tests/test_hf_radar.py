"""Tests for utils/hf_radar.py (offline, mocked)."""
from __future__ import annotations

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

        # History log check
        entries = hf_radar.load_history_entries(self.tmp, days=30)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["repo"], "test/model-1")

    def test_render_dashboard(self):
        data = {
            "updated_at": "2026-11-01T00:00:00Z",
            "models": [
                {
                    "repo": "prism-ml/Ternary-Bonsai-2-27B-gguf",
                    "quant": "Q4_K_M",
                    "size_mb": 5632.0,
                    "fit_mode": "gpu",
                    "tps": 17,
                    "downloads": 1900000,
                }
            ],
        }
        text = hf_radar.render_dashboard(data, gpu_only=False, limit=10)
        self.assertIn("HUGGING FACE LOCAL MODEL RADAR", text)
        self.assertIn("prism-ml/Ternary-Bonsai", text)
        self.assertIn("GPU", text)
        self.assertIn("~17 t/s", text)


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
            "tags": ["gguf"],
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
        ret = hf_radar.main(["--cli", "--dashboard"])
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


if __name__ == "__main__":
    unittest.main()
