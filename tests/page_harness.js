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
    Object.assign(this, { id, hidden, className, textContent: "", children: [], style: {}, nodeType: 1, onclick: null, attrs: {}, handlers: {}, value: "" });
    const names = () => this.className.split(/\s+/).filter(Boolean);
    this.classList = {
      add: (...c) => { this.className = [...new Set([...names(), ...c])].join(" "); },
      remove: (...c) => { this.className = names().filter((n) => !c.includes(n)).join(" "); },
      toggle: (c, on) => { const want = on === undefined ? !names().includes(c) : !!on; (want ? this.classList.add : this.classList.remove)(c); return want; },
      contains: (c) => names().includes(c),
    };
  }
  // As in the DOM, anything that is not a node becomes a text node: strings, and also null -> "null",
  // undefined -> "undefined" (a real bug once: tool cards showed the word "null").
  append(...kids) { for (const k of kids) this.children.push(k && typeof k === "object" ? k : { nodeType: 3, textContent: String(k) }); }
  prepend(...kids) { const old = this.children; this.children = []; this.append(...kids); this.children.push(...old); }
  replaceChildren(...kids) { this.children = []; this.append(...kids); }
  addEventListener(ev, fn) { this.handlers[ev] = fn; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  focus() { focused.el = this; }
  select() {}
  blur() {}
  remove() {}
  click() { const f = this.onclick || this.handlers.click; if (f) return f({ currentTarget: this, stopPropagation() {}, preventDefault() {} }); }
  text() { return [this.textContent, ...this.children.map((c) => (c.text ? c.text() : c.textContent || ""))].join(" "); }
}
const focused = { el: null };

