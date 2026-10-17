"""Tests of the test harness itself: the rules that keep the project test-driven.

  * every module in utils/ has a tests/test_<module>.py
  * every HTTP route the setup page's server exposes is exercised by some test
  * every launcher exists for Windows, macOS and Linux
  * all sources compile without SyntaxWarning / invalid-escape warnings (a bad regex is a bug)
  * the runner (tests/run.py), the CI workflow and the written workflow (tests/README.md) exist and agree
If you add a feature and one of these fails, that is the point: write its tests (first).
"""
import ast
import contextlib
import importlib.util
import io
import os
import platform
import re
import subprocess
import sys
import unittest
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
UTILS = sorted((ROOT / "utils").glob("*.py"))
TESTS = sorted(HERE.glob("test_*.py"))


def source(path):
    return Path(path).read_text(encoding="utf-8")


class TestEveryModuleHasTests(unittest.TestCase):
    def test_each_utils_module_has_a_test_file(self):
        for mod in UTILS:
            self.assertTrue((HERE / f"test_{mod.stem}.py").is_file(), f"utils/{mod.name} has no tests/test_{mod.stem}.py")

    def test_each_test_file_really_contains_tests(self):
        for path in TESTS:
            tree = ast.parse(source(path))
            tests = [n for c in ast.walk(tree) if isinstance(c, ast.ClassDef) and
                     any(isinstance(b, (ast.Attribute, ast.Name)) for b in c.bases)
                     for n in c.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
            self.assertTrue(tests, f"{path.name} defines no test methods")

    def test_every_api_route_is_exercised(self):
        routes = set(re.findall(r'"(/api/[a-z_/]+)"', source(ROOT / "utils" / "ui_server.py")))
        self.assertTrue(routes, "found no routes - did the server change shape?")
        tests = "\n".join(source(p) for p in TESTS if p.name != "test_harness.py")
        for route in sorted(routes):
            self.assertIn(route, tests, f"no test mentions {route}")

    def test_skips_are_few_and_explained(self):
        skips = []
        for path in TESTS:
            for node in ast.walk(ast.parse(source(path))):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr.startswith("skip") and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "unittest"):
                    reason = node.args[-1] if node.args else None
                    ok = isinstance(reason, ast.Constant) and isinstance(reason.value, str) and len(reason.value) >= 8
                    self.assertTrue(ok, f"{path.name}:{node.lineno} a skip needs a written reason")
                    skips.append((path.name, node.lineno))
        self.assertLessEqual(len(skips), 2, skips)       # node missing, POSIX permission bits


class TestLaunchers(unittest.TestCase):
    def test_every_unix_launcher_has_windows_and_mac_siblings(self):
        scripts = ROOT / "scripts"
        stems = {p.stem for p in (scripts / "unix").glob("*.sh")} - {"test"}      # test.sh is a developer tool
        self.assertTrue({"model-setup", "serve", "ui", "detect-tools"} <= stems)
        for stem in stems:
            self.assertTrue((scripts / "mac" / f"{stem}.command").is_file(), f"mac/{stem}.command missing")
            self.assertTrue(any((scripts / "win" / f"{stem}{ext}").is_file() for ext in (".bat", ".ps1")),
                            f"win/{stem}.(bat|ps1) missing")

    def test_mac_launcher_that_pauses_returns_the_tools_exit_status(self):
        """Regression: `read` after the tool made the launcher return read's status, so a failed --strict
        check looked like success (and closed stdin made a good run look like a failure)."""
        text = source(ROOT / "scripts" / "mac" / "detect-tools.command")
        self.assertIn("status=$?", text, "save the tool's exit status before prompting")
        self.assertRegex(text, r"(?m)^exit \"?\$status\"?\s*$", "and return it at the end")
        self.assertLess(text.index("status=$?"), text.index("read "), "save it before the prompt, not after")

    def test_launchers_only_start_python_utils(self):
        for sh in (ROOT / "scripts" / "unix").glob("*.sh"):
            text = source(sh)
            self.assertTrue(text.startswith("#!/usr/bin/env bash"), sh.name)


