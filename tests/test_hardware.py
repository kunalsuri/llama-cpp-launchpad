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


FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestDetection(unittest.TestCase):
    """detect_hw() and its helpers on every platform, with the operating system faked."""

    def system(self, name, machine="x86_64"):
        for attr, value in (("system", name), ("machine", machine)):
            p = mock.patch.object(hwmod.platform, attr, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def env(self, **values):
        base = {"LP_RAM_MB": "", "LP_VRAM_MB": "", "LP_GPU_USABLE": "", "LLAMA_SERVER": "", "MEMINFO_FILE": ""}
        p = mock.patch.dict(os.environ, {**base, **values})
        p.start()
        self.addCleanup(p.stop)
        if "LP_GPU_USABLE" not in values:
            os.environ.pop("LP_GPU_USABLE", None)

    def commands(self, outputs):
        """Fake run_cmd: look the program up by its first argument."""
        p = mock.patch.object(hwmod, "run_cmd", side_effect=lambda args, timeout=20:
                              outputs.get(tuple(args), outputs.get(args[0], "")))     # exact command first, then program
        p.start()
        self.addCleanup(p.stop)

    def test_linux_ram_from_meminfo(self):
        self.system("Linux")
        self.env(MEMINFO_FILE=str(FIXTURES / "meminfo_16g"))
        self.assertEqual(hwmod.read_ram_mb(), 15625)        # 16000000 kB / 1024

    def test_linux_unreadable_meminfo_is_zero(self):
        self.system("Linux")
        self.env(MEMINFO_FILE=str(FIXTURES / "does-not-exist"))
        self.assertEqual(hwmod.read_ram_mb(), 0)

    def test_macos_ram_from_sysctl(self):
        self.system("Darwin", "arm64")
        self.commands({"sysctl": "17179869184\n"})
        self.assertEqual(hwmod.read_ram_mb(), 16384)

    def test_macos_garbage_from_sysctl_is_zero(self):
        self.system("Darwin")
        self.commands({"sysctl": "not a number"})
        self.assertEqual(hwmod.read_ram_mb(), 0)

    def test_cpu_name_linux_and_macos_and_fallback(self):
        self.system("Linux")
        with mock.patch.object(Path, "read_text", return_value="processor\t: 0\nmodel name\t:  AMD  Ryzen 7 5800X\n"):
            self.assertEqual(hwmod.read_cpu_name(), "AMD Ryzen 7 5800X")
        self.system("Darwin")
        self.commands({"sysctl": "Apple M2\n"})
        self.assertEqual(hwmod.read_cpu_name(), "Apple M2")
        self.system("Plan9")
        with mock.patch.object(hwmod.platform, "processor", return_value="mystery cpu"):
            self.assertEqual(hwmod.read_cpu_name(), "mystery cpu")

    def test_apple_silicon_uses_unified_memory(self):
        self.system("Darwin", "arm64")
        self.env()
        self.commands({"sysctl": "17179869184"})
        hw = hwmod.detect_hw()
        self.assertEqual((hw.gpu_kind, hw.gpu_usable, hw.ram_mb), ("apple", True, 16384))

    def test_nvidia_gpu_usable_when_build_supports_it(self):
        self.system("Linux")
        self.env(MEMINFO_FILE=str(FIXTURES / "meminfo_16g"), LP_GPU_USABLE="1")
        self.commands({"nvidia-smi": "NVIDIA GeForce RTX 3060, 12288\n"})
        hw = hwmod.detect_hw()
        self.assertEqual((hw.gpu_kind, hw.gpu_name, hw.vram_mb, hw.gpu_usable), ("nvidia", "NVIDIA GeForce RTX 3060", 12288, True))

    def test_nvidia_gpu_present_but_build_cannot_use_it(self):
        self.system("Linux")
        self.env(MEMINFO_FILE=str(FIXTURES / "meminfo_16g"), LP_GPU_USABLE="0")
        self.commands({"nvidia-smi": "RTX 3060, 12288\n"})
        hw = hwmod.detect_hw()
        self.assertEqual((hw.gpu_kind, hw.gpu_usable), ("nvidia", False))

    def test_gpu_usable_is_asked_of_llama_server_when_not_forced(self):
        self.system("Linux")
        self.env(MEMINFO_FILE=str(FIXTURES / "meminfo_16g"))
        self.commands({"nvidia-smi": "RTX 3060, 12288\n", "/x/llama-server": "Device 0: CUDA0 (RTX 3060)"})
        with mock.patch.object(hwmod, "find_llama_server", return_value="/x/llama-server"):
            self.assertTrue(hwmod.detect_hw().gpu_usable)
        self.commands({"nvidia-smi": "RTX 3060, 12288\n", "/x/llama-server": "Device 0: CPU"})
        with mock.patch.object(hwmod, "find_llama_server", return_value="/x/llama-server"):
            self.assertFalse(hwmod.detect_hw().gpu_usable)
        with mock.patch.object(hwmod, "find_llama_server", return_value=""):
            self.assertFalse(hwmod.gpu_usable())

    NVIDIA_SMI_HEADER = ("+-----------------------------------------------------------------------------------------+\n"
                         "| NVIDIA-SMI 550.54.15              Driver Version: 550.54.15      CUDA Version: 12.4     |\n"
                         "|-----------------------------------------+------------------------+----------------------+\n")

    def test_the_drivers_cuda_version_is_read_from_nvidia_smi(self):
        """The installer must not pick a CUDA build newer than the driver supports. Plain `nvidia-smi` prints it."""
        self.system("Linux")
        self.env(MEMINFO_FILE=str(FIXTURES / "meminfo_16g"), LP_GPU_USABLE="0")
        self.commands({("nvidia-smi",): self.NVIDIA_SMI_HEADER, "nvidia-smi": "NVIDIA GeForce RTX 3060, 12288\n"})
        self.assertEqual(hwmod.detect_hw().cuda_version, "12.4")
        self.commands({"nvidia-smi": "NVIDIA GeForce RTX 3060, 12288\n"})       # header without a CUDA version
        self.assertEqual(hwmod.detect_hw().cuda_version, "")

    def test_cuda_version_does_not_change_the_saved_hardware_signature(self):
        """Existing users keep their .launchpad-state: the signature (and so the saved profile) is unchanged."""
        a = hwmod.Hw(ram_mb=16000, cores=8, gpu_kind="nvidia", gpu_name="G", vram_mb=8192, gpu_usable=True)
        b = hwmod.Hw(ram_mb=16000, cores=8, gpu_kind="nvidia", gpu_name="G", vram_mb=8192, gpu_usable=True)
        b.cuda_version = "12.4"
        self.assertEqual(a.sig(), b.sig())
        self.assertEqual(a.sig(), "16000-8192-nvidia-1-8")

    def drm(self, cards):
        """A fake /sys/class/drm: {"card0": "0x1002", ...} -> card*/device/vendor files."""
        import tempfile
        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, root, True)
        for card, vendor in cards.items():
            (root / card / "device").mkdir(parents=True)
            (root / card / "device" / "vendor").write_text(vendor + "\n")
        p = mock.patch.object(hwmod, "DRM_DIR", root)
        p.start()
        self.addCleanup(p.stop)
        return root

    def test_an_amd_gpu_on_linux_is_found_without_changing_the_saved_profile(self):
        """AMD (and Intel Arc) cards run llama.cpp's Vulkan build. Finding one must not change recommendations or the
        saved state for existing users: gpu_kind and the signature stay as they were; only other_gpu is set."""
        self.system("Linux")
        self.env(MEMINFO_FILE=str(FIXTURES / "meminfo_16g"))
        self.commands({})
        self.drm({"card0": "0x1002", "renderD128": "0x1002"})
        with mock.patch.object(hwmod, "gpu_usable", return_value=False):
            hw = hwmod.detect_hw()
        self.assertEqual((hw.gpu_kind, hw.other_gpu, hw.other_gpu_usable), ("none", "AMD graphics", False))
        self.assertEqual(hw.sig(), hwmod.Hw(ram_mb=hw.ram_mb, cores=hw.cores).sig())
        self.assertTrue(any("card0" in line and "AMD" in line for line in hw.gpu_looked), hw.gpu_looked)

    def test_integrated_intel_graphics_on_linux_keep_the_cpu_build_and_say_why(self):
        self.system("Linux")
        self.env(MEMINFO_FILE=str(FIXTURES / "meminfo_16g"))
        self.commands({})
        self.drm({"card0": "0x8086"})
        hw = hwmod.detect_hw()
        self.assertEqual(hw.other_gpu, "")
        self.assertTrue(any("Intel" in line and "processor" in line for line in hw.gpu_looked), hw.gpu_looked)

    def test_no_display_devices_is_logged_as_a_miss(self):
        """Rule 5: a search that finds nothing says where it looked."""
        self.system("Linux")
        self.env(MEMINFO_FILE=str(FIXTURES / "meminfo_16g"))
        self.commands({})
        root = self.drm({})
        hw = hwmod.detect_hw()
        self.assertEqual(hw.other_gpu, "")
        self.assertTrue(any(str(root) in line for line in hw.gpu_looked), hw.gpu_looked)

    def test_windows_display_adapter_names_pick_amd_or_intel_arc_only(self):
        pick = hwmod.pick_other_gpu
        self.assertEqual(pick(["Intel(R) UHD Graphics 770", "AMD Radeon RX 7900 XTX"])[0], "AMD Radeon RX 7900 XTX")
        self.assertEqual(pick(["Intel(R) Arc(TM) A770 Graphics"])[0], "Intel(R) Arc(TM) A770 Graphics")
        name, why = pick(["Intel(R) UHD Graphics 770"])
        self.assertEqual(name, "")
        self.assertIn("processor", why)
        self.assertEqual(pick(["Microsoft Basic Display Adapter"])[0], "")
        self.assertEqual(pick([])[0], "")

    def test_windows_adapters_are_read_from_the_registry(self):
        self.system("Windows")
        self.env()
        self.commands({})
        with mock.patch.object(hwmod, "windows_display_adapters", return_value=["AMD Radeon RX 6800"]), \
                mock.patch.object(hwmod, "read_ram_mb", return_value=16384), \
                mock.patch.object(hwmod, "gpu_usable", return_value=True):
            hw = hwmod.detect_hw()
        self.assertEqual((hw.gpu_kind, hw.other_gpu, hw.other_gpu_usable), ("none", "AMD Radeon RX 6800", True))

    def test_reading_windows_adapters_never_raises(self):
        """Runs for real on every OS: a list of names on Windows, [] elsewhere (no winreg)."""
        names = hwmod.windows_display_adapters()
        self.assertIsInstance(names, list)
        self.assertTrue(all(isinstance(n, str) for n in names))
        if sys.platform != "win32":                         # the real OS, not a --as persona
            self.assertEqual(names, [])

    def test_an_nvidia_gpu_skips_the_other_gpu_search(self):
        self.system("Linux")
        self.env(MEMINFO_FILE=str(FIXTURES / "meminfo_16g"), LP_GPU_USABLE="1")
        self.commands({"nvidia-smi": "RTX 3060, 12288\n"})
        self.drm({"card0": "0x1002"})
        self.assertEqual(hwmod.detect_hw().other_gpu, "")

    def test_garbage_from_nvidia_smi_means_no_gpu(self):
        self.system("Linux")
        self.env(MEMINFO_FILE=str(FIXTURES / "meminfo_16g"))
        for out in ("", "No devices were found", "name only"):
            self.commands({"nvidia-smi": out})
            self.assertEqual(hwmod.detect_hw().gpu_kind, "none", out)

    def test_overrides(self):
        self.system("Linux")
        self.env(MEMINFO_FILE=str(FIXTURES / "meminfo_16g"), LP_RAM_MB="4096", LP_VRAM_MB="6144")
        self.commands({})
        hw = hwmod.detect_hw()
        self.assertEqual((hw.ram_mb, hw.vram_mb, hw.gpu_kind, hw.gpu_usable), (4096, 6144, "gpu", True))

    def test_find_llama_server_honours_env_and_ignores_missing_files(self):
        exe = Path(tempfile.mkdtemp()) / "llama-server"
        self.addCleanup(shutil.rmtree, exe.parent, True)
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
        with mock.patch.dict(os.environ, {"LLAMA_SERVER": str(exe)}):
            self.assertEqual(hwmod.find_llama_server(), str(exe))
        with mock.patch.dict(os.environ, {"LLAMA_SERVER": str(exe.parent / "nope")}),                 mock.patch.object(hwmod.shutil, "which", return_value=None),                 mock.patch.object(hwmod, "ROOT", exe.parent / "no-project"),                 mock.patch.object(hwmod.Path, "home", return_value=exe.parent / "no-home"):
            self.assertEqual(hwmod.find_llama_server(), "")

    def test_run_cmd_never_raises(self):
        self.assertEqual(hwmod.run_cmd(["definitely-not-a-program-xyz"]), "")

    def test_print_mode_prints_and_writes_nothing(self):
        self.system("Linux")
        self.env(LP_RAM_MB="2048")
        self.commands({})
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out, True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(hwmod.main(["--print", "--out", str(out / "r.env")]), 0)
        self.assertIn('HW_RAM_MB="2048"', buf.getvalue())
        self.assertEqual(list(out.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
