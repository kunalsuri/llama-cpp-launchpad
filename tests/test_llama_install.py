"""Tests for utils/llama_install.py: install llama.cpp from the setup page, into the project's bin/ only.

Asset matching runs against tests/fixtures/llama_release_reconstructed.json. That file is NOT a saved API response:
its asset names follow llama.cpp's own release workflow (release-publish.yml), and its sizes and digests are made up
(see its "_provenance"). Downloads are faked (no network); archives are real zip / tar.gz files built here, so
extraction, checksum and size checks run for real. The machine (OS, chip, GPU, PATH) is always pinned (rule 2).
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import unittest
import unittest.mock
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "utils"))
import llama_install as li  # noqa: E402

RELEASE = json.loads((HERE / "fixtures" / "llama_release_reconstructed.json").read_text(encoding="utf-8"))
FAKE = str(HERE / "fake_llama_server.py")


def names(p):
    return [a["name"] for a in p["assets"]]


class TestPlan(unittest.TestCase):
    """Which release archive fits this machine: CUDA for NVIDIA, Vulkan for other GPUs, else CPU."""

    CASES = [
        ("Windows", "AMD64", "nvidia", "cuda", ["llama-b7777-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip"]),
        ("Windows", "ARM64", "nvidia", "cuda", ["llama-b7777-bin-win-cuda-13.4-arm64.zip", "cudart-llama-bin-win-cuda-13.4-arm64.zip"]),
        ("Windows", "AMD64", "gpu", "vulkan", ["llama-b7777-bin-win-vulkan-x64.zip"]),
        ("Windows", "AMD64", "none", "cpu", ["llama-b7777-bin-win-cpu-x64.zip"]),
        ("Windows", "ARM64", "none", "cpu", ["llama-b7777-bin-win-cpu-arm64.zip"]),
        ("Linux", "x86_64", "nvidia", "cuda", ["llama-b7777-bin-ubuntu-cuda-12.8-x64.tar.gz",
                                               "cudart-llama-b7777-bin-ubuntu-cuda-12.8-x64.tar.gz"]),
        ("Linux", "aarch64", "nvidia", "cuda", ["llama-b7777-bin-ubuntu-cuda-13.4-arm64.tar.gz",
                                                "cudart-llama-b7777-bin-ubuntu-cuda-13.4-arm64.tar.gz"]),
        ("Linux", "x86_64", "gpu", "vulkan", ["llama-b7777-bin-ubuntu-vulkan-x64.tar.gz"]),
        ("Linux", "x86_64", "none", "cpu", ["llama-b7777-bin-ubuntu-x64.tar.gz"]),
        ("Linux", "aarch64", "none", "cpu", ["llama-b7777-bin-ubuntu-arm64.tar.gz"]),
    ]

    def test_each_machine_gets_its_build(self):
        for system, machine, gpu, kind, expect in self.CASES:
            with self.subTest(system=system, machine=machine, gpu=gpu):
                p = li.plan(RELEASE, system, machine, gpu)
                self.assertEqual((p.get("kind"), names(p)), (kind, expect), p)
                self.assertEqual(p["tag"], "b7777")

    def test_oldest_cuda_major_is_preferred_because_it_needs_the_oldest_driver(self):
        p = li.plan(RELEASE, "Windows", "AMD64", "nvidia")
        self.assertIn("cuda-12.4", names(p)[0])

    def test_cpu_can_be_asked_for(self):
        self.assertEqual(names(li.plan(RELEASE, "Linux", "x86_64", "nvidia", "cpu")), ["llama-b7777-bin-ubuntu-x64.tar.gz"])

    def test_never_picks_builds_for_other_hardware(self):
        avoid = ("android", "snapdragon", "rocm", "sycl", "openvino", "s390x", "xcframework", "opencl", "-ui.", "macos")
        for system, machine, gpu, _, _ in self.CASES:
            for a in li.plan(RELEASE, system, machine, gpu)["assets"]:
                self.assertFalse(any(x in a["name"] for x in avoid), a["name"])

    def test_cuda_without_its_runtime_archive_falls_back_to_vulkan(self):
        rel = dict(RELEASE, assets=[a for a in RELEASE["assets"] if not a["name"].startswith("cudart-")])
        p = li.plan(rel, "Windows", "AMD64", "nvidia")
        self.assertEqual(p["kind"], "vulkan")
        self.assertIn("CUDA", p["why"])

    def test_mac_and_unknown_chips_get_no_download(self):
        self.assertIn("error", li.plan(RELEASE, "Darwin", "arm64", "apple"))
        p = li.plan(RELEASE, "Linux", "riscv64", "none")
        self.assertIn("riscv64", p["error"])

    def test_a_release_without_a_matching_build_says_so(self):
        p = li.plan({"tag_name": "b1", "assets": []}, "Linux", "x86_64", "none")
        self.assertIn("error", p)

    def test_only_official_https_download_links_are_accepted(self):
        good = "https://github.com/ggml-org/llama.cpp/releases/download/b7777/llama-b7777-bin-ubuntu-x64.tar.gz"
        self.assertTrue(li.download_url_ok(good))
        for bad in (good.replace("https", "http"), good.replace("ggml-org", "evil"), "https://evil.example/x.zip",
                    "https://github.com.evil.example/ggml-org/llama.cpp/releases/download/b1/x.zip",
                    "https://github.com/ggml-org/llama.cpp/archive/x.zip"):
            self.assertFalse(li.download_url_ok(bad), bad)
        rel = {"tag_name": "b1", "assets": [dict(RELEASE["assets"][3], browser_download_url="https://evil.example/x.tar.gz")]}
        self.assertIn("error", li.plan(rel, "Linux", "x86_64", "none"), "a listing pointing elsewhere is not used")

    def test_redirects_may_only_go_to_github_over_https(self):
        self.assertTrue(li.redirect_ok("https://release-assets.githubusercontent.com/github-production-release-asset/1"))
        self.assertTrue(li.redirect_ok("https://objects.githubusercontent.com/x"))
        for bad in ("http://objects.githubusercontent.com/x", "https://evil.example/x", "https://githubusercontent.com.evil.example/x"):
            self.assertFalse(li.redirect_ok(bad), bad)


def tar_bytes(top, files, links=()):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(f"{top}/{name}" if top else name)
            info.size, info.mode = len(data), 0o755
            tf.addfile(info, io.BytesIO(data))
        for name, target in links:
            info = tarfile.TarInfo(f"{top}/{name}" if top else name)
            info.type, info.linkname = tarfile.SYMTYPE, target
            tf.addfile(info)
    return buf.getvalue()


def zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def fake_version(argv, timeout=60):
    """Stands in for running `llama-server --version`: a file starting FAKE-OK works, anything else does not."""
    try:
        data = Path(argv[0]).read_bytes()
    except OSError as e:
        return False, str(e)
    if data.startswith(b"FAKE-OK"):
        return True, "version: 4242 (abc1234)\nbuilt with fake-cc"
    return False, "error while loading shared libraries: libvulkan.so.1: cannot open shared object file"


class InstallBase(unittest.TestCase):
    system, machine, gpu = "Linux", "x86_64", "none"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project = self.tmp / "proj"
        (self.project / "models").mkdir(parents=True)
        (self.project / "models" / "keep.gguf").write_bytes(b"model")
        self.bin = self.project / "bin"
        self.archives = {}               # url -> bytes served by the fake download
        self.release = json.loads(json.dumps(RELEASE))
        self.found = ""                  # what find_llama_server() returns after the install
        self.paths = {}                  # PATH: name -> path
        self.ran = []
        self.inst = self.make()

    def make(self, **kw):
        args = dict(bin_dir=self.bin, system=self.system, machine=self.machine, gpu_kind=lambda: self.gpu,
                    find=self.find, which=lambda n: self.paths.get(n, ""), fetch_json=self.fetch_json,
                    fetch_file=self.fetch_file, version=fake_version, run=self.run_brew)
        args.update(kw)
        return li.Installer(**args)

    def find(self):
        """As hardware.find_llama_server: a copy found earlier in the lookup order (LLAMA_SERVER, PATH) wins over bin/."""
        if self.found:
            return self.found
        exe = self.bin / ("llama-server.exe" if self.system == "Windows" else "llama-server")
        return str(exe) if exe.is_file() else ""

    def fetch_json(self, url):
        self.assertEqual(url, li.LATEST_RELEASE)
        return self.release

    def fetch_file(self, url, dest, on_progress=None):
        data = self.archives[url]
        for i in range(0, len(data), 1000):
            if on_progress:
                on_progress(i)
        Path(dest).write_bytes(data)

    def run_brew(self, argv, on_line):
        self.ran.append(list(argv))
        for line in ("==> Downloading llama.cpp", "==> Pouring llama.cpp"):
            on_line(line)
        return 0

    def serve(self, name, data, digest="auto"):
        """Put archive bytes behind the fixture asset `name` (and give it a matching size and digest)."""
        for a in self.release["assets"]:
            if a["name"] == name:
                a["size"] = len(data)
                a["digest"] = ("sha256:" + hashlib.sha256(data).hexdigest()) if digest == "auto" else digest
                self.archives[a["browser_download_url"]] = data
                return a
        raise KeyError(name)

    def wait(self, *states):
        for _ in range(400):
            s = self.inst.status()
            if s["state"] in states:
                return s
            time.sleep(0.02)
        self.fail(f"install never reached {states}: {self.inst.status()}")

    def snapshot(self):
        return {str(p.relative_to(self.project)) for p in self.project.rglob("*")}


class TestInstall(InstallBase):
    def test_linux_cpu_build_is_unpacked_into_bin_and_verified(self):
        self.serve("llama-b7777-bin-ubuntu-x64.tar.gz",
                   tar_bytes("llama-b7777", {"llama-server": b"FAKE-OK", "libllama.so.0.0.1": b"lib", "LICENSE": b"MIT"},
                             links=[("libllama.so.0", "libllama.so.0.0.1")]))
        self.found = str(self.bin / "llama-server")
        self.assertEqual(self.inst.start()[0], 202)
        s = self.wait("done", "failed")
        self.assertEqual(s["state"], "done", s)
        self.assertTrue((self.bin / "llama-server").is_file())
        self.assertTrue((self.bin / "libllama.so.0.0.1").is_file())
        if os.name != "nt":
            self.assertTrue(os.access(self.bin / "llama-server", os.X_OK))
            self.assertEqual(os.readlink(self.bin / "libllama.so.0"), "libllama.so.0.0.1")
        self.assertIn("4242", s["version"])
        self.assertEqual(s["checksum"], "verified")
        self.assertEqual(s["kind"], "cpu")
        self.assertFalse(s.get("shadowed"))
        self.assertFalse((self.bin / li.STAGING).exists(), "the staging folder is removed")

    def test_windows_cuda_build_brings_its_runtime_dlls(self):
        self.system, self.machine, self.gpu = "Windows", "AMD64", "nvidia"
        self.inst = self.make()
        self.serve("llama-b7777-bin-win-cuda-12.4-x64.zip", zip_bytes({"llama-server.exe": b"FAKE-OK", "ggml-cuda.dll": b"d"}))
        self.serve("cudart-llama-bin-win-cuda-12.4-x64.zip", zip_bytes({"cudart64_12.dll": b"d", "cublas64_12.dll": b"d"}))
        self.found = str(self.bin / "llama-server.exe")
        self.inst.start()
        s = self.wait("done", "failed")
        self.assertEqual(s["state"], "done", s)
        self.assertEqual(sorted(p.name for p in self.bin.iterdir()),
                         ["cublas64_12.dll", "cudart64_12.dll", "ggml-cuda.dll", "llama-server.exe"])
        self.assertEqual(s["kind"], "cuda")

    def test_it_writes_only_inside_bin(self):
        self.serve("llama-b7777-bin-ubuntu-x64.tar.gz", tar_bytes("llama-b7777", {"llama-server": b"FAKE-OK"}))
        before = self.snapshot()
        self.inst.start()
        self.wait("done", "failed")
        added = self.snapshot() - before
        self.assertTrue(added)
        self.assertTrue(all(p == "bin" or p.startswith("bin" + os.sep) for p in added), added)
        self.assertEqual((self.project / "models" / "keep.gguf").read_bytes(), b"model")

    def test_a_checksum_mismatch_installs_nothing(self):
        self.serve("llama-b7777-bin-ubuntu-x64.tar.gz", tar_bytes("llama-b7777", {"llama-server": b"FAKE-OK"}),
                   digest="sha256:" + "0" * 64)
        self.inst.start()
        s = self.wait("done", "failed")
        self.assertEqual(s["state"], "failed")
        self.assertIn("checksum", s["error"])
        self.assertFalse((self.bin / "llama-server").exists())
        self.assertFalse((self.bin / li.STAGING).exists())

    def test_the_staging_folder_is_gone_before_the_result_is_reported(self):
        """Regression (seen once in 3 runs): "failed" was reported before the staging folder was removed, so a page
        polling at that moment saw the result while bin/.launchpad-install still existed. Cleanup comes first."""
        real = li.shutil.rmtree

        def slow(path, *a, **kw):
            time.sleep(0.3)
            return real(path, *a, **kw)
        for digest in ("sha256:" + "0" * 64, "auto"):                  # a failed install, then a good one
            with self.subTest(digest=digest[:10]), unittest.mock.patch.object(li.shutil, "rmtree", slow):
                self.archives.clear()
                self.release = json.loads(json.dumps(RELEASE))
                self.serve("llama-b7777-bin-ubuntu-x64.tar.gz", tar_bytes("llama-b7777", {"llama-server": b"FAKE-OK"}), digest=digest)
                self.inst = self.make()
                self.inst.start()
                self.wait("done", "failed")
                self.assertFalse((self.bin / li.STAGING).exists(), "reported before cleaning up")

    def test_without_a_published_checksum_it_says_the_size_was_checked_only(self):
        self.serve("llama-b7777-bin-ubuntu-x64.tar.gz", tar_bytes("llama-b7777", {"llama-server": b"FAKE-OK"}), digest=None)
        self.inst.start()
        s = self.wait("done", "failed")
        self.assertEqual((s["state"], s["checksum"]), ("done", "none-published"))

    def test_a_size_mismatch_installs_nothing(self):
        a = self.serve("llama-b7777-bin-ubuntu-x64.tar.gz", tar_bytes("llama-b7777", {"llama-server": b"FAKE-OK"}), digest=None)
        a["size"] += 1
        self.inst.start()
        s = self.wait("done", "failed")
        self.assertEqual(s["state"], "failed")
        self.assertIn("size", s["error"])
        self.assertFalse((self.bin / "llama-server").exists())

    def test_archives_that_reach_outside_bin_are_refused(self):
        for evil in ({"../escape": b"x"}, {"/etc/evil": b"x"}, {"ok/../../escape": b"x"}):
            with self.subTest(evil=list(evil)):
                self.archives.clear()
                self.release = json.loads(json.dumps(RELEASE))
                self.serve("llama-b7777-bin-ubuntu-x64.tar.gz", tar_bytes("", {"llama-server": b"FAKE-OK", **evil}))
                self.inst = self.make()
                self.inst.start()
                s = self.wait("done", "failed")
                self.assertEqual(s["state"], "failed")
                self.assertIn("unsafe", s["error"])
                self.assertFalse((self.tmp / "escape").exists())
                self.assertFalse((self.bin / "llama-server").exists())
        links = tar_bytes("", {"llama-server": b"FAKE-OK"}, links=[("libx.so", "/etc/passwd")])
        self.archives.clear()
        self.release = json.loads(json.dumps(RELEASE))
        self.serve("llama-b7777-bin-ubuntu-x64.tar.gz", links)
        self.inst = self.make()
        self.inst.start()
        self.assertIn("unsafe", self.wait("done", "failed")["error"])

    def test_a_build_that_does_not_run_is_not_installed_and_the_cpu_build_is_offered(self):
        self.gpu = "gpu"
        self.serve("llama-b7777-bin-ubuntu-vulkan-x64.tar.gz", tar_bytes("llama-b7777", {"llama-server": b"BROKEN"}))
        self.inst.start()
        s = self.wait("done", "failed")
        self.assertEqual(s["state"], "failed")
        self.assertIn("libvulkan.so.1", "\n".join(s["log"]))
        self.assertTrue(s["cpu_fallback"])
        self.assertFalse((self.bin / "llama-server").exists(), "a build that does not start is not left in bin/")
        self.serve("llama-b7777-bin-ubuntu-x64.tar.gz", tar_bytes("llama-b7777", {"llama-server": b"FAKE-OK"}))
        self.assertEqual(self.inst.start("cpu")[0], 202)
        s = self.wait("done", "failed")
        self.assertEqual((s["state"], s["kind"]), ("done", "cpu"))

    def test_an_archive_with_a_single_file_is_unpacked_not_dropped(self):
        """A one-file archive (a runtime zip with one DLL) is not a wrapping folder: its file must arrive."""
        self.system, self.machine, self.gpu = "Windows", "AMD64", "nvidia"
        self.inst = self.make()
        self.serve("llama-b7777-bin-win-cuda-12.4-x64.zip", zip_bytes({"llama-server.exe": b"FAKE-OK", "ggml-cuda.dll": b"d"}))
        self.serve("cudart-llama-bin-win-cuda-12.4-x64.zip", zip_bytes({"cudart64_12.dll": b"d"}))
        self.inst.start()
        self.assertEqual(self.wait("done", "failed")["state"], "done")
        self.assertTrue((self.bin / "cudart64_12.dll").is_file())

    def test_a_file_that_cannot_be_replaced_is_reported_honestly(self):
        """Windows: a llama-server.exe started by serve.bat is locked. Say which file, and that bin/ is now mixed."""
        self.serve("llama-b7777-bin-ubuntu-x64.tar.gz", tar_bytes("llama-b7777", {"a.so": b"lib", "llama-server": b"FAKE-OK"}))
        real = os.replace

        def locked(src, dst):
            if Path(dst).name == "llama-server":
                raise PermissionError(13, "The process cannot access the file because it is being used by another process")
            return real(src, dst)
        with unittest.mock.patch.object(li.os, "replace", locked):
            self.inst.start()
            s = self.wait("done", "failed")
        self.assertEqual(s["state"], "failed")
        self.assertIn("llama-server", s["error"])
        self.assertIn("still running", s["error"])
        self.assertNotIn("Nothing was installed", s["error"])
        self.assertIn("1 of 2 files", s["error"])

    def test_a_copy_on_path_that_shadows_bin_is_named(self):
        self.serve("llama-b7777-bin-ubuntu-x64.tar.gz", tar_bytes("llama-b7777", {"llama-server": b"FAKE-OK"}))
        other = self.tmp / "usr" / "bin" / "llama-server"     # a working copy on PATH: the serve scripts pick it first
        other.parent.mkdir(parents=True)
        other.write_bytes(b"FAKE-OK")
        self.found = str(other)
        self.inst.start()
        s = self.wait("done", "failed")
        self.assertEqual(s["state"], "done", s)
        self.assertIn(str(other), s["shadowed"])
        self.assertIn(str(self.bin), s["shadowed"])

    def test_no_network_is_a_clean_failure(self):
        def offline(url):
            raise OSError("no route to host")
        self.inst = self.make(fetch_json=offline)
        self.inst.start()
        s = self.wait("done", "failed")
        self.assertIn("could not reach GitHub", s["error"])

    def test_one_install_at_a_time(self):
        gate = __import__("threading").Event()

        def slow(url):
            gate.wait(5)
            return self.release
        self.serve("llama-b7777-bin-ubuntu-x64.tar.gz", tar_bytes("llama-b7777", {"llama-server": b"FAKE-OK"}))
        self.inst = self.make(fetch_json=slow)
        self.assertEqual(self.inst.start()[0], 202)
        self.assertEqual(self.inst.start()[0], 409)
        gate.set()
        self.wait("done", "failed")

    def test_progress_is_reported_while_downloading(self):
        seen = []
        self.serve("llama-b7777-bin-ubuntu-x64.tar.gz", tar_bytes("llama-b7777", {"llama-server": b"FAKE-OK" + os.urandom(20000)}))
        real = self.fetch_file

        def watching(url, dest, on_progress=None):
            real(url, dest, lambda n: (on_progress(n), seen.append(self.inst.status()["done"])))
        self.inst = self.make(fetch_file=watching)
        self.inst.start()
        s = self.wait("done", "failed")
        self.assertGreater(len(set(seen)), 2)
        self.assertEqual(s["total"], self.release["assets"][3]["size"])


class TestMac(InstallBase):
    system, machine, gpu = "Darwin", "arm64", "apple"

    def test_offers_homebrew_only_when_brew_was_found(self):
        self.assertEqual(self.inst.offer()["how"], "manual")
        self.paths["brew"] = "/opt/homebrew/bin/brew"
        offer = self.inst.offer()
        self.assertEqual((offer["how"], offer["cmd"]), ("brew", "brew install llama.cpp"))

    def test_brew_install_runs_brew_and_checks_the_result(self):
        self.paths["brew"] = "/opt/homebrew/bin/brew"
        self.found = "/opt/homebrew/bin/llama-server"
        Path(self.tmp / "llama-server").write_bytes(b"FAKE-OK")
        self.inst = self.make(find=lambda: str(self.tmp / "llama-server"))
        self.assertEqual(self.inst.start()[0], 202)
        s = self.wait("done", "failed")
        self.assertEqual(s["state"], "done", s)
        self.assertEqual(self.ran, [["/opt/homebrew/bin/brew", "install", "llama.cpp"]])
        self.assertIn("Pouring", "\n".join(s["log"]))
        self.assertFalse(self.bin.exists(), "Homebrew installs it; nothing is written into bin/")

    def test_without_brew_nothing_is_run(self):
        self.assertEqual(self.inst.start()[0], 409)
        self.assertEqual(self.ran, [])

    def test_linux_with_brew_still_downloads_the_release(self):
        inst = self.make(system="Linux", machine="x86_64")
        self.paths["brew"] = "/home/linuxbrew/.linuxbrew/bin/brew"
        self.assertEqual(inst.offer()["how"], "download")


class TestVersion(unittest.TestCase):
    """`llama-server --version` decides whether a copy works: run for real against the fake llama-server."""

    def test_a_working_server_reports_its_version(self):
        ok, text = li.server_version([sys.executable, FAKE])
        self.assertTrue(ok)
        self.assertIn("version: 4242", text)

    def test_a_server_that_cannot_start_is_not_working(self):
        with unittest.mock.patch.dict(os.environ, {"FAKE_LLAMA_VERSION_FAIL": "1"}):
            ok, text = li.server_version([sys.executable, FAKE])
        self.assertFalse(ok)
        self.assertIn("libggml", text)
        self.assertEqual(li.server_version([str(Path(tempfile.gettempdir()) / "no-such-llama-server")])[0], False)


class TestWhyInstall(unittest.TestCase):
    def hw(self, kind="none", usable=False):
        return unittest.mock.Mock(gpu_kind=kind, gpu_usable=usable)

    def test_reasons(self):
        self.assertEqual(li.why_install("", False, self.hw()), "missing")
        self.assertEqual(li.why_install("/x/llama-server", False, self.hw()), "broken")
        self.assertEqual(li.why_install("/x/llama-server", True, self.hw("nvidia", False)), "no-gpu")
        self.assertEqual(li.why_install("/x/llama-server", True, self.hw("nvidia", True)), "")
        self.assertEqual(li.why_install("/x/llama-server", True, self.hw("apple", True)), "")
        self.assertEqual(li.why_install("/x/llama-server", True, self.hw()), "")


if __name__ == "__main__":
    unittest.main()
