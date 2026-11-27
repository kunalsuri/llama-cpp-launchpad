// Opens ui/tasks/index.html in a real browser (Chromium via Playwright). Every request is answered by this script
// (page.route): the page itself, and llama-server's /v1/models and /v1/chat/completions (streamed, as the real one
// streams). Prints one JSON line per check: {"name", "ok", "detail"}. Driven by tests/test_browser.py (TestTasksPage).
// Usage: node tests/tasks_check.js ui/tasks/index.html
"use strict";
const fs = require("fs");
const { chromium } = require("playwright");

const HTML = fs.readFileSync(process.argv[2], "utf8");
const BASE = "http://127.0.0.1:8080/";
const results = [];
const check = (name, detail) => results.push({ name, ok: !detail, detail: detail || "" });

function sse(pieces) {
  const chunks = pieces.map((p) => `data: ${JSON.stringify({ choices: [{ delta: { content: p } }] })}\n\n`);
  chunks.push(`data: ${JSON.stringify({ choices: [], usage: { completion_tokens: pieces.length } })}\n\n`, "data: [DONE]\n\n");
  return chunks.join("");
}

async function open(browser, { width = 1280, scheme = "light", init = "", reply = { status: 200, pieces: ["First point.", " Second point."] } } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height: 800 }, colorScheme: scheme });
  if (init) await ctx.addInitScript(init);
  const page = await ctx.newPage();
  page.setDefaultTimeout(3000);
  const sent = [], errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/" || url.pathname === "/index.html") return route.fulfill({ contentType: "text/html", body: HTML });
    if (url.pathname === "/v1/models") return route.fulfill({ contentType: "application/json", body: JSON.stringify({ data: [{ id: "/models/Qwen3-4B-Q4_K_M.gguf" }] }) });
    if (url.pathname === "/v1/chat/completions") {
      sent.push(JSON.parse(route.request().postData() || "{}"));
      if (reply.hang) return; // never answers: the test presses Stop
      if (reply.status !== 200) return route.fulfill({ status: reply.status, body: reply.body || "model not loaded" });
      return route.fulfill({ contentType: "text/event-stream", body: sse(reply.pieces) });
    }
    return route.fulfill({ status: 404, body: "" });
  });
  await page.goto(BASE);
  return { page, ctx, sent, errors };
}

async function run(page, text) {
  await page.fill("#text", text);
  await page.click("#run");
  await page.waitForFunction(() => document.querySelector("#run").getAttribute("aria-label") === "Run", null, { timeout: 10000 });
}

// One named scenario: any error (a selector that never appears, a failed expectation) becomes a readable failure.
async function scenario(name, fn) {
  try { check(name, (await fn()) || ""); } catch (e) { check(name, String(e && e.message || e).split("\n")[0]); }
}
const KEY = (page) => page.evaluate(() => {
  try { return Object.keys(localStorage).filter((k) => /tasks/.test(k) && /history/.test(k))[0] || ""; } catch (e) { return ""; }
});
const stored = (page) => page.evaluate(() => {
  try {
    const k = Object.keys(localStorage).filter((k) => /tasks/.test(k) && /history/.test(k))[0];
    return k ? JSON.parse(localStorage.getItem(k)) : null;
  } catch (e) { return null; }
});
const items = (page) => page.$$eval("#history-list > li", (l) => l.length);
// Stand-in for a browser with storage switched off (private mode): every access throws.
const NO_STORAGE = "Object.defineProperty(window, 'localStorage', { get() { throw new DOMException('denied', 'SecurityError'); } });";
const FULL_STORAGE = "Storage.prototype.setItem = function () { throw new DOMException('full', 'QuotaExceededError'); };";

