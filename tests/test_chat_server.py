"""Tests for utils/chat_server.py: "Start chatting" on the setup page runs llama-server for the chosen model.

The llama-server here is tests/fake_llama_server.py, a real process on a real localhost port, so starting, the
starting -> running switch, failures with their log, and stopping are exercised for real on Windows, macOS and Linux.
Which OS the commands are built for is pinned (rule 2), never taken from the machine running the tests.
"""
import http.client
import os
import re
import subprocess
import sys
import threading
import time
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "utils"))
import chat_server  # noqa: E402

FAKE = str(HERE / "fake_llama_server.py")
SERVER = [sys.executable, FAKE]


class QuickServer(ThreadingHTTPServer):
    """A test web server that binds without HTTPServer's host-name lookup (getfqdn), which is slow on macOS."""

    def server_bind(self):
        super(HTTPServer, self).server_bind()           # socketserver.TCPServer.server_bind: bind only
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


def free_port():
    s = QuickServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = s.server_address[1]
    s.server_close()
    return port


class Occupied:
    """Something else listening on a port: a plain web server, or one that looks like llama-server."""

    def __init__(self, test, llama=False):
        class H(BaseHTTPRequestHandler):
            server_version = "OtherApp/1.0"

            def log_message(self, *_a):
                pass

            def do_GET(self):
                body = b'{"model_path": "/somewhere/else.gguf"}' if llama and self.path == "/props" else b"hello"
                self.send_response(200 if llama or self.path == "/" else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        self.server = QuickServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        test.addCleanup(self.server.server_close)
        test.addCleanup(self.server.shutdown)


class Base(unittest.TestCase):
    system = "Linux"

    def setUp(self):
        self.env = {"PORT": str(free_port()), "EXTRA_ARGS": ""}
        self.model = Path("/models/My Model-Q4_K_M.gguf")
        self.ran = []
        self.cs = self.make()
        self.addCleanup(self.cs.stop)

    def make(self, server=SERVER, run_output=None):
        def run(args, timeout=20):
            self.ran.append(list(args))
            return (run_output or {}).get(Path(args[0]).name, "")
        return chat_server.ChatServer(find_server=lambda: list(server), environ=self.env, system=self.system,
                                      which=lambda name: "", run=run)

    def wait(self, *states, timeout=30):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            s = self.cs.status()
            if s["state"] in states:
                return s
            time.sleep(0.05)
        self.fail(f"never reached {states}: {self.cs.status()}")


class TestCommand(Base):
    def test_same_arguments_as_the_serve_scripts_with_port_and_extra_args_from_the_environment(self):
        """serve.sh and serve.ps1 run: llama-server -m MODEL --port PORT, then EXTRA_ARGS split on whitespace."""
        self.env.update(PORT="9123", EXTRA_ARGS="  -t 8   -c 8192 ")
        argv, port = self.cs.command(self.model)
        self.assertEqual(argv, SERVER + ["-m", str(self.model), "--port", "9123", "-t", "8", "-c", "8192"])
        self.assertEqual(port, 9123)

    def test_defaults_to_port_8080_like_the_serve_scripts(self):
        self.env.clear()
        self.assertEqual(self.cs.command(self.model)[1], 8080)
        self.env["PORT"] = "not-a-port"
        self.assertEqual(self.cs.command(self.model)[1], 8080)

    def test_a_port_chosen_on_the_page_replaces_port(self):
        self.env["PORT"] = "9123"
        argv, port = self.cs.command(self.model, 9200)
        self.assertEqual((port, argv[argv.index("--port") + 1]), (9200, "9200"))

    def test_shown_command_is_quoted_for_this_os(self):
        """Quoting follows the pinned OS. The model path is a plain string: a host Path would turn /models into
        \\models on a Windows runner (rule 2; failed on windows-latest)."""
        model = "/models/My Model-Q4_K_M.gguf"
        for system, expect in (("Linux", f"'{model}'"), ("Darwin", f"'{model}'"), ("Windows", f'"{model}"')):
            with self.subTest(system=system):
                cs = chat_server.ChatServer(find_server=lambda: ["llama-server"], environ={"PORT": "8080"}, system=system,
                                            which=lambda n: "", run=lambda a, timeout=20: "")
                shown = cs.preview(model, check_port=False)["cmd"]
                self.assertTrue(shown.startswith("llama-server -m "), shown)
                self.assertIn(expect, shown)
                self.assertTrue(shown.endswith("--port 8080"), shown)

    def test_no_llama_server_means_no_command(self):
        """Rule 3: never show a command whose program was not found."""
        cs = self.make(server=[])
        p = cs.preview(self.model)
        self.assertNotIn("cmd", p)
        self.assertIn("llama-server was not found", p["missing"])
        code, body = cs.start(self.model, "My Model")
        self.assertEqual(code, 409)
        self.assertIn("llama-server was not found", body["error"])
        self.assertEqual(cs.status()["state"], "idle")


HELP = (HERE / "fixtures" / "llama_server_help.txt").read_text(encoding="utf-8")
OLD_HELP = "-m,    --model FNAME       model path\n--port PORT                 port to listen\n"


class TestSettings(Base):
    """Presets for the page: a plain-language choice that maps to real llama-server flags, offered only when this
    llama-server lists those flags in its --help (rule 3: installed is not the same as can run)."""

    def test_flags_are_read_from_the_flag_column_of_help(self):
        flags = chat_server.server_flags(HELP)
        for f in ("--ctx-size", "--cache-type-k", "--n-gpu-layers", "--fit", "--mmproj", "--models-preset", "--port"):
            self.assertIn(f, flags)
        self.assertNotIn("--option", flags, "words in the description column are not flags")
        self.assertEqual(chat_server.server_flags(OLD_HELP), {"--model", "--port"})

    def test_each_preset_maps_to_flags(self):
        flags = chat_server.server_flags(HELP)
        args = lambda p, **kw: chat_server.settings_args(p, flags, **kw)  # noqa: E731
        self.assertEqual(args("short"), (["-c", "4096"], ""))
        self.assertEqual(args("long"), (["-c", "32768", "-ctk", "q8_0"], ""))
        self.assertEqual(args("fast", gpu=True), (["-c", "2048", "-ngl", "99"], ""))
        self.assertEqual(args("auto"), ([], ""))

    def test_context_never_exceeds_what_the_model_was_trained_on(self):
        flags = chat_server.server_flags(HELP)
        self.assertEqual(chat_server.settings_args("long", flags, train_ctx=8192)[0][:2], ["-c", "8192"])
        self.assertEqual(chat_server.settings_args("short", flags, train_ctx=8192)[0], ["-c", "4096"])

    def test_a_context_typed_by_the_user_replaces_the_presets(self):
        flags = chat_server.server_flags(HELP)
        self.assertEqual(chat_server.settings_args("long", flags, ctx=12000)[0], ["-c", "12000", "-ctk", "q8_0"])
        for bad in (100, 10 ** 8, "4096", True):
            with self.subTest(ctx=bad):
                _, why = chat_server.settings_args("short", flags, ctx=bad)
                self.assertIn("context length must be a whole number", why)

    def test_a_preset_that_cannot_run_here_says_what_is_missing(self):
        flags = chat_server.server_flags(OLD_HELP)
        args, why = chat_server.settings_args("short", flags)
        self.assertEqual(args, [])
        self.assertIn("--ctx-size", why)
        _, why = chat_server.settings_args("fast", chat_server.server_flags(HELP), gpu=False)
        self.assertIn("graphics card", why)
        _, why = chat_server.settings_args("nonsense", chat_server.server_flags(HELP))
        self.assertIn("Unknown setting", why)

    def test_default_lets_llama_cpp_fit_the_model_only_when_it_can(self):
        """Builds with --fit pick a context that fits memory; older ones load the model's whole trained context
        with -c 0, which can be 128k tokens and run out of memory. Those get the short preset."""
        self.assertEqual(chat_server.default_preset(chat_server.server_flags(HELP)), "auto")
        no_fit = chat_server.server_flags(HELP.replace("--fit [on|off]", "--nofit-here"))
        self.assertEqual(chat_server.default_preset(no_fit), "short")
        self.assertEqual(chat_server.default_preset(set()), "auto", "nothing can be set: nothing is passed")

    def test_settings_go_before_extra_args_so_the_users_own_flags_win(self):
        self.env.update(PORT="9123", EXTRA_ARGS="-c 1000")
        argv, _ = self.cs.command(self.model, settings=["-c", "4096"])
        self.assertEqual(argv[-4:], ["-c", "4096", "-c", "1000"])

    def test_help_flags_come_from_the_real_program_and_are_remembered(self):
        cs = chat_server.ChatServer(find_server=lambda: list(SERVER), environ=self.env, system=self.system,
                                    which=lambda n: "")
        self.assertIn("--ctx-size", cs.help_flags())
        cs.find_server = lambda: []
        self.assertEqual(cs.help_flags(), set(), "no llama-server: no flags")


class TestLifecycle(Base):
    def test_the_chosen_settings_reach_llama_server(self):
        code, body = self.cs.start(self.model, "My Model", settings=["-c", "2048", "-ngl", "99"])
        self.assertEqual(code, 202, body)
        self.assertIn("-c 2048 -ngl 99", body["cmd"])
        s = self.wait("running")
        self.assertTrue(any('"-c", "2048", "-ngl", "99"' in line for line in s["log"]), s["log"])

    def test_starting_then_running_then_stopped(self):
        self.env["EXTRA_ARGS"] = "-c 4096"
        code, body = self.cs.start(self.model, "My Model")
        self.assertEqual(code, 202, body)
        self.assertIn(body["state"], ("starting", "running"))
        self.assertIn("-c 4096", body["cmd"])
        s = self.wait("running")
        port = int(self.env["PORT"])
        self.assertEqual(s["url"], f"http://127.0.0.1:{port}/")
        self.assertEqual(s["model"], "My Model")
        self.assertTrue(any('"-c", "4096"' in line for line in s["log"]), s["log"])
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/health")
        self.assertEqual(conn.getresponse().status, 200)
        conn.close()
        s = self.cs.stop()
        self.assertEqual(s["state"], "stopped")
        self.assertIsNotNone(self.cs.proc.poll(), "the process is gone")

    def test_a_second_start_while_running_is_refused(self):
        self.cs.start(self.model, "My Model")
        self.wait("running")
        code, body = self.cs.start(self.model, "My Model")
        self.assertEqual(code, 409)
        self.assertIn("already", body["error"].lower())

    def test_a_server_that_exits_while_loading_is_failed_with_its_log(self):
        self.env["FAKE_LLAMA_EXIT"] = "3"
        with unittest.mock.patch.dict(os.environ, {"FAKE_LLAMA_EXIT": "3"}):
            self.cs.start(self.model, "My Model")
            s = self.wait("failed")
        self.assertEqual(s["exit_code"], 3)
        self.assertIn("failed to load model", "\n".join(s["log"]))
        self.assertIn("exit code 3", s["error"])

    def test_failed_is_reported_only_with_the_whole_log(self):
        """The output reader runs in its own thread: "failed" must wait for it, or the error line can be missing."""
        real = self.cs._read

        def slow_reader(proc):
            time.sleep(0.5)
            real(proc)
        self.cs._read = slow_reader
        with unittest.mock.patch.dict(os.environ, {"FAKE_LLAMA_EXIT": "3"}):
            self.cs.start(self.model, "My Model")
            s = self.wait("failed")
        self.assertIn("failed to load model", "\n".join(s["log"]))

    def test_a_server_that_dies_while_running_is_failed_not_running(self):
        self.cs.start(self.model, "My Model")
        self.wait("running")
        self.cs.proc.kill()                         # not through stop(): as if it crashed
        s = self.wait("failed")
        self.assertIn("stopped unexpectedly", s["error"])

    def test_a_server_that_never_gets_ready_stays_starting_and_can_be_stopped(self):
        with unittest.mock.patch.dict(os.environ, {"FAKE_LLAMA_LOAD_S": "600"}):
            self.cs.start(self.model, "My Model")
            time.sleep(1.0)
            self.assertEqual(self.cs.status()["state"], "starting")
            self.assertEqual(self.cs.stop()["state"], "stopped")

    def test_it_can_start_again_after_stopping_or_failing(self):
        self.cs.start(self.model, "My Model")
        self.wait("running")
        self.cs.stop()
        self.assertEqual(self.cs.start(self.model, "My Model")[0], 202)
        self.wait("running")


class TestStartIsAtomic(Base):
    """Regression (review on #3): the idle check and Popen were not one step, so two Start clicks (two tabs) could
    both start a server; the first was then out of reach of Stop and of the page's shutdown."""

    def test_two_starts_at_once_start_one_server(self):
        real = chat_server.port_in_use

        def slow(port):
            time.sleep(0.3)                     # both requests are past the state check before either starts
            return real(port)
        results = []
        with unittest.mock.patch.object(chat_server, "port_in_use", slow), \
                unittest.mock.patch.object(chat_server.subprocess, "Popen", wraps=subprocess.Popen) as popen:
            ports = [free_port(), free_port()]      # different ports: the busy-port check cannot hide the race
            threads = [threading.Thread(target=lambda p=p: results.append(self.cs.start(self.model, "M", p)[0])) for p in ports]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        self.assertEqual(sorted(results), [202, 409])
        self.assertEqual(popen.call_count, 1, "only one llama-server was started")

    def test_no_start_while_stopping(self):
        self.cs.job = {"state": "stopping"}
        self.addCleanup(setattr, self.cs, "job", {"state": "idle"})
        code, body = self.cs.start(self.model, "M")
        self.assertEqual(code, 409)
        self.assertIn("stopping", body["error"])

    def test_a_start_that_cannot_launch_releases_its_reservation(self):
        for failure in ("busy-port", "popen"):
            with self.subTest(failure=failure):
                if failure == "busy-port":
                    with unittest.mock.patch.object(chat_server, "port_in_use", return_value=True), \
                            unittest.mock.patch.object(self.cs, "busy", return_value={"used_by": "", "free_port": 0, "looked": []}):
                        self.assertEqual(self.cs.start(self.model, "M")[0], 409)
                else:
                    with unittest.mock.patch.object(chat_server.subprocess, "Popen", side_effect=OSError("exec format error")):
                        code, body = self.cs.start(self.model, "M")
                    self.assertEqual(code, 500)
                    self.assertEqual(self.cs.status()["state"], "failed")
                self.assertEqual(self.cs.start(self.model, "M")[0], 202, "the next start is not blocked")
                self.wait("running")
                self.cs.stop()


class TestOnlyItsOwnServer(Base):
    """Never copy serve.sh's KILL_EXISTING (it stops every llama-server on the machine)."""

    def other_llama_server(self):
        port = free_port()
        other = subprocess.Popen(SERVER + ["-m", "other.gguf", "--port", str(port)], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        self.addCleanup(other.wait, 30)
        self.addCleanup(other.kill)
        return other

    def test_stop_with_nothing_started_touches_nothing(self):
        other = self.other_llama_server()
        self.assertEqual(self.cs.stop()["state"], "idle")
        time.sleep(0.3)
        self.assertIsNone(other.poll(), "a llama-server this page did not start was stopped")

    def test_stopping_ours_leaves_others_running(self):
        other = self.other_llama_server()
        self.cs.start(self.model, "My Model")
        self.wait("running")
        self.cs.stop()
        time.sleep(0.3)
        self.assertIsNone(other.poll(), "a llama-server this page did not start was stopped")

    def test_stop_uses_no_posix_signals_or_process_name_kills(self):
        """Windows has no POSIX signals: stop the one process we started through Popen (TerminateProcess there),
        never by name (pkill / taskkill /IM) and never with os.kill or signal."""
        text = (HERE.parent / "utils" / "chat_server.py").read_text(encoding="utf-8")
        for banned in ("import signal", "os.kill", "pkill", "killall", "taskkill", "/IM", "SIGKILL", "SIGTERM"):
            self.assertNotIn(banned, text)

    def test_stop_terminates_then_kills_if_it_does_not_exit(self):
        proc = unittest.mock.Mock()
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired("llama-server", 10), 0]
        self.cs.proc, self.cs.job = proc, {"state": "running"}
        self.cs.stop()
        proc.terminate.assert_called_once_with()
        proc.kill.assert_called_once_with()


class TestBusyPort(Base):
    def test_a_busy_port_is_not_used_and_the_next_free_one_is_offered(self):
        occ = Occupied(self)
        self.env["PORT"] = str(occ.port)
        code, body = self.cs.start(self.model, "My Model")
        self.assertEqual(code, 409)
        busy = body["port_busy"]
        self.assertEqual(busy["port"], occ.port)
        self.assertIn(f"Port {occ.port} is already in use", body["error"])
        self.assertGreater(busy["free_port"], occ.port)
        self.assertFalse(chat_server.port_in_use(busy["free_port"]))
        self.assertEqual(self.cs.status()["state"], "idle", "nothing was started")
        self.assertEqual(self.cs.start(self.model, "My Model", busy["free_port"])[0], 202)
        self.assertEqual(self.wait("running")["port"], busy["free_port"])

    def test_preview_says_what_is_using_the_port(self):
        occ = Occupied(self)
        self.env["PORT"] = str(occ.port)
        busy = self.cs.preview(self.model)["busy"]
        self.assertIn("OtherApp/1.0", busy["used_by"])
        self.assertTrue(any(f"127.0.0.1:{occ.port}" in line for line in busy["looked"]), busy["looked"])

    def test_another_llama_server_on_the_port_is_named_with_its_model(self):
        occ = Occupied(self, llama=True)
        self.env["PORT"] = str(occ.port)
        busy = self.cs.preview(self.model)["busy"]
        self.assertIn("another llama-server", busy["used_by"])
        self.assertIn("else.gguf", busy["used_by"])

    def test_a_free_port_is_not_busy(self):
        self.assertIsNone(self.cs.preview(self.model)["busy"])


class TestPortChecksDoNoNameLookups(unittest.TestCase):
    """Regression (macOS CI): http.server's HTTPServer.server_bind() calls socket.getfqdn(), a host-name lookup that
    can take seconds on macOS. The port check binds up to 100 ports to find a free one, so it must not look names up."""

    def test_port_checks_never_resolve_host_names(self):
        import socket
        with unittest.mock.patch.object(socket, "getfqdn", side_effect=AssertionError("getfqdn called")), \
                unittest.mock.patch.object(socket, "gethostbyaddr", side_effect=AssertionError("gethostbyaddr called")):
            port = free_port()
            self.assertFalse(chat_server.port_in_use(port))
            occ = Occupied(self)
            self.assertTrue(chat_server.port_in_use(occ.port))
            self.assertGreater(chat_server.next_free_port(occ.port), occ.port)


class TestWhoUsesThePort(unittest.TestCase):
    """The program name comes from the OS tools that exist on this kind of machine; every miss is logged (rule 5)."""

    def who(self, system, which, outputs):
        ran = []

        def run(args, timeout=20):
            ran.append(list(args))
            return outputs.get(re.split(r"[\\/]", args[0])[-1], "")      # a Windows path, split the same on any host
        with unittest.mock.patch.object(chat_server, "http_probe", return_value=("", "no answer over HTTP")):
            used_by, looked = chat_server.who_uses(8080, system, lambda n: which.get(n, ""), run)
        return used_by, looked, ran

    def test_lsof_on_mac_and_linux(self):
        out = "p4242\ncollama\nf3\n"
        for system in ("Darwin", "Linux"):
            used_by, looked, ran = self.who(system, {"lsof": "/usr/sbin/lsof"}, {"lsof": out})
            self.assertEqual(used_by, "ollama (process 4242)")
            self.assertEqual(ran[0][:2], ["/usr/sbin/lsof", "-nP"])

    def test_ss_on_linux_without_lsof(self):
        out = 'LISTEN 0 4096 127.0.0.1:8080 0.0.0.0:* users:(("python3",pid=777,fd=3))\n'
        used_by, looked, ran = self.who("Linux", {"ss": "/usr/bin/ss"}, {"ss": out})
        self.assertEqual(used_by, "python3 (process 777)")
        self.assertTrue(any("lsof: not found" in line for line in looked), looked)

    def test_netstat_and_tasklist_on_windows(self):
        netstat = ("  Proto  Local Address          Foreign Address        State           PID\n"
                   "  TCP    0.0.0.0:80             0.0.0.0:0              LISTENING       4\n"
                   "  TCP    127.0.0.1:8080         0.0.0.0:0              LISTENING       5150\n"
                   "  TCP    127.0.0.1:18080        0.0.0.0:0              LISTENING       9\n")
        tasklist = '"Docker Desktop.exe","5150","Console","1","12,345 K"\n'
        used_by, looked, ran = self.who("Windows", {"netstat": r"C:\Windows\System32\NETSTAT.EXE",
                                                    "tasklist": r"C:\Windows\System32\tasklist.exe"},
                                        {"NETSTAT.EXE": netstat, "tasklist.exe": tasklist})
        self.assertEqual(used_by, "Docker Desktop.exe (process 5150)")
        self.assertIn("PID eq 5150", " ".join(ran[1]))

    def test_nothing_found_says_where_it_looked(self):
        used_by, looked, _ = self.who("Linux", {}, {})
        self.assertEqual(used_by, "")
        self.assertEqual(len(looked), 3, looked)            # HTTP, lsof, ss: each one a recorded miss
        self.assertTrue(all(line for line in looked))


if __name__ == "__main__":
    unittest.main()
