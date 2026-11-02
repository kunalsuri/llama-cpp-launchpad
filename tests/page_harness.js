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

// Start chatting: a finished download of model "o/M-GGUF|m.gguf", and the chat's states as the server reports them.
const PREVIEW = { cmd: "llama-server -m /p/models/m.gguf --port 8080", port: 8080, busy: null };
const IDLE_CHAT = { state: "idle", log: [] };
const mem = (need, where, extra) => Object.assign({ need_mb: need, kv_mb: 512, ctx: 4096, bound: "exact", where, note: "" }, extra);
const PRESET_PREVIEW = { ...PREVIEW, cmd: "CMD-AUTO", preset: "auto", presets: [
  { id: "short", label: "Short chats", text: "About 3,000 words.", available: true, why: "", cmd: "CMD-SHORT", memory: mem(5734, "gpu") },
  { id: "long", label: "Long documents", text: "About 24,000 words.", available: true, why: "", cmd: "CMD-LONG", memory: mem(9000, "cpu") },
  { id: "fast", label: "Fastest replies", text: "All on the card.", available: false, why: "This needs a graphics card that llama.cpp can use, and none was found.", memory: mem(5000, "gpu") },
  { id: "auto", label: "Let llama.cpp decide", text: "llama.cpp picks.", available: true, why: "", cmd: "CMD-AUTO", memory: mem(40000, "no", { note: "whole trained context" }) }] };