async function historyChecks(browser) {
  {
    const { page, ctx, errors } = await open(browser);
    await scenario("History says it stays in this browser", async () => {
      const t = await page.textContent("#history");
      return /this browser/i.test(t) ? "" : "history section says: " + t;
    });
    await run(page, "alpha text to summarize");
    await scenario("a successful result is added to History and saved in localStorage", async () => {
      const n = await items(page), list = await stored(page);
      if (n !== 1) return "list shows " + n + " items";
      const e = list && list[0];
      if (!e) return "nothing saved under a tasks history key: " + (await KEY(page));
      if (e.task !== "summarize" || e.option !== "short" || e.input !== "alpha text to summarize" || e.output !== "First point. Second point." || !(e.time || e.t))
        return "saved: " + JSON.stringify(e);
    });
    await page.reload();
    await scenario("History is still there after a reload", async () => (await items(page)) === 1 ? "" : "items after reload: " + (await items(page)));

    await page.click("[data-task=rewrite]");
    await page.fill("#text", "something else");
    await scenario("clicking an item restores task, option, input and output", async () => {
      await page.click("#history-list > li:first-child .hist-open");
      const s = await page.evaluate(() => ({
        pressed: document.querySelector("#tasks [aria-pressed=true]").getAttribute("data-task"),
        text: document.querySelector("#text").value, out: document.querySelector("#output").textContent,
        opt: document.querySelector("#option").value, shown: !document.querySelector("#result").hidden }));
      return s.pressed === "summarize" && s.text === "alpha text to summarize" && s.out.includes("First point. Second point.") && s.opt === "short" && s.shown
        ? "" : JSON.stringify(s);
    });

    await run(page, "beta text");
    await scenario("the newest item is first, and each has its own Delete", async () => {
      const first = await page.textContent("#history-list > li:first-child");
      if ((await items(page)) !== 2 || !first.includes("beta text")) return "items " + (await items(page)) + ", first: " + first;
      await page.click("#history-list > li:first-child .hist-del");
      const left = await stored(page);
      if ((await items(page)) !== 1 || !left || left.length !== 1 || left[0].input !== "alpha text to summarize") return "after delete: " + JSON.stringify(left);
    });
    await scenario("Clear history asks first; Cancel keeps everything", async () => {
      const before = await items(page);
      await page.click("#history-clear");
      if (!(await page.isVisible("#history-confirm"))) return "no confirmation shown";
      const ask = await page.textContent("#history-confirm");
      if (!ask.includes(String(before))) return "confirmation does not say how many: " + ask;
      const kept = await stored(page);
      if ((await items(page)) !== before || !kept || kept.length !== before) return "cleared before confirming: " + JSON.stringify(kept);
      await page.click("#history-clear-no");
      if (await page.isVisible("#history-confirm")) return "confirmation still shown after Cancel";
      const after = await stored(page);
      if ((await items(page)) !== before || !after || after.length !== before) return "Cancel cleared: " + JSON.stringify(after);
    });
    await scenario("Clear history, then Yes, empties the list and the saved copy", async () => {
      await page.click("#history-clear");
      await page.click("#history-clear-yes");
      const left = await stored(page);
      if ((await items(page)) !== 0 || (left && left.length)) return "left: " + JSON.stringify(left);
      if (!(await page.isVisible("#history-empty"))) return "no empty-state message";
    });
    check("no script errors (history)", errors.join("; "));
    await ctx.close();
  }
  {
    const { page, ctx } = await open(browser, { reply: { status: 503, body: "Loading model" } });
    await run(page, "this will fail");
    await scenario("a failed request is not saved", async () => {
      const n = await items(page), list = await stored(page);
      return n === 0 && !(list && list.length) ? "" : "items " + n + ", saved " + JSON.stringify(list);
    });
    await ctx.close();
  }
  {
    const { page, ctx } = await open(browser, { reply: { hang: true } });
    await page.fill("#text", "this will be stopped");
    await page.click("#run");
    await page.waitForFunction(() => document.querySelector("#run").getAttribute("aria-label") === "Stop");
    await page.click("#run");
    await page.waitForFunction(() => document.querySelector("#run").getAttribute("aria-label") === "Run");
    await scenario("a stopped request is not saved", async () => {
      const n = await items(page), list = await stored(page);
      return n === 0 && !(list && list.length) ? "" : "items " + n + ", saved " + JSON.stringify(list);
    });
    await ctx.close();
  }
  {
    const { page, ctx } = await open(browser);
    const old = Array.from({ length: 20 }, (_, n) => 19 - n).map((i) => ({ time: 1700000000000 + i, task: "summarize", option: "short", input: "old " + i, output: "out " + i }));
    await page.evaluate((o) => localStorage.setItem("lp.tasks.history.v1", JSON.stringify(o)), old);
    await page.reload();
    await run(page, "the 21st");
    await scenario("History keeps the last 20 and drops the oldest", async () => {
      const list = await stored(page);
      if (!list || list.length !== 20) return "saved " + (list && list.length);
      const inputs = list.map((e) => e.input);
      if (!inputs.includes("the 21st") || inputs.includes("old 0") || !inputs.includes("old 1")) return "saved inputs: " + inputs.join(",");
      if ((await items(page)) !== 20) return "list shows " + (await items(page));
    });
    await ctx.close();
  }
  {
    const { page, ctx } = await open(browser);
    await run(page, "x".repeat(5000));
    await scenario("a long input is shortened when saved, with the output kept", async () => {
      const list = await stored(page), e = list && list[0];
      if (!e) return "nothing saved";
      if (e.input.length > 2000 || e.input.length < 1000) return "input length " + e.input.length;
      if (e.output !== "First point. Second point.") return "output: " + e.output;
    });
    await ctx.close();
  }
  for (const [label, init] of [["blocked", NO_STORAGE], ["full", FULL_STORAGE]]) {
    const { page, ctx, errors } = await open(browser, { init });
    await run(page, "works without storage");
    await scenario(`storage ${label}: the task still runs and shows its result`, async () => {
      const out = await page.textContent("#output");
      return out.includes("First point.") ? "" : "output: " + out;
    });
    await scenario(`storage ${label}: History keeps this visit's items and says they are not saved`, async () => {
      if ((await items(page)) !== 1) return "items " + (await items(page));
      const note = await page.textContent("#history-note");
      return /not saved|not saving|can.?t save|cannot save|unavailable/i.test(note) ? "" : "note: " + note;
    });
    check(`storage ${label}: no script errors`, errors.join("; "));
    await ctx.close();
  }
  for (const [width, scheme] of [[360, "light"], [360, "dark"], [1280, "dark"]]) {
    const { page, ctx } = await open(browser, { width, scheme });
    await run(page, "A long text ".repeat(40));
    await run(page, "Another text with-a-very-long-unbroken-word-" + "w".repeat(120));
    await scenario(`History layout at ${width}px, ${scheme}`, async () => page.evaluate(() => {
      const d = document.documentElement, problems = [];
      if (d.scrollWidth > d.clientWidth + 1) problems.push(`scrolls sideways: ${d.scrollWidth}px in ${d.clientWidth}px`);
      for (const b of document.querySelectorAll("#history button")) {
        if (b.offsetParent === null) continue;
        if (!(b.getAttribute("aria-label") || b.innerText.trim())) problems.push("a history button without a name");
        const r = b.getBoundingClientRect();
        if (innerWidth <= 480 && (r.height < 32 || r.width < 32)) problems.push(`tap target ${Math.round(r.width)}x${Math.round(r.height)}: ${b.className}`);
      }
      const leaked = document.querySelector("#history").innerText.match(/\b(null|undefined|NaN|\[object Object\])\b/);
      if (leaked) problems.push(`"${leaked[0]}" in History`);
      const h = document.querySelector("#history");
      if (!h) problems.push("no #history");
      else if (getComputedStyle(h).color === getComputedStyle(document.body).backgroundColor) problems.push("History text has the background's colour");
      return problems.join("; ");
    }));
    await ctx.close();
  }
}