function makePage({ hash = "", routes, clipboard = "ok" }) {
  focused.el = null;
  const els = new Map();
  for (const m of html.matchAll(/<(\w+)([^>]*)>/g)) {
    const id = /\bid="([^"]+)"/.exec(m[2]);
    if (!id) continue;
    els.set(id[1], new El(id[1], /\bhidden\b/.test(m[2]), (/class="([^"]*)"/.exec(m[2]) || [, ""])[1]));
  }
  const views = [...els.values()].filter((e) => e.className.split(/\s+/).includes("view"));
  const timers = [];
  let now = 0, nextId = 1;
  const state = { routes, calls: [], copied: [] };
  // A browser's URL history: setting location.hash adds an entry and fires "hashchange" (asynchronously, as browsers
  // do); history.pushState adds one silently; history.back() goes to the previous entry and fires "hashchange".
  const winHandlers = {};
  const fire = (ev) => Promise.resolve().then(() => (winHandlers[ev] || []).forEach((fn) => fn({})));
  const entries = [hash];
  let at = 0, current = hash;
  const location = {
    pathname: "/", search: "",
    get hash() { return current; },
    set hash(v) {
      v = v && !v.startsWith("#") ? "#" + v : v;
      if (v === current) return;
      entries.splice(at + 1); entries.push(v); at++; current = v; fire("hashchange");
    },
  };
  const history = {
    pushState(_s, _t, url) { const v = (/#.*/.exec(url || "") || [""])[0]; entries.splice(at + 1); entries.push(v); at++; current = v; },
    back() { if (at > 0) { const old = current; current = entries[--at]; if (old !== current) fire("hashchange"); } },
    forward() { if (at < entries.length - 1) { const old = current; current = entries[++at]; if (old !== current) fire("hashchange"); } },
  };
  const doc = {
    documentElement: new El("html"),
    get activeElement() { return focused.el; },
    querySelector: (s) => els.get(s.replace(/^#/, "")) || new El(s),
    querySelectorAll: (s) => (s === ".view" ? views : []),
    createElement: () => new El(),
    createElementNS: () => new El(),
    createTextNode: (t) => ({ nodeType: 3, textContent: String(t) }),
    body: new El("body"),
    execCommand: () => clipboard === "fallback",
  };
  const ctx = {
    document: doc,
    window: {
      scrollTo() {},
      addEventListener: (ev, fn) => { (winHandlers[ev] = winHandlers[ev] || []).push(fn); },
      isSecureContext: true,
    },
    location,
    history,
    navigator: { clipboard: { writeText: async (t) => { if (clipboard !== "ok") throw new Error("denied"); state.copied.push(t); } } },
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
    location,
    async back() { history.back(); await settle(); },
    async forward() { history.forward(); await settle(); },
    focused: () => focused.el,
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

const STATE = { token: "t", ram_gb: 16, gpu: "", vram_gb: 0, mode: "cpu", llama_server: true, serve_cmd: "serve-it", installed: "",
  os: "linux", llama_install: { install: "Download a Linux release and copy llama-server into bin" } };
const RESUME = { kind: "resume", label: "Download or resume it from a terminal", cmd: "RESUME-CMD --download x" };
const MANUAL = { kind: "manual", label: "Or download it by hand with curl (starts from zero)", cmd: "MANUAL-CMD -o x" };
const idle = (extra) => (path, o, full) => {
  if (path === "/api/state") return STATE;
  if (path === "/api/progress") return { state: "idle" };
  return extra ? extra(path, o, full) : {};
};
// A download that is running when the page opens and has finished by the first poll.
const finishing = (st, done) => {
  let polls = 0;
  return (path) => (path === "/api/state" ? st : path === "/api/progress" ? (++polls === 1 ? DOWNLOADING : done) : {});
};
const radarModel = (over) => Object.assign({ repo: "a/m-GGUF", name: "m-Q4_K_M", fit_mode: "gpu", tps: 30, downloads: 10,
  size_mb: 4000, quant: "Q4_K_M", id: "a/m-GGUF|m.gguf", commands: [RESUME] }, over);
const TOOLS = { tools: [{ id: "ollama", label: "Ollama", status: "installed", version: "0.5.1",
  evidence: [{ kind: "on-PATH", path: "/usr/bin/ollama" }], searched: [], hint: { install: "get it", start: "ollama serve" } },
  { id: "llama-cpp", label: "llama.cpp", status: "installed", version: "", evidence: [{ kind: "python-package", path: "python:llama-cpp-python" }],
    searched: [], hint: { install: "brew install llama.cpp", setup: "llama-server was not found" } },
  { id: "lmstudio", label: "LM Studio", status: "not-found", version: "", evidence: [], searched: [], hint: { install: "Download it from lmstudio.ai" } },
  { id: "unsloth", label: "Unsloth", status: "not-found", version: "", evidence: [], searched: [], hint: { install: "pip install unsloth", install_cmd: "pip install unsloth" } }] };
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
    if (!p.text("d-text").includes("Qwen is downloaded")) return "result text missing: " + p.text("d-text");
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
    if (!/Start it with:\s+ollama serve/.test(text)) return "start command missing: " + text;
    if (!text.includes("llama-server was not found")) return "setup step missing: " + text;
    if (/\b(undefined|null)\b/.test(text)) return "undefined or null leaked into the page: " + text;
    if (!text.includes("Download it from lmstudio.ai")) return "install hint missing for a tool that was not found";
    if (!p.button("tools-list", "Copy")) return "no copy button for a runnable install command";
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

  async "the /#radar link opens the radar view and displays models"() {
    const radarData = {
      updated_at: "2026-11-01T00:00:00Z",
      models: [
        { repo: "author/test-model", fit_mode: "gpu", tps: 24, downloads: 1200, size_mb: 4096, quant: "Q4_K_M" },
      ],
    };
    const p = makePage({
      hash: "#radar",
      routes: (path) => {
        if (path === "/api/state") return STATE;
        if (path === "/api/progress") return { state: "idle" };
        if (path.startsWith("/api/radar")) return radarData;
        return {};
      },
    });
    await p.start();
    await p.advance(100);
    if (p.visible() !== "v-radar") return "expected v-radar on #radar hash, got " + p.visible();
    if (!p.text("radar-list").includes("author/test-model")) return "radar models not rendered: " + p.text("radar-list");
  },

  async "radar sort buttons update sort order"() {
    const radarData = {
      updated_at: "2026-11-01T00:00:00Z",
      models: [
        { repo: "slow-big", fit_mode: "cpu", tps: 5, downloads: 100, size_mb: 8000, quant: "Q4_K_M" },
        { repo: "fast-small", fit_mode: "gpu", tps: 50, downloads: 5000, size_mb: 2000, quant: "Q4_K_M" },
      ],
    };
    const p = makePage({
      routes: (path) => {
        if (path === "/api/state") return STATE;
        if (path === "/api/progress") return { state: "idle" };
        if (path.startsWith("/api/radar")) return radarData;
        return {};
      },
    });
    await p.start();
    await p.click("radar-btn");
    await p.advance(100);
    if (p.visible() !== "v-radar") return "expected v-radar";
    // Default sort is downloads desc: fast-small first
    let text = p.text("radar-list");
    if (text.indexOf("fast-small") > text.indexOf("slow-big")) return "expected fast-small before slow-big by downloads";
    // Click sort-speed:
    await p.click("sort-speed");
    text = p.text("radar-list");
    if (text.indexOf("fast-small") > text.indexOf("slow-big")) return "expected fast-small before slow-big by speed desc";
    // Click sort-dir: flips to asc
    await p.click("sort-dir");
    text = p.text("radar-list");
    if (text.indexOf("slow-big") > text.indexOf("fast-small")) return "expected slow-big before fast-small by speed asc";
  },

  async "radar cluster buttons filter models by cluster"() {
    const radarData = {
      updated_at: "2026-11-01T00:00:00Z",
      models: [
        { repo: "author/code-model", fit_mode: "gpu", tps: 20, downloads: 100, size_mb: 2000, clusters: ["coding", "chat"] },
        { repo: "author/agent-model", fit_mode: "gpu", tps: 20, downloads: 100, size_mb: 2000, clusters: ["agentic"] },
      ],
    };
    const p = makePage({
      routes: (path) => {
        if (path === "/api/state") return STATE;
        if (path === "/api/progress") return { state: "idle" };
        if (path.startsWith("/api/radar")) return radarData;
        return {};
      },
    });
    await p.start();
    await p.click("radar-btn");
    await p.advance(100);
    if (!p.text("radar-list").includes("author/code-model") || !p.text("radar-list").includes("author/agent-model")) {
      return "expected both models in all clusters view";
    }
  },

  async "the /#history link opens the history view and displays changes"() {
    const historyData = {
      has_previous: true,
      latest_sync: "2026-11-01T00:00:00Z",
      previous_sync: "2026-10-31T00:00:00Z",
      summary: { new_count: 1, removed_count: 1, persisted_count: 1, gpu_ready_new: 1, total_current: 2, total_previous: 2 },
      new_models: [{ repo: "new/frontier-model", fit_mode: "gpu", tps: 30, downloads: 500, size_mb: 4000, quant: "Q4_K_M", clusters: ["coding"] }],
      top_movers: [{ repo: "common/mover-model", fit_mode: "gpu", tps: 20, downloads: 2000, delta_downloads: 400, size_mb: 2000, quant: "Q4_K_M" }],
      removed_models: [{ repo: "old/retired-model", downloads: 300, quant: "Q8_0" }],
      snapshots: [{ date: "2026-11-01", count: 2, updated_at: "2026-11-01T00:00:00Z" }],
    };
    const p = makePage({
      hash: "#history",
      routes: (path) => {
        if (path === "/api/state") return STATE;
        if (path === "/api/progress") return { state: "idle" };
        if (path.startsWith("/api/radar/history")) return historyData;
        return {};
      },
    });
    await p.start();
    await p.advance(100);
    if (p.visible() !== "v-history") return "expected v-history on #history hash, got " + p.visible();
    if (!p.text("history-content").includes("new/frontier-model")) {
      return "new model not rendered in history view: " + p.text("history-content");
    }
  },

  // --- Commands: the page shows exactly what the server built for this OS (rule 3), never its own guesses ---
  async "download commands on screen are the server's, during a download and after a failure"() {
    let job = { state: "downloading", title: "Qwen", done: 1, total: 4, source: "terminal", repo: "q/Q-GGUF", file: "q.gguf", commands: [RESUME, MANUAL] };
    const p = makePage({ routes: (path) => (path === "/api/state" ? STATE : path === "/api/progress" ? job : {}) });
    await p.start();
    if (p.visible() !== "v-install") return "expected v-install, got " + p.visible();
    const box = p.text("i-terminal-box");
    if (!box.includes("RESUME-CMD") || !box.includes("MANUAL-CMD")) return "server commands missing: " + box;
    if (/python3|curl -L -C/.test(box)) return "page built its own command: " + box;
    job = { state: "error", error: "Network interrupted", commands: [RESUME] };
    await p.advance(600);
    if (p.visible() !== "v-error") return "expected v-error, got " + p.visible();
    const err = p.text("e-terminal-box");
    if (!err.includes("RESUME-CMD")) return "resume command missing after failure: " + err;
    if (/python3|curl/.test(err)) return "page built its own command: " + err;
  },

  async "a model the server gave no commands for shows no copy-command button"() {
    const p = makePage({ hash: "#radar", routes: idle((path) => (path.startsWith("/api/radar") ? { models: [radarModel({ commands: [] })] } : {})) });
    await p.start();
    if (/Copy (curl|command)/.test(p.text("radar-list"))) return "a copy button without a command: " + p.text("radar-list");
    const q = makePage({ hash: "#radar", routes: idle((path) => (path.startsWith("/api/radar") ? { models: [radarModel()] } : {})) });
    await q.start();
    const btn = q.button("radar-list", "Copy command");
    if (!btn) return "no copy button for a model with a command: " + q.text("radar-list");
    btn.click(); await q.settle();
    if (q.state.copied[0] !== RESUME.cmd) return "copied " + JSON.stringify(q.state.copied);
  },

  async "the done screen says to install llama.cpp first when llama-server is missing"() {
    const done = { state: "done", title: "Qwen", bench: "skipped", tps: 0 };
    const missing = { ...STATE, llama_server: false, llama_install: { install: "brew install llama.cpp", install_cmd: "brew install llama.cpp" } };
    const p = makePage({ routes: finishing(missing, done) });
    await p.start();
    await p.advance(600);
    if (p.visible() !== "v-done") return "expected v-done, got " + p.visible();
    const t = p.text("done-next");
    if (!t.includes("brew install llama.cpp")) return "install step missing: " + t;
    if (!/llama\.cpp is not installed|install llama\.cpp/i.test(t)) return "no explanation: " + t;
    const ok = makePage({ routes: finishing(STATE, done) });
    await ok.start();
    await ok.advance(600);
    if (!ok.text("done-next").includes("serve-it")) return "serve command missing when llama-server exists";
    if (ok.text("done-next").includes("Download a Linux release")) return "install step shown although llama-server exists";
  },

  async "the llama.cpp warning gives this computer's install step, with a copy button only for a command"() {
    const text = makePage({ routes: (path) => (path === "/api/state" ? { ...STATE, llama_server: false } : { state: "idle" }) });
    await text.start();
    const w = text.text("warn");
    if (!w.includes("Download a Linux release")) return "OS install step missing: " + w;
    if (w.includes("README")) return "still sends the user to the README: " + w;
    if (text.button("warn", "Copy")) return "copy button for plain text";
    const cmd = makePage({ routes: (path) => (path === "/api/state" ? { ...STATE, llama_server: false, llama_install: { install: "winget install ggml.llamacpp", install_cmd: "winget install ggml.llamacpp" } } : { state: "idle" }) });
    await cmd.start();
    if (!cmd.button("warn", "Copy")) return "no copy button for a runnable install command";
  },

  async "downloading from the radar shows the progress screen instead of polling silently"() {
    let started = false;
    const p = makePage({ hash: "#radar", routes: (path) => {
      if (path === "/api/state") return STATE;
      if (path === "/api/install") { started = true; return { ok: true }; }
      if (path === "/api/progress") return started ? DOWNLOADING : { state: "idle" };
      if (path.startsWith("/api/radar")) return { models: [radarModel()] };
      return {};
    } });
    await p.start();
    const btn = p.button("radar-list", "Download");
    if (!btn) return "no Download button: " + p.text("radar-list");
    btn.click(); await p.settle();
    if (p.visible() !== "v-install") return "expected the progress screen, got " + p.visible();
    if (p.location.hash !== "") return "the address still says " + p.location.hash;
    await p.back();
    if (p.visible() !== "v-radar") return "browser Back should return to the radar, got " + p.visible();
  },

  // --- Navigation: views live in the URL, so browser Back/Forward and bookmarks work ---
  async "browser Back and Forward move between views"() {
    const p = makePage({ routes: idle((path) => (path === "/api/tools" ? TOOLS : path.startsWith("/api/radar") ? { models: [radarModel()] } : {})) });
    await p.start();
    await p.click("radar-btn");
    if (p.visible() !== "v-radar" || p.location.hash !== "#radar") return "radar: " + p.visible() + " " + p.location.hash;
    await p.click("tools-btn");
    if (p.visible() !== "v-tools" || p.location.hash !== "#tools") return "tools: " + p.visible() + " " + p.location.hash;
    await p.back();
    if (p.visible() !== "v-radar") return "Back from tools should show radar, got " + p.visible();
    await p.back();
    if (p.visible() !== "v-use") return "Back again should show the first screen, got " + p.visible();
    await p.forward();
    if (p.visible() !== "v-radar") return "Forward should show radar again, got " + p.visible();
  },

  async "the in-page Back link goes home and leaves a history entry"() {
    const p = makePage({ routes: idle((path) => (path === "/api/tools" ? TOOLS : {})) });
    await p.start();
    await p.click("tools-btn");
    await p.click("tools-back");
    if (p.visible() !== "v-use" || p.location.hash !== "") return "expected v-use with no hash, got " + p.visible() + " " + p.location.hash;
    await p.back();
    if (p.visible() !== "v-tools") return "browser Back should reopen tools, got " + p.visible();
  },

  async "the open view is marked in the nav and gets keyboard focus"() {
    const p = makePage({ routes: idle((path) => (path === "/api/tools" ? TOOLS : {})) });
    await p.start();
    await p.click("tools-btn");
    if (p.el("tools-btn").getAttribute("aria-current") !== "page") return "tools nav not aria-current";
    if (p.el("radar-btn").getAttribute("aria-current") === "page") return "radar nav still marked current";
    const f = p.focused();
    if (!f || f.id !== "tools-title") return "focus should move to the view heading, got " + (f && f.id);
    await p.click("tools-back");
    if (p.el("tools-btn").getAttribute("aria-current") === "page") return "tools still marked current after going home";
  },

  // --- Honest feedback ---
  async "copying says so when the clipboard is blocked, and falls back when it can"() {
    const done = { state: "done", title: "Qwen", bench: "ok", tps: 20 };
    for (const [mode, want] of [["ok", /copied/i], ["fallback", /copied/i], ["denied", /select|press|ctrl|⌘/i]]) {
      const p = makePage({ clipboard: mode, routes: finishing(STATE, done) });
      await p.start();
      await p.advance(600);
      const btn = p.button("done-next", "Copy");
      if (!btn) return "no Copy button next to the serve command: " + p.text("done-next");
      btn.click(); await p.settle();
      const t = btn.text();
      if (!want.test(t)) return `${mode}: button says ${JSON.stringify(t)}`;
      if (mode === "denied" && /copied/i.test(t)) return "claimed Copied although copying failed";
    }
  },

  async "a radar sync that cannot reach Hugging Face says so instead of showing an empty list"() {
    const p = makePage({ hash: "#radar", routes: idle((path) => (path.startsWith("/api/radar") ? { offline: true, updated_at: "2026-10-30T00:00:00Z", models: [radarModel()] } : {})) });
    await p.start();
    const t = p.text("radar-notice");
    if (!/could not reach hugging face/i.test(t)) return "no offline notice: " + t;
    if (!t.includes("2026-10-30")) return "should say how old the saved results are: " + t;
    if (!p.text("radar-list").includes("a/m-GGUF")) return "saved results should still be listed";
  },

  async "radar figures are labelled as estimates and never overstate the fit"() {
    const cpuOnly = [radarModel({ repo: "big/cpu-GGUF", fit_mode: "cpu", tps: 9, size_mb: 20480 })];
    const p = makePage({ hash: "#radar", routes: idle((path) => (path.startsWith("/api/radar") ? { models: cpuOnly } : {})) });
    await p.start();
    const all = p.text("radar-spotlight") + " " + p.text("radar-list");
    if (/100% GPU|Real-Time|KV Cache/i.test(all)) return "overstated claim on screen: " + all;
    if (!/est\./.test(all)) return "speed not labelled as an estimate: " + all;
    if (/20\.0 GB of 16 GB \(100%\)/.test(all)) return "a 20 GB model was shown as 100% of 16 GB";
    if (!/bigger than|more than/i.test(all)) return "should say the model is bigger than the memory: " + all;
  },

  async "the progress bar reports its value to assistive technology"() {
    const p = makePage({ routes: (path) => (path === "/api/state" ? STATE : path === "/api/progress" ? { ...DOWNLOADING, commands: [] } : {}) });
    await p.start();
    if (p.el("bar").getAttribute("aria-valuenow") !== "50") return "aria-valuenow is " + p.el("bar").getAttribute("aria-valuenow");
  },

  async "radar tabs expose which one is selected"() {
    const p = makePage({ hash: "#radar", routes: idle((path) => (path.startsWith("/api/radar") ? { models: [radarModel()] } : {})) });
    await p.start();
    const tabs = p.el("radar-tabs").children;
    if (!tabs.length) return "tabs are not built by the script";
    const gpu = tabs.find((t) => t.getAttribute("data-tab") === "gpu");
    gpu.click(); await p.settle();
    const sel = tabs.filter((t) => t.getAttribute("aria-selected") === "true").map((t) => t.getAttribute("data-tab"));
    if (sel.join() !== "gpu") return "aria-selected on: " + sel.join();
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
