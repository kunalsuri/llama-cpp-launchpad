// Runs the real <script> of ui/setup/index.html against a tiny fake DOM, fake fetch and fake timers, and
// prints one JSON line per scenario: {"name": ..., "ok": true|false, "detail": ...}.
// Driven by tests/test_ui_server.py (TestPageScript). Usage: node tests/page_harness.js ui/setup/index.html
"use strict";
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync(process.argv[2], "utf8");
const script = html.slice(html.indexOf("<script>") + 8, html.indexOf("</script>"));

class El {
  constructor(id = "", hidden = false, className = "") {
    Object.assign(this, { id, hidden, className, textContent: "", children: [], style: {}, nodeType: 1, onclick: null, attrs: {}, handlers: {} });
    this.classList = { add() {}, remove() {}, contains: () => false };
  }
  append(...kids) { for (const k of kids) this.children.push(k); }
  replaceChildren(...kids) { this.children = []; this.append(...kids); }
  addEventListener(ev, fn) { this.handlers[ev] = fn; }
  setAttribute(k, v) { this.attrs[k] = v; }
  querySelector() { return null; }
  remove() {}
  click() { const f = this.onclick || this.handlers.click; if (f) return f(); }
  text() { return [this.textContent, ...this.children.map((c) => (c.text ? c.text() : c.textContent || ""))].join(" "); }
}