const textFile = (name, text) => ({ name, mimeType: "text/plain", buffer: Buffer.from(text) });
const dropFile = (page, name, text) => page.evaluate(([n, t]) => {
  const dt = new DataTransfer();
  dt.items.add(new File([t], n, { type: "" }));
  const box = document.querySelector("#form");
  box.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
  box.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
}, [name, text]);
const status = (page) => page.textContent("#file-status");
const waitStatus = (page, re) => page.waitForFunction((src) => new RegExp(src, "i").test((document.querySelector("#file-status") || {}).textContent || ""), re.source);

async function fileChecks(browser) {
  {
    const { page, ctx, sent, errors } = await open(browser);
    await scenario("Open file loads a text file into the box and shows its name", async () => {
      await page.setInputFiles("#file", textFile("notes.txt", "Meeting notes\nSecond line"));
      await waitStatus(page, /notes\.txt/);
      const v = await page.inputValue("#text");
      return v === "Meeting notes\nSecond line" ? "" : "text box holds: " + v;
    });
    await scenario("the same file can be opened again after editing the box", async () => {
      await page.fill("#text", "edited");
      await page.setInputFiles("#file", textFile("notes.txt", "Meeting notes\nSecond line"));
      await page.waitForFunction(() => document.querySelector("#text").value.startsWith("Meeting"));
    });
    await scenario("the loaded text is what Summarize sends", async () => {
      await run(page, await page.inputValue("#text"));
      return JSON.stringify(sent[0]).includes("Second line") ? "" : JSON.stringify(sent[0]);
    });
    await scenario("Explain code uses the file's extension as the language", async () => {
      await page.click("[data-task=explain]");
      await page.setInputFiles("#file", textFile("tool.py", "def f(x):\n    return x * 2\n"));
      await waitStatus(page, /Python/);
      await page.click("#run");
      await page.waitForFunction(() => document.querySelector("#run").getAttribute("aria-label") === "Run");
      const body = JSON.stringify(sent[sent.length - 1]);
      return /Python/.test(body) && body.includes("return x * 2") ? "" : body;
    });
    await scenario("a file in an unfamiliar language is named by its extension, not guessed", async () => {
      await page.setInputFiles("#file", textFile("kernel.zig", "pub fn main() void {}"));
      await waitStatus(page, /kernel\.zig/);
      return (await page.inputValue("#text")) === "pub fn main() void {}" ? "" : "not loaded";
    });
    check("no script errors (open file)", errors.join("; "));
    await ctx.close();
  }
  {
    const { page, ctx } = await open(browser);
    await scenario("dropping a file on the input area loads it", async () => {
      await dropFile(page, "README.md", "# Title\n\nBody");
      await waitStatus(page, /README\.md/);
      return (await page.inputValue("#text")) === "# Title\n\nBody" ? "" : "text box holds: " + (await page.inputValue("#text"));
    });
    await scenario("the drop target is marked while a file is dragged over it", async () => {
      const on = await page.evaluate(() => {
        const dt = new DataTransfer(); dt.items.add(new File(["x"], "a.txt"));
        document.querySelector("#form").dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
        return document.querySelector("#form").classList.contains("drag");
      });
      return on ? "" : "no .drag class on the input area during dragover";
    });
    await ctx.close();
  }
  {
    const { page, ctx, sent } = await open(browser);
    await page.fill("#text", "my own text");
    await scenario("a binary file is refused, by name, and leaves the text alone", async () => {
      const bytes = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0, 0, 0, 13]), Buffer.alloc(200, 0)]);
      await page.setInputFiles("#file", { name: "photo.png", mimeType: "image/png", buffer: bytes });
      await waitStatus(page, /photo\.png/);
      const s = await status(page);
      if (!/binary|not (a )?text/i.test(s)) return "message: " + s;
      return (await page.inputValue("#text")) === "my own text" ? "" : "text box changed to: " + (await page.inputValue("#text"));
    });
    await scenario("a binary file dropped on the box is refused the same way", async () => {
      await page.evaluate(() => {
        const dt = new DataTransfer(); dt.items.add(new File([new Uint8Array([0, 1, 2, 0, 0, 3])], "app.bin"));
        document.querySelector("#form").dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
      });
      await waitStatus(page, /app\.bin/);
      return /binary|not (a )?text/i.test(await status(page)) ? "" : "message: " + (await status(page));
    });
    await scenario("a file over the limit is refused with its name and the limit", async () => {
      await page.setInputFiles("#file", textFile("huge.log", "a".repeat(1024 * 1024 + 1)));
      await waitStatus(page, /huge\.log/);
      const s = await status(page);
      if (!/1 ?MB/i.test(s)) return "message: " + s;
      return (await page.inputValue("#text")) === "my own text" ? "" : "text box changed";
    });
    await scenario("a file of exactly the limit is accepted", async () => {
      await page.setInputFiles("#file", textFile("edge.txt", "b".repeat(1024 * 1024)));
      await page.waitForFunction(() => document.querySelector("#text").value.length === 1024 * 1024, null, { timeout: 8000 });
    });
    check("refused files send nothing to the model", sent.length === 0 ? "" : "requests: " + sent.length);
    await ctx.close();
  }
  for (const [width, scheme] of [[360, "light"], [360, "dark"], [1280, "dark"]]) {
    const { page, ctx } = await open(browser, { width, scheme });
    const long = "a-very-long-file-name-" + "n".repeat(120) + ".txt";
    await page.setInputFiles("#file", textFile(long, "text"));
    await waitStatus(page, /a-very-long/);
    await scenario(`Open file layout at ${width}px, ${scheme}`, async () => {
      const bad = await page.evaluate(() => {
        const d = document.documentElement, problems = [];
        if (d.scrollWidth > d.clientWidth + 1) problems.push(`scrolls sideways: ${d.scrollWidth}px in ${d.clientWidth}px`);
        const b = document.querySelector("#open-file");
        if (!b) problems.push("no #open-file button");
        else if (!(b.getAttribute("aria-label") || b.innerText.trim())) problems.push("Open file button without a name");
        else if (innerWidth <= 480 && b.getBoundingClientRect().height < 32) problems.push("Open file button under 32px tall");
        return problems.join("; ");
      });
      return bad;
    });
    await ctx.close();
  }
  {
    const { page, ctx } = await open(browser, { init: NO_STORAGE });
    await scenario("Open file works with storage blocked", async () => {
      await page.setInputFiles("#file", textFile("a.txt", "hello"));
      await page.waitForFunction(() => document.querySelector("#text").value === "hello");
    });
    await ctx.close();
  }
}