def code_lines(path):
    """Executable lines of a launcher: no blanks, no comments."""
    out = []
    for line in source(path).replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if s and not s.startswith("#") and not s.lower().startswith(("rem ", "::", "@echo off")):
            out.append(s)
    return out


class TestLauncherExitStatus(unittest.TestCase):
    """Rule 7: a launcher returns the tool's exit status. Anything that runs after the tool (a pause, cleanup,
    `if errorlevel`) must not replace it. Seen in PR #1: the mac launcher returned `read`'s status."""

    def test_every_launcher_ends_by_returning_a_status(self):
        scripts = ROOT / "scripts"
        for path in sorted(list((scripts / "unix").glob("*.sh")) + list((scripts / "mac").glob("*.command"))):
            last = code_lines(path)[-1]
            self.assertRegex(last, r"^(exec |exit )", f"{path.name}: last line is {last!r}; end with exec or exit")
        for path in sorted((scripts / "win").glob("*.bat")):
            last = code_lines(path)[-1]
            self.assertRegex(last, r"(?i)^exit /b %\w+%$", f"{path.name}: last line is {last!r}; end with exit /b %rc%")

    def test_launchers_really_pass_the_status_through(self):
        """Run the launchers that exist for this OS with an option no tool accepts: argparse exits with 2."""
        scripts = ROOT / "scripts"
        if sys.platform == "win32":
            runs = [[str(scripts / "win" / f"{stem}.bat")] for stem in ("detect-tools", "model-setup")]
        else:
            runs = [["bash", str(scripts / "unix" / "detect-tools.sh")], ["bash", str(scripts / "mac" / "detect-tools.command")],
                    ["bash", str(scripts / "unix" / "model-setup.sh")]]
        self.assertTrue(runs)
        for cmd in runs:
            with self.subTest(cmd=Path(cmd[-1]).name):
                done = subprocess.run(cmd + ["--definitely-not-an-option"], stdin=subprocess.DEVNULL,
                                      capture_output=True, text=True, timeout=120)
                self.assertEqual(done.returncode, 2, done.stdout + done.stderr)