function makePage({ hash = "", routes }) {
  const els = new Map();
  for (const m of html.matchAll(/<(\w+)([^>]*)>/g)) {
    const id = /\bid="([^"]+)"/.exec(m[2]);
    if (!id) continue;
    els.set(id[1], new El(id[1], /\bhidden\b/.test(m[2]), (/class="([^"]*)"/.exec(m[2]) || [, ""])[1]));
  }
  const views = [...els.values()].filter((e) => e.className.split(/\s+/).includes("view"));
  const timers = [];
  let now = 0, nextId = 1;
  const state = { routes, calls: [] };
  const ctx = {
    document: {
      querySelector: (s) => els.get(s.replace(/^#/, "")) || new El(s),
      querySelectorAll: (s) => (s === ".view" ? views : []),
      createElement: () => new El(),
      createElementNS: () => new El(),
      createTextNode: (t) => ({ nodeType: 3, textContent: String(t) }),
    },
    window: { scrollTo() {} },
    location: { hash },
    navigator: { clipboard: { writeText: async () => {} } },
    console,
    fetch: async (path, opts) => {
      state.calls.push(path);
      const body = state.routes(path.split("?")[0], opts);
      return { json: async () => body };
    },
    setTimeout: (fn, ms) => { const id = nextId++; timers.push({ id, at: now + (ms || 0), fn }); return id; },
    clearTimeout: (id) => { const i = timers.findIndex((t) => t.id === id); if (i >= 0) timers.splice(i, 1); },
  };
  vm.createContext(ctx);
  const settle = async () => { for (let i = 0; i < 25; i++) await new Promise((r) => setImmediate(r)); };
  const page = {
    state,
    el: (id) => els.get(id),
    visible: () => views.filter((v) => !v.hidden).map((v) => v.id).join(","),
    text: (id) => els.get(id).text(),
    settle,
    async start() { vm.runInContext(script, ctx); await settle(); },
    async click(id) { els.get(id).click(); await settle(); },
    async advance(ms) {
      const end = now + ms;
      for (;;) {
        timers.sort((a, b) => a.at - b.at);
        if (!timers.length || timers[0].at > end) break;
        const t = timers.shift(); now = Math.max(now, t.at); t.fn(); await settle();
      }
      now = end;
    },
  };
  return page;
}

const STATE = { token: "t", ram_gb: 16, gpu: "", vram_gb: 0, mode: "cpu", llama_server: true, serve_cmd: "serve-it", installed: "" };
const TOOLS = { tools: [{ id: "ollama", label: "Ollama", status: "installed", version: "0.5.1",
  evidence: [{ kind: "on-PATH", path: "/usr/bin/ollama" }], searched: [], hint: { install: "get it", start: "ollama serve" } },
  { id: "llama-cpp", label: "llama.cpp", status: "installed", version: "", evidence: [{ kind: "python-package", path: "python:llama-cpp-python" }],
    searched: [], hint: { install: "brew install llama.cpp", setup: "llama-server was not found" } }] };
const DOWNLOADING = { state: "downloading", title: "Qwen", done: 5, total: 10 };

function routes(job) {
  return (path) => {
    if (path === "/api/state") return STATE;
    if (path === "/api/progress") return job.current;
    if (path === "/api/tools") return TOOLS;
    return {};
  };
}

const scenarios = {
  async "opening the tools view during a download is not undone by progress polling"() {
    const job = { current: DOWNLOADING };
    const p = makePage({ routes: routes(job) });
    await p.start();
    if (p.visible() !== "v-install") return "after reload during a download expected v-install, got " + p.visible();
    await p.click("tools-btn");
    if (p.visible() !== "v-tools") return "tools view did not open: " + p.visible();
    await p.advance(3000);
    if (p.visible() !== "v-tools") return "polling switched the view to " + p.visible();
    await p.click("tools-back");
    if (p.visible() !== "v-install") return "Back should restore the running download, got " + p.visible();
  },

  async "a download that finishes while the tools view is open is shown after Back"() {
    const job = { current: DOWNLOADING };
    const p = makePage({ routes: routes(job) });
    await p.start();
    await p.click("tools-btn");
    job.current = { state: "done", title: "Qwen", bench: "ok", tps: 20 };
    await p.advance(2000);
    if (p.visible() !== "v-tools") return "the result replaced the tools view: " + p.visible();
    await p.click("tools-back");
    if (p.visible() !== "v-done") return "Back should show the finished job, got " + p.visible();
    if (!p.text("d-text").includes("Qwen is installed")) return "result text missing: " + p.text("d-text");
  },

  async "a download that fails while the tools view is open is shown after Back"() {
    const job = { current: DOWNLOADING };
    const p = makePage({ routes: routes(job) });
    await p.start();
    await p.click("tools-btn");
    job.current = { state: "error", error: "disk full" };
    await p.advance(2000);
    if (p.visible() !== "v-tools") return "the error replaced the tools view: " + p.visible();
    await p.click("tools-back");
    if (p.visible() !== "v-error" || !p.text("e-text").includes("disk full")) return "Back should show the error, got " + p.visible();
  },

  async "with no job, Back from the tools view returns to the first screen"() {
    const p = makePage({ routes: routes({ current: { state: "idle" } }) });
    await p.start();
    await p.click("tools-btn");
    if (p.visible() !== "v-tools") return "tools view did not open";
    await p.click("tools-back");
    if (p.visible() !== "v-use") return "expected v-use, got " + p.visible();
  },

  async "the /#tools link opens the tools view, even while a download is running"() {
    for (const current of [{ state: "idle" }, DOWNLOADING]) {
      const p = makePage({ hash: "#tools", routes: routes({ current }) });
      await p.start();
      await p.advance(2000);
      if (p.visible() !== "v-tools") return `state ${current.state}: expected v-tools, got ${p.visible()}`;
    }
  },

  async "a finished job that was dismissed does not come back through the tools view"() {
    const job = { current: { state: "done", title: "Qwen", bench: "ok", tps: 20 } };
    const p = makePage({ routes: routes(job) });
    await p.start();
    await p.click("again");                         // user clicked "Get another model"
    if (p.visible() !== "v-use") return "expected v-use after dismissing, got " + p.visible();
    await p.click("tools-btn");
    await p.click("tools-back");
    if (p.visible() !== "v-use") return "old result reappeared: " + p.visible();
  },

  async "each tool card shows a start command, or the missing setup step"() {
    const p = makePage({ routes: routes({ current: { state: "idle" } }) });
    await p.start();
    await p.click("tools-btn");
    const text = p.text("tools-list");
    if (!text.includes("Start it with: ollama serve")) return "start command missing: " + text;
    if (!text.includes("llama-server was not found")) return "setup step missing: " + text;
    if (text.includes("Start it with: undefined")) return "undefined leaked into the page";
  },
};

(async () => {
  let failed = 0;
  for (const [name, fn] of Object.entries(scenarios)) {
    let detail;
    try { detail = await fn(); } catch (e) { detail = "threw: " + (e && e.stack || e); }
    if (detail) failed++;
    console.log(JSON.stringify({ name, ok: !detail, detail: detail || "" }));
  }
  process.exit(failed ? 1 : 0);
})();