(async () => {
  const browser = await chromium.launch();
  const mode = process.argv[3] || "page";
  try {
    if (mode === "history") await historyChecks(browser);
    else if (mode === "file") await fileChecks(browser);
    else {
    {
      const { page, ctx, sent, errors } = await open(browser);
      const model = await page.textContent("#model");
      check("the badge names the model llama-server loaded", /Qwen3-4B-Q4_K_M/.test(model) ? "" : "badge says: " + model);
      await run(page, "A long report about the quarterly numbers.");
      const out = await page.textContent("#output");
      check("Summarize streams the reply into the output", out.includes("First point. Second point.") ? "" : "output: " + out);
      const body = sent[0] || {};
      const sys = ((body.messages || [])[0] || {}).content || "";
      const user = ((body.messages || [])[1] || {}).content || "";
      check("Summarize asks for a summary of exactly the text given",
        /summar/i.test(sys) && user.includes("A long report about the quarterly numbers.") && body.stream === true ? "" : JSON.stringify(body));
      const stats = await page.textContent("#stats");
      check("the speed of the reply is shown", /2 tokens/.test(stats) ? "" : "stats: " + stats);

      await page.click("[data-task=explain]");
      const ph = await page.getAttribute("#text", "placeholder");
      check("Explain code asks for code", /code/i.test(ph) ? "" : "placeholder: " + ph);
      await run(page, "def f(x):\n    return x * 2");
      const sys2 = ((sent[1] || {}).messages || [])[0] || {};
      check("Explain code sends an explaining prompt with the code", /explain/i.test(sys2.content || "") &&
        ((sent[1].messages[1] || {}).content || "").includes("return x * 2") ? "" : JSON.stringify(sent[1]));

      await page.click("[data-task=rewrite]");
      await page.selectOption("#option", "formal");
      await run(page, "hey can u send it");
      const sys3 = ((sent[2] || {}).messages || [])[0] || {};
      check("Rewrite uses the chosen tone", /formal/i.test(sys3.content || "") ? "" : JSON.stringify(sent[2]));
      check("no script errors", errors.join("; "));
      await ctx.close();
    }
    {
      const { page, ctx } = await open(browser, { reply: { status: 503, body: "Loading model" } });
      await run(page, "Some text");
      const out = await page.textContent("#output");
      check("a server error is shown as text, not swallowed", /503/.test(out) && /Loading model/.test(out) ? "" : "output: " + out);
      await ctx.close();
    }
    for (const [width, scheme] of [[360, "light"], [360, "dark"], [1280, "dark"]]) {
      const { page, ctx } = await open(browser, { width, scheme });
      await run(page, "Some text to summarize.");
      const p = await page.evaluate(() => {
        const d = document.documentElement, problems = [];
        if (d.scrollWidth > d.clientWidth + 1) problems.push(`scrolls sideways: ${d.scrollWidth}px in ${d.clientWidth}px`);
        const leaked = document.body.innerText.match(/\b(null|undefined|NaN|\[object Object\])\b/);
        if (leaked) problems.push(`"${leaked[0]}" on the page`);
        for (const b of document.querySelectorAll("button, select, textarea")) {
          if (b.offsetParent === null) continue;
          if (!(b.getAttribute("aria-label") || b.innerText.trim() || (b.labels && b.labels.length))) problems.push("a control without a name: " + b.outerHTML.slice(0, 60));
        }
        const bg = getComputedStyle(document.body).backgroundColor, fg = getComputedStyle(document.body).color;
        if (bg === fg) problems.push("text has the background's colour");
        return problems.join("; ");
      });
      check(`layout at ${width}px, ${scheme}`, p);
      await ctx.close();
    }
    }
  } catch (e) {
    check("the check script ran to the end", String(e && e.message || e).split("\n")[0]);
  } finally {
    await browser.close();
  }
  for (const r of results) console.log(JSON.stringify(r));
  process.exit(results.every((r) => r.ok) ? 0 : 1);
})();