class TestPersonas(unittest.TestCase):
    """`tests/run.py --as mac` runs the suite while pretending to be another machine, so host-dependent tests
    (rule 2) fail on any developer's computer instead of only on the CI runner of another OS."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("lp_run_personas", HERE / "run.py")
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    def test_personas_are_defined_and_windows_is_not_one_of_them(self):
        self.assertEqual(self.runner.PERSONAS["mac"], ("Darwin", "arm64"))
        self.assertEqual(self.runner.PERSONAS["mac-intel"], ("Darwin", "x86_64"))
        self.assertEqual(self.runner.PERSONAS["linux"], ("Linux", "x86_64"))
        self.assertNotIn("windows", self.runner.PERSONAS, "ctypes.windll / winreg cannot be faked; real Windows CI covers it")

    def test_option_is_parsed_and_passed_on_to_the_coverage_child(self):
        args = self.runner.parse_args(["--as", "mac", "--cov", "-q"])
        self.assertEqual(args.persona, "mac")
        self.assertEqual(self.runner.child_args(args), ["--as", "mac", "--quiet"])
        self.assertIsNone(self.runner.parse_args([]).persona)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            self.runner.parse_args(["--as", "windows"])
        self.assertEqual(cm.exception.code, 2)

    def test_applying_a_persona_changes_the_platform_and_can_be_undone(self):
        real = (platform.system(), platform.machine())
        marker = os.environ.get("LP_TEST_PERSONA")          # set already when this suite itself runs under --as
        undo = self.runner.apply_persona("mac")
        try:
            self.assertEqual((platform.system(), platform.machine()), ("Darwin", "arm64"))
            self.assertEqual(os.environ.get("LP_TEST_PERSONA"), "mac")
        finally:
            undo()
        self.assertEqual((platform.system(), platform.machine()), real)
        self.assertEqual(os.environ.get("LP_TEST_PERSONA"), marker)

    def test_canary_the_platform_matches_the_requested_persona(self):
        """Meaningless on its own; test_runner_applies_the_persona runs it under `--as` to prove it took effect."""
        name = os.environ.get("LP_TEST_PERSONA")
        if name:
            self.assertEqual((platform.system(), platform.machine()), self.runner.PERSONAS[name])

    def test_runner_applies_the_persona(self):
        for name, (system, machine) in (("mac", ("Darwin", "arm64")), ("linux", ("Linux", "x86_64"))):
            with self.subTest(name):
                done = subprocess.run([sys.executable, "-I", str(HERE / "run.py"), "--as", name, "-q", "-k", "test_canary_the_platform"],
                                      capture_output=True, text=True, timeout=120)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertIn(f"pretending to be {system} {machine}", done.stdout)
                self.assertIn("Ran 1 test", done.stderr + done.stdout)

    def test_ci_runs_the_suite_as_each_persona(self):
        text = source(ROOT / ".github" / "workflows" / "ci.yml")
        self.assertIn("tests/run.py --quiet --as ${{ matrix.persona }}", text)
        listed = re.search(r"persona: \[([^\]]*)\]", text)
        self.assertTrue(listed, "CI has no persona matrix")
        self.assertEqual(sorted(n.strip() for n in listed.group(1).split(",")), sorted(self.runner.PERSONAS),
                         "the CI persona list must match PERSONAS in tests/run.py")


class TestSourcesCompileCleanly(unittest.TestCase):
    def test_no_syntax_or_escape_warnings(self):
        for path in UTILS + TESTS + [HERE / "run.py", HERE / "fakes.py"]:
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                try:
                    compile(source(path), str(path), "exec")
                except (SyntaxWarning, DeprecationWarning) as e:
                    self.fail(f"{path.name}: {e}")

    def test_no_stray_control_characters(self):
        for path in UTILS + TESTS:
            bad = [c for c in source(path) if ord(c) < 32 and c not in "\n\r\t"]
            self.assertFalse(bad, f"{path.name} contains control characters {bad!r}")


class TestRunnerAndWorkflow(unittest.TestCase):
    def test_runner_lists_what_it_would_run(self):
        done = subprocess.run([sys.executable, "-I", str(HERE / "run.py"), "--list", "-k", "test_harness"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("test_harness", done.stdout)

    def test_coverage_child_arguments_do_not_depend_on_how_options_were_spelled(self):
        """Regression: `--cov --min=85` raised ValueError because the child command was rebuilt by
        looking for the two-token spelling `--min 85` in the original arguments."""
        spec = importlib.util.spec_from_file_location("lp_run", HERE / "run.py")
        run = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(run)
        for spelling in (["--min", "85"], ["--min=85"]):
            args = run.parse_args(["--cov", *spelling, "-k", "ollama", "--repeat=2", "--failfast", "-q"])
            self.assertEqual((args.cov, args.min), (True, 85))
            self.assertEqual(run.child_args(args), ["-k", "ollama", "--repeat", "2", "--failfast", "--quiet"], spelling)
        self.assertEqual(run.child_args(run.parse_args([])), [])
        self.assertEqual(run.child_args(run.parse_args(["--list"])), ["--list"])

    def test_runner_exit_code_reflects_failure(self):
        done = subprocess.run([sys.executable, "-I", str(HERE / "run.py"), "-k", "no_such_test_name_xyz"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 2, "running zero tests is an error, not a pass")

    def test_ci_runs_the_runner_on_all_three_platforms(self):
        text = source(ROOT / ".github" / "workflows" / "ci.yml")
        for needle in ("ubuntu-latest", "macos-latest", "windows-latest", "tests/run.py", "--repeat"):
            self.assertIn(needle, text)

    def test_readme_covers_every_launcher_and_the_test_command(self):
        readme = source(ROOT / "README.md")
        for stem in ("model-setup", "serve", "ui", "detect-tools"):
            self.assertIn(stem, readme, f"README never mentions {stem}")
        self.assertIn("python tests/run.py", readme)
        self.assertIn("Installed tools", readme, "the dashboard's tools view is documented")
        self.assertRegex(readme, r"(?s)## Start.*detect-tools.*\*\*1\. Get llama\.cpp", "quick start begins with a check")

    def test_workflow_is_documented(self):
        text = source(HERE / "README.md").lower()
        for needle in ("test first", "red", "green", "tests/run.py", "fakes.py"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
