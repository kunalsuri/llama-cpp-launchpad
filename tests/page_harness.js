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
      // A route may return a Promise (a slow server), {__reject} (the request fails) or {__badjson} (not JSON).
      const body = await state.routes(path.split("?")[0], opts, path);
      if (body && body.__reject) throw new TypeError(body.__reject);
      return { json: async () => { if (body && body.__badjson) throw new SyntaxError("Unexpected token <"); return body; } };
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
    // The n-th button (0-based) with this label, found anywhere under element `id`.
    button(id, label, n = 0) {
      const found = [];
      const walk = (e) => { if (e.handlers && e.handlers.click && e.text().includes(label)) found.push(e); (e.children || []).forEach(walk); };
      walk(els.get(id));
      return found[n];
    },
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
  async "a slow Hub search that finishes after the user chose something else is discarded"() {
    let release;
    const gate = new Promise((r) => (release = r));
    const model = (id, title) => ({ id, title, verdict: "smooth", where: "cpu", size_h: "1 GB", have: false, note: "" });
    const p = makePage({
      routes: (path, _o, full) => {
        if (path === "/api/state") return STATE;
        if (path === "/api/progress") return { state: "idle" };
        if (path === "/api/recommend") return { models: [full.includes("use=chat") ? model("c1", "Chat Model") : model("k1", "Code Model")] };
        if (path === "/api/more") return full.includes("use=chat") ? gate.then(() => ({ models: [model("s1", "Stale Hub Model")] })) : { models: [model("n1", "Fresh Hub Model")] };
        return {};
      },
    });
    await p.start();
    await p.click("tiles");                                    // no-op: the container itself
    p.button("tiles", "General chat").click(); await p.settle();
    if (p.visible() !== "v-pick") return "chat recommendations did not open: " + p.visible();
    await p.click("more-btn");                                 // search starts, answer is held back
    await p.click("back");                                     // "Change"
    p.button("tiles", "Writing code").click(); await p.settle();
    release(); await p.settle();
    if (p.text("others").includes("Stale Hub Model")) return "old search results were added to the new recommendations";
    if (p.el("more-wrap").hidden) return "the new selection lost its search button";
    await p.click("more-btn");
    if (!p.state.calls.some((c) => c.startsWith("/api/more?use=coding"))) return "search was blocked by the old request: " + p.state.calls.join(" ");
    if (!p.text("others").includes("Fresh Hub Model")) return "new search results missing: " + p.text("others");
  },

  async "a failed Hub search shows a message and can be tried again"() {
    let n = 0;
    const p = makePage({
      routes: (path) => {
        if (path === "/api/state") return STATE;
        if (path === "/api/progress") return { state: "idle" };
        if (path === "/api/recommend") return { models: [{ id: "c1", title: "Chat Model", verdict: "smooth", where: "cpu", size_h: "1 GB", have: false, note: "" }] };
        if (path === "/api/more") return ++n === 1 ? { __reject: "Failed to fetch" } : { models: [{ id: "h1", title: "Hub Model", verdict: "usable", where: "cpu", size_h: "2 GB", have: false, note: "" }] };
        return {};
      },
    });
    await p.start();
    p.button("tiles", "General chat").click(); await p.settle();
    await p.click("more-btn");
    if (p.visible() !== "v-pick") return "a failed search should stay on the picks, got " + p.visible();
    if (!/could not|couldn't|try again/i.test(p.text("others"))) return "no message after the failure: " + p.text("others");
    if (p.el("more-wrap").hidden) return "no way to search again";
    await p.click("more-btn");
    if (n !== 2) return "second search never ran (stuck busy): " + n;
    if (!p.text("others").includes("Hub Model")) return "results missing after retry";
  },

  async "a failed progress request does not stop the progress updates"() {
    for (const failure of [{ __reject: "Failed to fetch" }, { __badjson: true }]) {
      let calls = 0;
      const p = makePage({
        routes: (path) => {
          if (path === "/api/state") return STATE;
          if (path !== "/api/progress") return {};
          calls++;
          if (calls === 2) return failure;                 // 1 = page load, 2 = first poll
          return calls < 5 ? DOWNLOADING : { state: "done", title: "Qwen", bench: "ok", tps: 20 };
        },
      });
      await p.start();
      await p.advance(5000);
      if (p.visible() !== "v-done") return `after ${Object.keys(failure)[0]}: polling stopped, showing ${p.visible()} (${calls} requests)`;
    }
  },

  async "a server that stays unreachable ends in an error, not an endless wait"() {
    let calls = 0;
    const p = makePage({
      routes: (path) => {
        if (path === "/api/state") return STATE;
        if (path !== "/api/progress") return {};
        return ++calls === 1 ? DOWNLOADING : { __reject: "Failed to fetch" };
      },
    });
    await p.start();
    await p.advance(60000);
    if (p.visible() !== "v-error") return "expected v-error, got " + p.visible();
  },

  async "a failed start of the download and a failed page load both show an error"() {
    const rec = { models: [{ id: "c1", title: "Chat Model", verdict: "smooth", where: "cpu", size_h: "1 GB", have: false, note: "" }] };
    const p = makePage({
      routes: (path) => {
        if (path === "/api/state") return STATE;
        if (path === "/api/progress") return { state: "idle" };
        if (path === "/api/recommend") return rec;
        if (path === "/api/install") return { __reject: "Failed to fetch" };
        return {};
      },
    });
    await p.start();
    p.button("tiles", "General chat").click(); await p.settle();
    p.button("top", "Get this model").click(); await p.settle();
    if (p.visible() !== "v-error") return "install failure: expected v-error, got " + p.visible();
    const q = makePage({ routes: (path) => (path === "/api/state" ? { __reject: "Failed to fetch" } : {}) });
    await q.start();
    if (q.visible() !== "v-error") return "page load failure: expected v-error, got " + q.visible();
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
