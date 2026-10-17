"""Tests for utils/detect_tools.py (are Ollama / llama.cpp / LM Studio / Unsloth installed?).

A FakeProbe stands in for the machine: a virtual file system, a virtual PATH and canned program
output, so the Windows, macOS and Linux code paths are all tested on any host. No tool, network
or GPU needed, and nothing real is executed (the real-machine tests only read, or run this script itself).
Run: python3 -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import detect_tools as dt  # noqa: E402
from fakes import FakeProbe  # noqa: E402

SOURCE = Path(dt.__file__).read_text(encoding="utf-8")


def tool(result, tool_id):
    return next(t for t in result["tools"] if t["id"] == tool_id)


class TestNothingInstalled(unittest.TestCase):
    def test_every_platform_reports_not_found(self):
        for system in ("Windows", "Darwin", "Linux"):
            with self.subTest(system):
                result = dt.detect(FakeProbe(system))
                self.assertEqual([t["status"] for t in result["tools"]], ["not-found"] * 4)
                self.assertTrue(all(t["evidence"] == [] and t["version"] == "" for t in result["tools"]))

    def test_searched_log_records_misses(self):
        t = tool(dt.detect(FakeProbe("Linux")), "ollama")
        self.assertIn({"check": "PATH", "target": "ollama", "found": False}, t["searched"])
        self.assertTrue(all(not s["found"] for s in t["searched"]))


class TestOllama(unittest.TestCase):
    def test_on_path_with_version(self):
        out = "Warning: could not connect to a running Ollama instance\nWarning: client version is 0.5.1\n"
        p = FakeProbe("Linux", path={"ollama": "/usr/local/bin/ollama"}, output={"/usr/local/bin/ollama": out},
                      files=["/usr/local/bin/ollama"])
        t = tool(dt.detect(p), "ollama")
        self.assertEqual((t["status"], t["version"]), ("installed", "0.5.1"))
        self.assertEqual(len(t["evidence"]), 1, "PATH hit and known-location hit are the same file")
        self.assertEqual(t["evidence"][0]["kind"], "on-PATH")
        self.assertEqual(p.ran, [["/usr/local/bin/ollama", "--version"]])

    def test_windows_default_location_without_path(self):
        exe = r"C:\Users\me\AppData\Local\Programs\Ollama\ollama.exe"
        p = FakeProbe("Windows", files=[exe], output={exe: "ollama version is 0.6.0"})
        t = tool(dt.detect(p), "ollama")
        self.assertEqual((t["status"], t["version"]), ("installed", "0.6.0"))
        self.assertEqual(t["evidence"][0]["kind"], "known-location")

    def test_windows_honours_localappdata_variable(self):
        exe = r"D:\Apps\Programs\Ollama\ollama.exe"
        p = FakeProbe("Windows", files=[exe], env={"LOCALAPPDATA": r"D:\Apps"})
        self.assertEqual(tool(dt.detect(p), "ollama")["status"], "installed")

    def test_mac_app_bundle_is_installed_and_not_executed(self):
        p = FakeProbe("Darwin", dirs=["/Applications/Ollama.app"], files=[])
        t = tool(dt.detect(p), "ollama")
        self.assertEqual((t["status"], t["evidence"][0]["kind"]), ("installed", "app"))
        self.assertEqual(p.ran, [])

    def test_leftover_data_dir_is_data_only(self):
        p = FakeProbe("Linux", dirs=["/home/me/.ollama"])
        t = tool(dt.detect(p), "ollama")
        self.assertEqual((t["status"], t["evidence"][0]["strength"]), ("data-only", "weak"))
        self.assertEqual(p.ran, [])


class TestLlamaCpp(unittest.TestCase):
    def test_several_binaries_one_tool_one_version_run(self):
        build = "/home/me/llama.cpp/build/bin/"
        p = FakeProbe("Linux", files=[build + "llama-server", build + "llama-cli"],
                      path={"llama-server": build + "llama-server"},
                      output={build + "llama-server": "version: 4567 (abc1234)\nbuilt with gcc\n"})
        t = tool(dt.detect(p), "llama-cpp")
        self.assertEqual((t["status"], t["version"]), ("installed", "4567 (abc1234)"))
        self.assertEqual(sorted(e["path"] for e in t["evidence"]), [build + "llama-cli", build + "llama-server"])
        self.assertEqual(len(p.ran), 1)

    def test_llama_server_env_var(self):
        p = FakeProbe("Linux", files=["/opt/x/llama-server"], env={"LLAMA_SERVER": "/opt/x/llama-server"})
        t = tool(dt.detect(p), "llama-cpp")
        self.assertEqual(t["evidence"][0]["kind"], "env-LLAMA_SERVER")

    def test_env_var_pointing_nowhere_is_ignored(self):
        p = FakeProbe("Linux", env={"LLAMA_SERVER": "/nope/llama-server"})
        self.assertEqual(tool(dt.detect(p), "llama-cpp")["status"], "not-found")

    def test_windows_exe_suffix_and_project_bin(self):
        exe = r"C:\proj\bin\llama-server.exe"
        self.assertEqual(tool(dt.detect(FakeProbe("Windows", files=[exe])), "llama-cpp")["status"], "installed")

    def test_python_bindings_count(self):
        t = tool(dt.detect(FakeProbe("Linux", pkgs={"llama-cpp-python": "0.3.1"})), "llama-cpp")
        self.assertEqual((t["status"], t["version"]), ("installed", "0.3.1"))


class TestLmStudio(unittest.TestCase):
    def test_cli_with_banner_output(self):
        exe = "/home/me/.lmstudio/bin/lms"
        banner = "\x1b[38;5;166m   __   __\x1b[0m\nCLI commit: ff50809\n"
        p = FakeProbe("Linux", files=[exe], path={"lms": exe}, output={exe: banner})
        t = tool(dt.detect(p), "lmstudio")
        self.assertEqual((t["status"], t["version"]), ("installed", "ff50809"))

    def test_mac_app_bundle(self):
        p = FakeProbe("Darwin", dirs=["/Applications/LM Studio.app"], files=["/Applications/LM Studio.app"])
        t = tool(dt.detect(p), "lmstudio")
        self.assertEqual((t["status"], t["evidence"][0]["kind"]), ("installed", "app"))
        self.assertEqual(p.ran, [], "app bundles are never executed")

    def test_linux_appimage_glob(self):
        p = FakeProbe("Linux", files=["/home/me/Applications/LM-Studio-0.3.5.AppImage"])
        self.assertEqual(tool(dt.detect(p), "lmstudio")["status"], "installed")

    def test_windows_app_exe_not_executed(self):
        p = FakeProbe("Windows", files=[r"C:\Users\me\AppData\Local\Programs\LM Studio\LM Studio.exe"])
        self.assertEqual(tool(dt.detect(p), "lmstudio")["status"], "installed")
        self.assertEqual(p.ran, [])


class TestUnsloth(unittest.TestCase):
    def test_package_in_current_python(self):
        p = FakeProbe("Linux", pkgs={"unsloth": "2025.9.1"})
        t = tool(dt.detect(p), "unsloth")
        self.assertEqual((t["status"], t["version"]), ("installed", "2025.9.1"))

    def test_package_in_conda_env_found_by_dist_info(self):
        sp = "/home/me/miniconda3/envs/llm/lib/python3.11/site-packages/"
        p = FakeProbe("Linux", dirs=[sp + "unsloth-2025.8.2.dist-info", sp + "unsloth_zoo-2025.8.1.dist-info"])
        t = tool(dt.detect(p), "unsloth")
        self.assertEqual((t["status"], t["version"]), ("installed", "2025.8.2"))
        self.assertEqual(len(t["evidence"]), 1, "unsloth_zoo must not count as unsloth")

    def test_windows_conda_env(self):
        sp = r"C:\Users\me\miniconda3\envs\llm\Lib\site-packages" + "\\"
        p = FakeProbe("Windows", dirs=[sp + "unsloth-2025.8.2.dist-info"])
        self.assertEqual(tool(dt.detect(p), "unsloth")["status"], "installed")

    def test_never_executes_anything_even_when_cli_is_on_path(self):
        p = FakeProbe("Linux", path={"unsloth": "/home/me/.venv/bin/unsloth"})
        t = tool(dt.detect(p), "unsloth")
        self.assertEqual(t["status"], "installed")
        self.assertEqual(p.ran, [], "importing unsloth loads PyTorch; we must not run it")

    def test_failed_environment_searches_are_recorded_too(self):
        """Regression: only successful conda/virtualenv searches were logged, so --verbose and the dashboard
        could not show where Unsloth had been looked for."""
        t = tool(dt.detect(FakeProbe("Linux")), "unsloth")
        env_checks = [s for s in t["searched"] if s["check"] == "python-package" and "site-packages" in s["target"]]
        self.assertGreaterEqual(len(env_checks), 10)
        self.assertTrue(all(not s["found"] for s in env_checks))
        self.assertIn("/home/me/miniconda3/envs/*/lib/python3*/site-packages/unsloth-*.dist-info",
                      [s["target"] for s in env_checks])

    def test_a_hit_is_still_recorded_as_found(self):
        sp = "/home/me/miniconda3/envs/llm/lib/python3.11/site-packages/"
        t = tool(dt.detect(FakeProbe("Linux", dirs=[sp + "unsloth-2025.8.2.dist-info"])), "unsloth")
        self.assertEqual(sum(1 for s in t["searched"] if s["found"] and "site-packages" in s["target"]), 1)

    def test_home_dir_alone_is_data_only(self):
        t = tool(dt.detect(FakeProbe("Linux", dirs=["/home/me/.unsloth"])), "unsloth")
        self.assertEqual(t["status"], "data-only")

    def test_macos_conda_env_and_unsloth_studio_env(self):
        for sp in ("/Users/me/miniconda3/envs/llm/lib/python3.11/site-packages/",
                   "/Users/me/.unsloth/studio/unsloth_studio/lib/python3.12/site-packages/"):
            with self.subTest(sp):
                t = tool(dt.detect(FakeProbe("Darwin", dirs=[sp + "unsloth-2025.8.2.dist-info"])), "unsloth")
                self.assertEqual((t["status"], t["version"]), ("installed", "2025.8.2"))

    def test_tools_without_python_packages_do_not_search_environments(self):
        for tool_id in ("ollama", "llama-cpp", "lmstudio"):
            t = tool(dt.detect(FakeProbe("Linux")), tool_id)
            looked = [s for s in t["searched"] if "site-packages" in s["target"]]
            self.assertEqual(looked == [], tool_id != "llama-cpp", tool_id)


class TestEnvSitePackagesPatterns(unittest.TestCase):
    """Pins the exact folders searched (and their order: the first match supplies the version) on each system."""

    def test_windows(self):
        pats = dt.env_site_packages(FakeProbe("Windows"))
        self.assertEqual(len(pats), 38)
        self.assertEqual(pats[0], r"C:\Users\me\miniconda3\Lib\site-packages")
        self.assertEqual(pats[11], r"C:\ProgramData\anaconda3\Lib\site-packages")
        self.assertEqual(pats[12], r"C:\Users\me\miniconda3\envs\*\Lib\site-packages")
        self.assertEqual(pats[24], r"C:\Users\me\miniconda3\*\Lib\site-packages")
        self.assertEqual(pats[-2], r"C:\Users\me\AppData\Local\Programs\Python\Python3*\Lib\site-packages")
        self.assertEqual(pats[-1], r"C:\Users\me\.unsloth\*\*\Lib\site-packages")

    def test_linux_and_macos(self):
        for system, home, root in (("Linux", "/home/me", "/home/me/proj"), ("Darwin", "/Users/me", "/Users/me/proj")):
            with self.subTest(system):
                pats = dt.env_site_packages(FakeProbe(system))
                self.assertEqual(len(pats), 31)
                self.assertEqual(pats[0], f"{home}/miniconda3/lib/python3*/site-packages")
                self.assertEqual(pats[9], f"{root}/.venv/lib/python3*/site-packages")
                self.assertEqual(pats[10], f"{home}/miniconda3/envs/*/lib/python3*/site-packages")
                self.assertEqual(pats[20], f"{home}/miniconda3/*/lib/python3*/site-packages")
                self.assertEqual(pats[-1], f"{home}/.unsloth/*/*/lib/python3*/site-packages")
                self.assertFalse(any("ProgramData" in p or "Programs" in p for p in pats))


class TestVersionHandling(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(dt.parse_version("ollama version is 0.5.1", r"(\d+\.\d+\.\d+\S*)"), "0.5.1")
        self.assertEqual(dt.parse_version("\x1b[1mhello\x1b[0m\nworld", ""), "hello")
        self.assertEqual(dt.parse_version("", r"(\d+)"), "")
        self.assertEqual(dt.parse_version("no digits here", r"(\d+\.\d+)"), "no digits here")
        self.assertEqual(len(dt.parse_version("x" * 500, "")), 80)

    def test_program_that_prints_nothing_is_still_installed(self):
        p = FakeProbe("Linux", files=["/usr/bin/ollama"], path={"ollama": "/usr/bin/ollama"})
        t = tool(dt.detect(p), "ollama")
        self.assertEqual((t["status"], t["version"]), ("installed", ""))

    def test_no_version_flag_runs_nothing(self):
        p = FakeProbe("Linux", path={"ollama": "/usr/bin/ollama"})
        t = tool(dt.detect(p, want_version=False), "ollama")
        self.assertEqual((t["status"], p.ran), ("installed", []))


class TestCli(unittest.TestCase):
    def run_main(self, argv, probe):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = dt.main(argv, probe)
        return code, buf.getvalue()

    def test_json_schema(self):
        p = FakeProbe("Linux", path={"ollama": "/usr/bin/ollama"}, files=["/usr/bin/ollama"])
        code, out = self.run_main(["--json"], p)
        data = json.loads(out)
        self.assertEqual((code, data["schema"]), (0, 1))
        self.assertEqual([t["id"] for t in data["tools"]], ["ollama", "llama-cpp", "lmstudio", "unsloth"])
        for t in data["tools"]:
            self.assertEqual(set(t), {"id", "label", "status", "version", "evidence"})
            self.assertIn(t["status"], ("installed", "data-only", "not-found"))
        self.assertEqual(set(data["platform"]), {"system", "machine", "python"})

    def test_json_verbose_adds_searched(self):
        _, out = self.run_main(["--json", "-v"], FakeProbe("Linux"))
        self.assertIn("searched", json.loads(out)["tools"][0])

    def test_tool_filter(self):
        _, out = self.run_main(["--json", "--tool", "unsloth", "--tool", "ollama"], FakeProbe("Linux"))
        self.assertEqual([t["id"] for t in json.loads(out)["tools"]], ["unsloth", "ollama"])

    def test_strict_exit_codes(self):
        installed = FakeProbe("Linux", path={"ollama": "/usr/bin/ollama"}, files=["/usr/bin/ollama"])
        self.assertEqual(self.run_main(["--strict", "--tool", "ollama"], installed)[0], 0)
        self.assertEqual(self.run_main(["--strict"], installed)[0], 1)
        self.assertEqual(self.run_main([], installed)[0], 0, "without --strict, missing tools are not an error")

    def test_data_only_fails_strict(self):
        p = FakeProbe("Linux", dirs=["/home/me/.ollama"])
        self.assertEqual(self.run_main(["--strict", "--tool", "ollama"], p)[0], 1)

    def test_unknown_tool_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            dt.main(["--tool", "nope"], FakeProbe("Linux"))
        self.assertEqual(cm.exception.code, 2)

    def test_text_output_is_one_line_per_tool_and_ascii(self):
        _, out = self.run_main([], FakeProbe("Linux", pkgs={"unsloth": "1.0"}))
        self.assertEqual(len(out.strip().splitlines()), 1 + 4)
        out.encode("ascii")
        self.assertRegex(out, r"Unsloth\s+INSTALLED")

    def test_verbose_text_lists_checked_locations(self):
        _, out = self.run_main(["-v", "--tool", "ollama"], FakeProbe("Linux"))
        self.assertIn("miss PATH: ollama", out)


class TestRealMachineSmoke(unittest.TestCase):
    """Reads the real machine; asserts shape only, since what is installed differs per computer."""

    def test_real_probe_returns_well_formed_result(self):
        result = dt.detect(dt.Probe(), want_version=False)
        json.dumps(result)
        self.assertEqual(len(result["tools"]), 4)
        for t in result["tools"]:
            self.assertIn(t["status"], ("installed", "data-only", "not-found"))
            self.assertEqual(t["status"] == "not-found", t["evidence"] == [])


class TestRealProbe(unittest.TestCase):
    """The real Probe's file-system helpers, on a throw-away directory."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.probe = dt.Probe()

    def test_files_dirs_and_globs(self):
        exe = self.tmp / "tool.exe"
        exe.write_text("x")
        if sys.platform != "win32":
            exe.chmod(0o755)
        (self.tmp / "d").mkdir()
        self.assertTrue(self.probe.is_exe(str(exe)))
        self.assertFalse(self.probe.is_exe(str(self.tmp / "missing")))
        self.assertFalse(self.probe.is_exe(str(self.tmp / "d")), "a directory is not an executable")
        self.assertTrue(self.probe.is_dir(str(self.tmp / "d")))
        self.assertFalse(self.probe.is_dir(str(exe)))
        self.assertEqual(self.probe.glob(str(self.tmp / "*.exe")), [str(exe)])

    @unittest.skipIf(sys.platform == "win32", "execute permission bits only exist on POSIX")
    def test_a_file_without_execute_permission_is_not_an_executable(self):
        plain = self.tmp / "plain"
        plain.write_text("x")
        plain.chmod(0o644)
        self.assertFalse(self.probe.is_exe(str(plain)))

    def test_join_and_norm_follow_the_probe_system(self):
        win = FakeProbe("Windows")
        self.assertEqual(win.join("C:\\a", "b"), "C:\\a\\b")
        self.assertEqual(FakeProbe("Linux").join("/a", "b"), "/a/b")
        self.assertEqual(win.norm("C:\\Users\\ME"), "c:/users/me", "Windows paths are case-insensitive")
        self.assertEqual(FakeProbe("Linux").norm("/A/b"), "/A/b")

    def test_py_package_known_and_unknown(self):
        with unittest.mock.patch.object(dt.importlib.metadata, "version", return_value="1.2.3"):
            self.assertEqual(self.probe.py_package("anything"), "1.2.3")
        self.assertEqual(self.probe.py_package("definitely-not-installed-xyz"), "")

    def test_dist_info_version_parsing(self):
        self.assertEqual(dt._dist_version("/sp/unsloth-2025.8.2.dist-info", "unsloth"), "2025.8.2")
        self.assertEqual(dt._dist_version("C:\\sp\\llama_cpp_python-0.3.1.dist-info", "llama-cpp-python"), "0.3.1")
        self.assertEqual(dt._dist_version("/sp/other-1.0.dist-info", "unsloth"), "")