const STARTING = { state: "starting", cmd: PREVIEW.cmd, port: 8080, url: "http://127.0.0.1:8080/", model: "M", log: ["loading"] };
const RUNNING = { ...STARTING, state: "running" };
const STOPPED = { ...STARTING, state: "stopped" };
function chatRoutes({ state = STATE, progress, chats, preview = PREVIEW, posts = [], start = STARTING, stop = STOPPED }) {
  let i = 0;
  const done = progress || { state: "done", id: "o/M-GGUF|m.gguf", title: "M", bench: "ok", tps: 20 };
  let polls = 0;
  return (path, opts, full) => {
    if (path === "/api/state") return state;
    if (path === "/api/progress") return progress ? done : (++polls === 1 ? DOWNLOADING : done);
    if (path === "/api/chat" && opts && opts.method === "POST") return {};
    if (path === "/api/chat") {
      const chat = chats[Math.min(i++, chats.length - 1)];
      return full.includes("id=") ? { chat, preview } : { chat };
    }
    if (path === "/api/chat/start" || path === "/api/chat/stop") {
      posts.push({ path, body: JSON.parse(opts.body) });
      i = Math.max(i, 1);
      return path === "/api/chat/start" ? start : stop;
    }
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

  async "the done screen has no stray text on any OS when llama.cpp is installed"() {
    // Review finding: on Linux the optional double-click tip is undefined and replaceChildren(..., null) printed "null".
    const done = { state: "done", title: "Qwen", bench: "ok", tps: 20 };
    for (const os of ["linux", "mac", "windows"]) {
      const p = makePage({ routes: finishing({ ...STATE, os }, done) });
      await p.start();
      await p.advance(600);
      const t = p.text("done-next");
      if (/\b(null|undefined)\b/.test(t)) return `${os}: stray text on the done screen: ${t}`;
      if (os !== "linux" && !/double-click/.test(t)) return `${os}: the double-click tip is missing: ${t}`;
    }
  },

  async "Details opens on the cards of the What changed view too"() {
    // Review finding: the toggle re-rendered only the (hidden) radar list, so history cards never opened.
    const hist = { summary: { new_count: 1 }, new_models: [radarModel({ repo: "new/x-GGUF", file: "x.gguf" })], top_movers: [], removed_models: [], snapshots: [] };
    const p = makePage({ hash: "#history", routes: idle((path) => (path.startsWith("/api/radar/history") ? hist : {})) });
    await p.start();
    const btn = p.button("history-content", "Details");
    if (!btn) return "no Details button: " + p.text("history-content");
    btn.click(); await p.settle();
    const t = p.text("history-content");
    if (!t.includes("Repository") || !t.includes("x.gguf")) return "details did not open in the history view: " + t;
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

  // --- Image support (a vision projector) on the done screen --------------------------------------------------
  async "image support is offered, downloads with progress, then the chat command loads it"() {
    const posts = [];
    let vis = { have: false, flag: true, file: "", available: { file: "mmproj-model-f16.gguf", size: 851443712 }, why: "", job: { state: "idle" } };
    const base = chatRoutes({ chats: [IDLE_CHAT], preview: PRESET_PREVIEW });
    const chatCalls = [];
    const p = makePage({ routes: (path, opts, full) => {
      if (path === "/api/vision") return vis;
      if (path === "/api/vision/get") {
        posts.push(JSON.parse(opts.body));
        vis = { ...vis, job: { state: "downloading", done: 425721856, total: 851443712 } };
        return { ok: true };
      }
      if (path === "/api/chat" && full.includes("id=")) chatCalls.push(full);
      return base(path, opts, full);
    } });
    await p.start();
    await p.advance(1000);
    const btn = p.button("vision-box", "Add image support");
    if (!btn) return "no button to add image support: " + p.text("vision-box");
    if (!p.text("vision-box").includes("812 MB")) return "the download size is not shown: " + p.text("vision-box");
    btn.click(); await p.settle();
    if (posts.length !== 1 || posts[0].id !== "o/M-GGUF|m.gguf") return "the request was not sent: " + JSON.stringify(posts);
    await p.advance(1100);
    if (!p.text("vision-box").includes("50%")) return "no progress: " + p.text("vision-box");
    const before = chatCalls.length;
    vis = { ...vis, have: true, file: "mmproj-model-f16.gguf", available: null, job: { state: "done", file: "mmproj-model-f16.gguf" } };
    await p.advance(1100);
    if (!/Image support is on/.test(p.text("vision-box"))) return "not shown as on: " + p.text("vision-box");
    if (chatCalls.length === before) return "the chat command was not asked for again (it must now include --mmproj)";
    const n = chatCalls.length;
    await p.advance(5000);
    if (chatCalls.length !== n) return "kept polling after the download finished";
  },

  async "a model that does not read images shows no image box"() {
    const vis = { have: false, flag: true, file: "", available: null, why: "This model does not read images.", job: { state: "idle" } };
    const base = chatRoutes({ chats: [IDLE_CHAT], preview: PRESET_PREVIEW });
    const p = makePage({ routes: (path, opts, full) => (path === "/api/vision" ? vis : base(path, opts, full)) });
    await p.start();
    await p.advance(1000);
    if (!p.el("vision-box").hidden) return "a box is shown for a text-only model: " + p.text("vision-box");
  },

  // --- My models: the models folder, and deleting with a second click -------------------------------------------
  async "My models lists the folder and deletes only after a second, explicit click"() {
    const posts = [];
    const list = { dir: "/p/models", total: 3e9, free: 50e9, models: [
      { id: "shape.gguf", kind: "model", size: 2.6e9, repo: "o/Shape-GGUF", files: ["shape.gguf"], arch: "llama", layers: 32, train_ctx: 131072, header_error: "" },
      { id: "x.gguf.part", kind: "partial", size: 4e8, repo: "", files: ["x.gguf.part"], header_error: "" }] };
    const after = { ...list, models: [list.models[1]], removed: ["shape.gguf"] };
    const p = makePage({ hash: "#models", routes: idle((path, opts) => {
      if (path === "/api/models") return list;
      if (path === "/api/models/delete") { posts.push(JSON.parse(opts.body)); return after; }
      return {};
    }) });
    await p.start();
    if (p.visible() !== "v-models") return "the /#models link did not open My models: " + p.visible();
    const t = p.text("models-list");
    for (const want of ["shape.gguf", "o/Shape-GGUF", "2.4 GB", "llama", "32 layers", "Unfinished download"])
      if (!t.includes(want)) return `missing "${want}": ` + t;
    if (!p.text("models-sum").includes("46.6 GB free")) return "free space not shown: " + p.text("models-sum");
    p.button("models-list", "Delete").click(); await p.settle();
    if (posts.length) return "deleted on the first click";
    if (!p.text("models-list").includes("Delete shape.gguf (2.4 GB)?")) return "no confirmation: " + p.text("models-list");
    p.button("models-list", "Cancel").click(); await p.settle();
    if (posts.length || p.text("models-list").includes("Delete shape.gguf (2.4 GB)?")) return "Cancel did not cancel";
    p.button("models-list", "Delete").click(); await p.settle();
    p.button("models-list", "Yes, delete").click(); await p.settle();
    if (posts.length !== 1 || posts[0].id !== "shape.gguf") return "the delete was not sent once with the id: " + JSON.stringify(posts);
    if (p.text("models-list").includes("o/Shape-GGUF")) return "the list was not refreshed: " + p.text("models-list");
  },

  async "a refused delete says why and keeps the model"() {
    const list = { dir: "/p/models", total: 1, free: 1, models: [{ id: "a.gguf", kind: "model", size: 1e9, repo: "", files: ["a.gguf"], header_error: "" }] };
    const p = makePage({ hash: "#models", routes: idle((path) => (path === "/api/models" ? list
      : path === "/api/models/delete" ? { error: "The chat is using this model. Stop the chat first, then delete it." } : {})) });
    await p.start();
    p.button("models-list", "Delete").click(); await p.settle();
    p.button("models-list", "Yes, delete").click(); await p.settle();
    const t = p.text("models-list");
    if (!t.includes("Stop the chat first") || !t.includes("a.gguf")) return "the reason is not shown: " + t;
  },

  // --- Plain-language explanations next to the choice they affect ----------------------------------------------
  async "the recommended model explains its quantization, size and speed in plain words"() {
    const rec = (quant, tps) => ({ models: [{ id: "a|m.gguf", title: "Qwen3-4B", repo: "a/Qwen3-4B-GGUF", quant, verdict: "smooth",
      where: "gpu", size: 2.4e9, size_h: "2.4 GB", tps, have: false, note: "", commands: [] }] });
    const texts = {};
    for (const [quant, tps] of [["Q4_K_M", 40], ["Q8_0", 20], ["IQ2_XS", 60], ["", 3]]) {
      const p = makePage({ routes: idle((path) => (path === "/api/recommend" ? rec(quant, tps) : {})) });
      await p.start();
      p.button("tiles", "General chat").click(); await p.settle();
      if (p.visible() !== "v-pick") return "the pick view did not open: " + p.visible();
      texts[quant] = p.text("top");
      if (!texts[quant].includes("What do these mean?")) return quant + ": no explanation on the card: " + texts[quant];
    }
    if (!/4-bit/.test(texts.Q4_K_M) || !/balance/.test(texts.Q4_K_M)) return "Q4_K_M is not explained: " + texts.Q4_K_M;
    if (!/8-bit/.test(texts.Q8_0) || !/twice/.test(texts.Q8_0)) return "Q8_0 is not explained: " + texts.Q8_0;
    if (!/noticeably worse/.test(texts.IQ2_XS)) return "a 2-bit model does not warn about quality: " + texts.IQ2_XS;
    if (!/about 30 words a second/.test(texts.Q4_K_M)) return "40 tokens/s is not put in words: " + texts.Q4_K_M;
    if (!/slower than you read/.test(texts[""])) return "3 tokens/s is not compared with reading: " + texts[""];
    if (!/faster than most people read/.test(texts.Q8_0)) return "20 tokens/s is not compared with reading: " + texts.Q8_0;
    if (/\b(null|undefined)\b/.test(texts[""])) return "a model without a quantization shows stray text: " + texts[""];
    const exact = makePage({ routes: idle((path) => (path === "/api/recommend"
      ? { models: [{ ...rec("Q4_K_M", 40).models[0], need_mb: 3584, memory_from: "header" }] } : {})) });
    await exact.start();
    exact.button("tiles", "General chat").click(); await exact.settle();
    if (!/about 3\.5 GB of memory to run \(worked out from the model file itself\)/.test(exact.text("top"))) return "exact memory not explained: " + exact.text("top");
  },

  // --- A slow speed test explains itself ----------------------------------------------------------------------
  async "a slow speed test shows why it was slow and what to do"() {
    const done = { state: "done", id: "o/M-GGUF|m.gguf", title: "M", bench: "ok", tps: 3,
      speed_notes: [{ code: "gpu_unused", text: "cannot use your graphics card (RTX)", fix: "Get llama.cpp offers a build" }] };
    const state = { ...STATE, llama: { offer: { how: "download", label: "CUDA build" } } };
    const p = makePage({ routes: finishing(state, done) });
    await p.start();
    await p.advance(1000);
    const t = p.text("speed-notes");
    if (!t.includes("Why it is slow") || !t.includes("cannot use your graphics card") || !t.includes("Get llama.cpp offers a build"))
      return "the reasons are not shown: " + t;
    if (!p.button("speed-notes", "Get a build that uses it")) return "no way to act on a graphics card that is not used";
    const fast = makePage({ routes: finishing(state, { ...done, tps: 40, speed_notes: [] }) });
    await fast.start();
    await fast.advance(1000);
    if (fast.text("speed-notes").includes("Why it is slow")) return "a fast run still explains slowness";
    if (!fast.el("speed-notes").hidden) return "an empty reasons box is shown";
  },

  // --- Settings presets on the done screen ----------------------------------------------------------------------
  async "the done screen offers presets with their memory, and Start sends the one picked"() {
    const posts = [];
    const p = makePage({ routes: chatRoutes({ chats: [IDLE_CHAT], preview: PRESET_PREVIEW, posts }) });
    await p.start();
    await p.advance(1000);
    const t = p.text("done-next");
    for (const want of ["Short chats", "Long documents", "Needs about 5.6 GB", "fits your graphics card", "too big for this computer"])
      if (!t.includes(want)) return `missing "${want}": ` + t;
    if (!t.includes("CMD-AUTO")) return "the default preset's command is not shown: " + t;
    const long = p.button("done-next", "Long documents");
    if (!long) return "no button for Long documents";
    long.click(); await p.settle();
    if (!p.text("done-next").includes("CMD-LONG")) return "picking a preset did not show its command: " + p.text("done-next");
    if (long.getAttribute("aria-pressed") !== "true" && !findEl(p.el("done-next"), (e) => e.attrs && e.attrs["aria-pressed"] === "true" && e.text().includes("Long documents")))
      return "the picked preset is not marked as pressed";
    p.button("done-next", "Start chatting").click(); await p.settle();
    const start = posts.find((x) => x.path === "/api/chat/start");
    if (!start || start.body.preset !== "long") return "Start did not send the picked preset: " + JSON.stringify(posts);
  },

  async "a preset this llama-server cannot run shows why and cannot be picked"() {
    const p = makePage({ routes: chatRoutes({ chats: [IDLE_CHAT], preview: PRESET_PREVIEW }) });
    await p.start();
    await p.advance(1000);
    const t = p.text("done-next");
    if (!t.includes("needs a graphics card")) return "the reason is not shown: " + t;
    if (p.button("done-next", "Fastest replies")) return "an unavailable preset can still be clicked";
  },

  async "typing a context length asks the server for that command"() {
    const calls = [];
    const routes = chatRoutes({ chats: [IDLE_CHAT], preview: PRESET_PREVIEW });
    const p = makePage({ routes: (path, opts, full) => { if (path === "/api/chat") calls.push(full); return routes(path, opts, full); } });
    await p.start();
    await p.advance(1000);
    const input = findEl(p.el("done-next"), (e) => e.attrs && e.attrs.type === "number");
    if (!input) return "no context length field";
    input.value = "12000";
    const apply = p.button("done-next", "Use this length");
    if (!apply) return "no button to apply the length";
    apply.click(); await p.settle();
    if (!calls.some((c) => /[?&]ctx=12000\b/.test(c))) return "the server was not asked: " + calls.join(" ");
  },

  // --- Start chatting ------------------------------------------------------------------------------------------
  async "the done screen offers Start chatting and shows the exact command it will run"() {
    const p = makePage({ routes: chatRoutes({ chats: [IDLE_CHAT] }) });
    await p.start();
    await p.advance(1000);
    if (p.visible() !== "v-done") return "expected the done screen, got " + p.visible();
    if (!p.button("done-next", "Start chatting")) return "no Start chatting button: " + p.text("done-next");
    if (!p.text("done-next").includes(PREVIEW.cmd)) return "the command it runs is not shown: " + p.text("done-next");
    if (/\b(null|undefined)\b/.test(p.text("done-next"))) return "null or undefined on screen (Linux has no double-click tip): " + p.text("done-next");
    if (!p.state.calls.includes("/api/chat?id=" + encodeURIComponent("o/M-GGUF|m.gguf"))) return "did not ask about this model: " + p.state.calls.join(" ");
  },

  async "without llama-server there is no Start chatting button, only what is missing"() {
    const st = { ...STATE, llama_server: false };
    const p = makePage({ routes: chatRoutes({ state: st, chats: [IDLE_CHAT] }) });
    await p.start();
    await p.advance(1000);
    if (p.button("done-next", "Start chatting")) return "a Start chatting button was shown without llama-server";
    if (!/llama\.cpp is not installed/.test(p.text("done-next"))) return "missing piece not named: " + p.text("done-next");
  },

  async "Start chatting goes starting -> running, links to the chat, and Stop stops it"() {
    const posts = [];
    const p = makePage({ routes: chatRoutes({ posts, chats: [IDLE_CHAT, STARTING, STARTING, RUNNING, RUNNING, STOPPED],
      start: STARTING, stop: STOPPED }) });
    await p.start();
    await p.advance(1000);
    p.button("done-next", "Start chatting").click(); await p.settle();
    if (posts[0].path !== "/api/chat/start" || posts[0].body.id !== "o/M-GGUF|m.gguf") return "start request: " + JSON.stringify(posts);
    if (!/Starting/.test(p.text("chat-box"))) return "no starting state: " + p.text("chat-box");
    if (!p.button("chat-box", "Stop")) return "no Stop while starting";
    await p.advance(3000);
    const box = p.el("chat-box");
    if (!/running/i.test(p.text("chat-box"))) return "never showed running: " + p.text("chat-box");
    const link = findEl(box, (e) => e.getAttribute && e.getAttribute("href") === RUNNING.url);
    if (!link || !/Open the chat/.test(link.text())) return "no link to the chat at " + RUNNING.url;
    if (link.getAttribute("rel") !== "noopener noreferrer") return "chat link must not get access to this page";
    p.button("chat-box", "Stop").click(); await p.settle();
    if (posts[posts.length - 1].path !== "/api/chat/stop") return "Stop did not ask the server: " + JSON.stringify(posts);
    if (!/stopped/i.test(p.text("chat-box"))) return "not shown as stopped: " + p.text("chat-box");
    if (!p.button("chat-box", "Start chatting")) return "cannot start again after stopping";
  },

  async "a failed start shows why and llama-server's own output"() {
    const failed = { state: "failed", error: "llama-server stopped before it was ready (exit code 1).", cmd: PREVIEW.cmd,
      log: ["fake llama-server args", "error: failed to load model 'm.gguf'"], model: "M" };
    const p = makePage({ routes: chatRoutes({ chats: [IDLE_CHAT, STARTING, failed], start: STARTING }) });
    await p.start();
    await p.advance(1000);
    p.button("done-next", "Start chatting").click(); await p.settle();
    await p.advance(3000);
    const t = p.text("chat-box");
    if (!t.includes("exit code 1")) return "no reason: " + t;
    if (!t.includes("failed to load model")) return "no log: " + t;
    if (!p.button("chat-box", "Try again")) return "no way to try again";
  },

  async "a busy port says what is using it and offers the next free port"() {
    const posts = [];
    const busy = { ...PREVIEW, busy: { port: 8080, used_by: "Docker Desktop.exe (process 5150)", free_port: 8081,
      looked: ["HTTP on 127.0.0.1:8080: no answer over HTTP", "netstat: process 5150 listens on 8080"] } };
    const p = makePage({ routes: chatRoutes({ posts, preview: busy, chats: [IDLE_CHAT, STARTING], start: STARTING }) });
    await p.start();
    await p.advance(1000);
    const t = p.text("done-next");
    if (!t.includes("Port 8080 is in use by Docker Desktop.exe (process 5150)")) return "does not say who uses the port: " + t;
    if (p.button("done-next", "Start chatting")) return "offered to start on the busy port";
    const alt = p.button("done-next", "Start on port 8081");
    if (!alt) return "next free port not offered: " + t;
    alt.click(); await p.settle();
    if (posts[0].body.port !== 8081) return "did not start on 8081: " + JSON.stringify(posts);
  },

  async "a start refused by the server shows its message instead of hanging"() {
    const refused = { error: "Port 8080 is already in use by ollama (process 7). Port 8081 is free.",
      port_busy: { port: 8080, used_by: "ollama (process 7)", free_port: 8081, looked: [] } };
    const p = makePage({ routes: chatRoutes({ chats: [IDLE_CHAT], start: refused }) });
    await p.start();
    await p.advance(1000);
    p.button("done-next", "Start chatting").click(); await p.settle();
    const t = p.text("chat-box");
    if (!t.includes("already in use by ollama")) return "refusal not shown: " + t;
    if (!p.button("chat-box", "Start on port 8081")) return "next free port not offered after refusal: " + t;
  },

  async "leaving the done screen stops asking about the chat"() {
    const p = makePage({ routes: chatRoutes({ chats: [IDLE_CHAT, STARTING, RUNNING], start: STARTING }) });
    await p.start();
    await p.advance(1000);
    p.button("done-next", "Start chatting").click(); await p.settle();
    await p.advance(2000);
    await p.click("tools-btn");
    const before = p.state.calls.filter((c) => c.startsWith("/api/chat")).length;
    await p.advance(20000);
    const after = p.state.calls.filter((c) => c.startsWith("/api/chat")).length;
    if (after !== before) return `kept polling the chat from another view: ${after - before} requests`;
  },

  async "a chat started on the done screen is offered on the first screen after Get another model"() {
    // Regression (review on #3): the done screen did not update S.chat, so the first screen showed no Open/Stop.
    const p = makePage({ routes: chatRoutes({ chats: [IDLE_CHAT, STARTING, RUNNING], start: STARTING }) });
    await p.start();
    await p.advance(1000);
    p.button("done-next", "Start chatting").click(); await p.settle();
    await p.advance(3000);
    if (!/running/i.test(p.text("chat-box"))) return "chat never ran: " + p.text("chat-box");
    await p.click("again");
    if (p.visible() !== "v-use") return "expected the first screen, got " + p.visible();
    const link = findEl(p.el("warn"), (e) => e.getAttribute && e.getAttribute("href") === RUNNING.url);
    if (!link) return "the running chat is not offered on the first screen: " + p.text("warn");
    if (!p.button("warn", "Stop")) return "no Stop on the first screen";
  },

  async "polling a running chat keeps its controls, an opened output panel, and does not repeat the announcement"() {
    // Regression (review on #3): every poll rebuilt the panel, dropping keyboard focus on Open/Stop and closing the
    // output the user had opened, and re-announced "running" to screen readers every 3 seconds.
    const running = { ...RUNNING, log: ["line 1"] };
    const later = { ...RUNNING, log: ["line 1", "line 2"] };
    const p = makePage({ routes: chatRoutes({ chats: [IDLE_CHAT, STARTING, running, later, later, later], start: STARTING }) });
    await p.start();
    await p.advance(1000);
    p.button("done-next", "Start chatting").click(); await p.settle();
    await p.advance(2000);
    const stop = p.button("chat-box", "Stop");
    const details = findEl(p.el("chat-box"), (e) => e.text && /output/.test(e.text()) && e.getAttribute && e.getAttribute("class") === null && e.children.some((c) => c.className === "log"));
    if (!stop || !details) return "running panel incomplete: " + p.text("chat-box");
    details.setAttribute("open", "");                 // the user opens llama-server's output
    stop.focus();
    const said = [];
    const live = p.el("live");
    let last = live.textContent;
    for (let i = 0; i < 4; i++) { await p.advance(3000); if (live.textContent !== last) { said.push(live.textContent); last = live.textContent; } }
    if (p.button("chat-box", "Stop") !== stop) return "the Stop button was rebuilt by polling (keyboard focus is lost)";
    if (p.focused() !== stop) return "focus moved off Stop";
    if (details.getAttribute("open") === null) return "the opened output was closed by polling";
    if (!p.text("chat-box").includes("line 2")) return "new output was not shown: " + p.text("chat-box");
    if (said.length) return "re-announced on polling: " + said.join(" | ");
  },

  async "a chat that is running when the page opens can be opened or stopped from the first screen"() {
    const posts = [];
    const st = { ...STATE, chat: RUNNING };
    const p = makePage({ routes: chatRoutes({ state: st, progress: { state: "idle" }, posts, chats: [RUNNING], stop: STOPPED }) });
    await p.start();
    if (p.visible() !== "v-use") return "expected the first screen, got " + p.visible();
    const warn = p.el("warn");
    const link = findEl(warn, (e) => e.getAttribute && e.getAttribute("href") === RUNNING.url);
    if (!link) return "no link to the running chat: " + p.text("warn");
    p.button("warn", "Stop").click(); await p.settle();
    if (!posts.some((x) => x.path === "/api/chat/stop")) return "Stop did not ask the server";
    if (findEl(p.el("warn"), (e) => e.getAttribute && e.getAttribute("href") === RUNNING.url)) return "still offers the stopped chat";
  },
};

// --- Installing llama.cpp ----------------------------------------------------------------------------------------
const OFFER = { how: "download", kind: "cpu", label: "CPU build", into: "/p/proj/bin" };
const NEED = { found: "", works: false, version: "", need: "missing", offer: OFFER, job: { state: "idle", log: [] } };
function llamaRoutes({ infos, posts = [], state, start = { state: "checking", log: [] } }) {
  let i = 0;
  return (path, opts) => {
    if (path === "/api/state") return state || { ...STATE, llama_server: false, llama: infos[0] };
    if (path === "/api/progress") return { state: "idle" };
    if (path === "/api/llama") return infos[Math.min(i++, infos.length - 1)];
    if (path === "/api/llama/install") { posts.push(JSON.parse(opts.body)); i = Math.max(i, 1); return start; }
    return {};
  };
}
const job = (j) => ({ ...NEED, job: { log: [], ...j } });

Object.assign(scenarios, {
  async "the llama.cpp notice offers to install it, and the install view says from where and to where"() {
    const p = makePage({ routes: llamaRoutes({ infos: [NEED] }) });
    await p.start();
    const b = p.button("warn", "Install llama.cpp");
    if (!b) return "no install button in the notice: " + p.text("warn");
    b.click(); await p.settle();
    if (p.visible() !== "v-llama") return "install view did not open: " + p.visible();
    if (p.location.hash !== "#llama") return "the install view has no address: " + p.location.hash;
    const t = p.text("llama-body");
    if (!t.includes("github.com/ggml-org/llama.cpp") || !t.includes("/p/proj/bin")) return "does not say from where and to where: " + t;
    if (!/no admin/i.test(t)) return "does not say it needs no admin rights: " + t;
    if (!p.button("llama-body", "Install llama.cpp (CPU build)")) return "no install button in the view: " + t;
  },

  async "installing shows progress, then the version, how it was checked, and a copy that shadows it"() {
    const posts = [];
    const done = job({ state: "done", path: "/usr/bin/llama-server", version: "version: 4242 (abc1234)", checksum: "verified",
      shadowed: "Another llama-server comes first: /usr/bin/llama-server." });
    const p = makePage({ hash: "#llama", routes: llamaRoutes({ posts, infos: [NEED,
      job({ state: "downloading", done: 50, total: 100, kind: "cpu", why: "CPU build." }),
      job({ state: "verifying", done: 100, total: 100 }), done, { ...done, found: "/usr/bin/llama-server", works: true, need: "" }] }) });
    await p.start();
    p.button("llama-body", "Install llama.cpp").click(); await p.settle();
    if (JSON.stringify(posts) !== "[{\"variant\":\"auto\"}]") return "install request: " + JSON.stringify(posts);
    const bar = findEl(p.el("llama-body"), (e) => e.getAttribute && e.getAttribute("role") === "progressbar");
    if (!bar || bar.getAttribute("aria-valuenow") !== "50") return "no progress at 50%: " + p.text("llama-body");
    await p.advance(3000);
    const t = p.text("llama-body");
    if (!t.includes("4242")) return "version not shown: " + t;
    if (!/SHA-256/.test(t)) return "does not say it was checked against the published checksum: " + t;
    if (!t.includes("Another llama-server comes first")) return "shadowing copy not named: " + t;
  },

  async "an install without a published checksum says only the size was checked"() {
    const p = makePage({ hash: "#llama", routes: llamaRoutes({ infos: [job({ state: "done", path: "/p/proj/bin/llama-server",
      version: "version: 1", checksum: "none-published", shadowed: "" })] }) });
    await p.start();
    if (!/no checksum/i.test(p.text("llama-body"))) return "no checksum note: " + p.text("llama-body");
  },

  async "a failed install shows why, llama-server's output, and offers the CPU build"() {
    const posts = [];
    const failed = job({ state: "failed", error: "The downloaded Vulkan build did not start.", cpu_fallback: true,
      log: ["error while loading shared libraries: libvulkan.so.1"] });
    const p = makePage({ hash: "#llama", routes: llamaRoutes({ posts, infos: [failed] }) });
    await p.start();
    const t = p.text("llama-body");
    if (!t.includes("did not start") || !t.includes("libvulkan.so.1")) return "error or log missing: " + t;
    const cpu = p.button("llama-body", "Install the CPU build instead");
    if (!cpu) return "CPU build not offered: " + t;
    cpu.click(); await p.settle();
    if (posts[0].variant !== "cpu") return "did not ask for the CPU build: " + JSON.stringify(posts);
  },

  async "macOS with Homebrew shows the brew command; without it, only the instructions and no button"() {
    const brew = { ...NEED, offer: { how: "brew", cmd: "brew install llama.cpp" } };
    let p = makePage({ hash: "#llama", routes: llamaRoutes({ infos: [brew] }) });
    await p.start();
    if (!p.button("llama-body", "Install with Homebrew")) return "no Homebrew button: " + p.text("llama-body");
    if (!p.text("llama-body").includes("brew install llama.cpp")) return "brew command not shown";
    const manual = { ...NEED, offer: { how: "manual" } };
    p = makePage({ hash: "#llama", routes: llamaRoutes({ infos: [manual], state: { ...STATE, llama_server: false, llama: manual,
      llama_install: { install: "Install Homebrew (see brew.sh), then run: brew install llama.cpp" } } }) });
    await p.start();
    if (p.button("llama-body", "Install")) return "an install button without a way to install";
    if (!p.text("llama-body").includes("Install Homebrew")) return "instructions missing: " + p.text("llama-body");
  },

  async "a build that cannot use the GPU is explained, with a way to get one that can"() {
    const nogpu = { ...NEED, found: "/usr/bin/llama-server", works: true, version: "version: 1", need: "no-gpu",
      offer: { how: "download", kind: "cuda", label: "CUDA build for your NVIDIA graphics card", into: "/p/proj/bin" } };
    const st = { ...STATE, llama_server: true, gpu_unused: true, llama: nogpu };
    const p = makePage({ routes: llamaRoutes({ infos: [nogpu], state: st }) });
    await p.start();
    const b = p.button("warn", "Get a build that uses it");
    if (!b) return "no way to get a GPU build: " + p.text("warn");
    b.click(); await p.settle();
    const t = p.text("llama-body");
    if (!t.includes("/usr/bin/llama-server") || !/cannot use your graphics card/.test(t)) return "the reason is not explained: " + t;
    if (!p.button("llama-body", "Install llama.cpp (CUDA build")) return "no CUDA install button: " + t;
  },

  async "leaving the install view stops asking about the install"() {
    const p = makePage({ hash: "#llama", routes: llamaRoutes({ infos: [job({ state: "downloading", done: 1, total: 100 })] }) });
    await p.start();
    await p.click("tools-btn");
    const before = p.state.calls.filter((c) => c === "/api/llama").length;
    await p.advance(20000);
    const after = p.state.calls.filter((c) => c === "/api/llama").length;
    if (after !== before) return `kept polling from another view: ${after - before} requests`;
  },
});

function findEl(root, pred) {
  if (!root) return null;
  if (pred(root)) return root;
  for (const c of root.children || []) { const f = findEl(c, pred); if (f) return f; }
  return null;
}

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
