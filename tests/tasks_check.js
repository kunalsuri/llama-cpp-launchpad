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

async function open(browser, { width = 1280, scheme = "light", reply = { status: 200, pieces: ["First point.", " Second point."] } } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height: 800 }, colorScheme: scheme });
  const page = await ctx.newPage();
  const sent = [], errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/" || url.pathname === "/index.html") return route.fulfill({ contentType: "text/html", body: HTML });
    if (url.pathname === "/v1/models") return route.fulfill({ contentType: "application/json", body: JSON.stringify({ data: [{ id: "/models/Qwen3-4B-Q4_K_M.gguf" }] }) });
    if (url.pathname === "/v1/chat/completions") {
      sent.push(JSON.parse(route.request().postData() || "{}"));
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

(async () => {
  const browser = await chromium.launch();
  try {
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
  } finally {
    await browser.close();
  }
  for (const r of results) console.log(JSON.stringify(r));
  process.exit(results.every((r) => r.ok) ? 0 : 1);
})();