class TestRunAsProgram(unittest.TestCase):
    """The file is also a command: python utils/detect_tools.py (what the launcher scripts run)."""

    def run_script(self, *args):
        return subprocess.run([sys.executable, dt.__file__, *args], capture_output=True, text=True, timeout=120)

    def test_json_output_and_exit_code(self):
        done = self.run_script("--json", "--no-version")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["schema"], 1)

    def test_help_and_bad_option(self):
        self.assertEqual(self.run_script("--help").returncode, 0)
        self.assertEqual(self.run_script("--tool", "nope").returncode, 2)


class TestSourceIsReadOnly(unittest.TestCase):
    """detect_tools.py is meant to be trusted on any laptop: it must stay read-only and offline."""

    def test_no_writes_deletes_network_or_shell(self):
        banned = r"(write_text|write_bytes|open\(|os\.replace|os\.remove|unlink|rmdir|rmtree|shutil\.(move|copy)|" \
                 r"urllib|http|socket|os\.system|os\.popen|shell\s*=|eval\(|exec\()"
        code = "\n".join(l for l in SOURCE.splitlines() if not l.lstrip().startswith("#"))
        code = re.sub(r'""".*?"""', "", code, flags=re.S)       # prose in docstrings may say "network"
        self.assertIsNone(re.search(banned, code), re.search(banned, code))

    def test_only_version_flags_are_ever_passed_to_programs(self):
        self.assertEqual(set(re.findall(r'version_args=(\[[^\]]*\]|None)', SOURCE)), {'["--version"]', "None"})


if __name__ == "__main__":
    unittest.main()
