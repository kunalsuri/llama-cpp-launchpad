"""Tests for utils/hardware.py (the report file that scripts/win/dev-setup.ps1 creates).
Detection itself is covered in test_model_setup.py (TestHardware); here: the report.
No GPU, network or llama.cpp needed.
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))
import hardware as hwmod  # noqa: E402


def parse_env(text):
    out = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            out[key] = value.strip('"')
    return out


class TestReport(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"LP_RAM_MB": "16384", "LLAMA_SERVER": ""})
        env.start()
        self.addCleanup(env.stop)
        for name, rv in (("run_cmd", ""), ("find_llama_server", "")):
            p = mock.patch.object(hwmod, name, return_value=rv)
            p.start()
            self.addCleanup(p.stop)

    def test_report_has_the_expected_keys(self):
        hw = hwmod.Hw(ram_mb=16384, cores=8, gpu_kind="nvidia", gpu_name="RTX 3060", vram_mb=12288, gpu_usable=True)
        values = parse_env(hwmod.render_report(hw))
        self.assertEqual(values["HW_RAM_MB"], "16384")
        self.assertEqual(values["HW_CPU_THREADS"], "8")
        self.assertEqual(values["HW_GPU_NAME"], "RTX 3060")
        self.assertEqual(values["HW_VRAM_MB"], "12288")
        self.assertEqual(values["HW_GPU_USABLE_BY_LLAMACPP"], "true")
        self.assertEqual(values["HW_RECOMMENDED_MODE"], "gpu")
        self.assertEqual(values["HW_SIGNATURE"], hw.sig())

    def test_cpu_only_machine(self):
        values = parse_env(hwmod.render_report(hwmod.Hw(ram_mb=8192, cores=4)))
        self.assertEqual((values["HW_GPU_KIND"], values["HW_RECOMMENDED_MODE"]), ("none", "cpu"))

    def test_report_holds_no_identity(self):
        text = hwmod.render_report(hwmod.Hw(ram_mb=8192, cores=4))
        for secret in (os.environ.get("USERNAME", ""), os.environ.get("USER", ""), os.environ.get("COMPUTERNAME", ""),
                       str(Path.home())):
            if len(secret) > 2:
                self.assertNotIn(secret, text)

    def test_quotes_and_newlines_cannot_break_the_file(self):
        hw = hwmod.Hw(ram_mb=1, cores=1, gpu_kind="gpu", gpu_name='Evil"\nHW_RAM_MB=999')
        values = parse_env(hwmod.render_report(hw))
        self.assertEqual(values["HW_RAM_MB"], "1")

    def test_main_writes_the_file_and_leaves_no_temp_file(self):
        out = self.tmp / ".hardware.env"
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = hwmod.main(["--out", str(out)])
        self.assertEqual(rc, 0)
        self.assertEqual(parse_env(out.read_text(encoding="utf-8"))["HW_RAM_MB"], "16384")
        self.assertEqual([p.name for p in self.tmp.iterdir()], [".hardware.env"])
        self.assertIn("16 GB RAM", buf.getvalue())

    def test_unreadable_ram_is_a_failure_exit_code(self):
        with mock.patch.dict(os.environ, {"LP_RAM_MB": ""}), mock.patch.object(hwmod, "read_ram_mb", return_value=0), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(hwmod.main(["--out", str(self.tmp / "x.env")]), 1)


if __name__ == "__main__":
    unittest.main()
