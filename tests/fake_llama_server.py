"""A stand-in for llama.cpp's llama-server, for tests. Run as `python fake_llama_server.py <llama-server args>`.

It behaves like the real program where the launchpad depends on it:
  --version           prints a version banner and exits 0
  --list-devices      prints FAKE_LLAMA_DEVICES (default: no GPU) and exits 0
  -m FILE --port N    listens on 127.0.0.1:N; /health answers 503 "Loading model" for FAKE_LLAMA_LOAD_S seconds
                      (default 0.3), then 200 {"status": "ok"}; /props names the model. Prints its arguments first,
                      so tests can see exactly what it was started with. A busy port: prints an error, exits 1.
Failure knobs (environment): FAKE_LLAMA_EXIT=<code> prints an error and exits with that code before listening;
FAKE_LLAMA_VERSION_FAIL=1 makes --version fail. Standard library only.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def arg(name, default=""):
    a = sys.argv[1:]
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default


def main():
    if "--version" in sys.argv:
        if os.environ.get("FAKE_LLAMA_VERSION_FAIL") == "1":
            print("error while loading shared libraries: libggml.so: cannot open shared object file", flush=True)
            return 127
        print("version: 4242 (abc1234)\nbuilt with fake-cc for test", flush=True)
        return 0
    if "--list-devices" in sys.argv:
        print(os.environ.get("FAKE_LLAMA_DEVICES", "Available devices:"), flush=True)
        return 0
    print("fake llama-server args: " + json.dumps(sys.argv[1:]), flush=True)
    code = os.environ.get("FAKE_LLAMA_EXIT")
    if code:
        print("error: failed to load model '" + arg("-m") + "'", flush=True)
        return int(code)
    port = int(arg("--port", "8080"))
    ready_at = time.monotonic() + float(os.environ.get("FAKE_LLAMA_LOAD_S", "0.3"))
    model = arg("-m")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def do_GET(self):
            if self.path == "/health":
                ok = time.monotonic() >= ready_at
                body = {"status": "ok"} if ok else {"error": {"code": 503, "message": "Loading model"}}
                return self.answer(200 if ok else 503, body)
            if self.path == "/props":
                return self.answer(200, {"model_path": model})
            return self.answer(404, {"error": "not found"})

        def answer(self, code, obj):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            for i in range(0, len(data), 65536):            # small writes (CLAUDE.md rule 9)
                self.wfile.write(data[i:i + 65536])

    class Server(ThreadingHTTPServer):
        allow_reuse_address = sys.platform != "win32"      # as cpp-httplib: never share a port on Windows

    try:
        server = Server(("127.0.0.1", port), Handler)
    except OSError as e:
        print(f"couldn't bind HTTP server socket, hostname: 127.0.0.1, port: {port} ({e})", flush=True)
        return 1
    print(f"main: server is listening on http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
