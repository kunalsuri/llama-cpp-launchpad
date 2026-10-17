"""Tests of the test harness itself: the rules that keep the project test-driven.

  * every module in utils/ has a tests/test_<module>.py
  * every HTTP route the setup page's server exposes is exercised by some test
  * every launcher exists for Windows, macOS and Linux
  * all sources compile without SyntaxWarning / invalid-escape warnings (a bad regex is a bug)
  * the runner (tests/run.py), the CI workflow and the written workflow (tests/README.md) exist and agree
If you add a feature and one of these fails, that is the point: write its tests (first).
"""
import ast
import importlib.util
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
        self.assertLessEqual(len(skips), 3, skips)       # node missing, POSIX permission bits, Linux /proc format


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
