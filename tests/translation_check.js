// Opens ui/translation/index.html in a real browser (Chromium via Playwright) and checks its History list. Every request
// is answered by this script (page.route): the page itself, llama-server's /v1/models and /v1/chat/completions (streamed).
// Prints one JSON line per check: {"name", "ok", "detail"}. Driven by tests/test_browser.py (TestTranslationPage).
// Usage: node tests/translation_check.js ui/translation/index.html
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

async function open(browser, { width = 1280, scheme = "light", init = "", reply = { status: 200, pieces: ["Bonjour !", " Comment allez-vous ?"] } } = {}) {
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

const idle = (page) => page.waitForFunction(() => document.querySelector("#send").getAttribute("aria-label") === "Translate", null, { timeout: 10000 });
async function translate(page, text) {
  if (text !== undefined) await page.fill("#text", text);
  await page.click("#send");
  await idle(page);
}
async function scenario(name, fn) {
  try { check(name, (await fn()) || ""); } catch (e) { check(name, String(e && e.message || e).split("\n")[0]); }
}
const readKey = "(() => { try { return Object.keys(localStorage).filter((k) => /translation/.test(k) && /history/.test(k))[0] || ''; } catch (e) { return ''; } })()";
const stored = (page) => page.evaluate(`(() => { try { const k = ${readKey}; return k ? JSON.parse(localStorage.getItem(k)) : null; } catch (e) { return null; } })()`);
const items = (page) => page.$$eval("#history-list > li", (l) => l.length);
async function openHistory(page) {
  if (!(await page.$eval("#history", (d) => d.open))) await page.click("#history > summary");
}
const NO_STORAGE = "Object.defineProperty(window, 'localStorage', { get() { throw new DOMException('denied', 'SecurityError'); } });";
const FULL_STORAGE = "Storage.prototype.setItem = function () { throw new DOMException('full', 'QuotaExceededError'); };";
const nothingSaved = async (page) => {
  const n = await items(page), list = await stored(page);
  return n === 0 && !(list && list.length) ? "" : "items " + n + ", saved " + JSON.stringify(list);
};

(async () => {
  const browser = await chromium.launch();
  try {
    {
      const { page, ctx, errors } = await open(browser);
      await scenario("History says it stays in this browser", async () => {
        await openHistory(page);
        const t = await page.textContent("#history");
        return /this browser/i.test(t) ? "" : "history section says: " + t;
      });
      await translate(page);
      await scenario("a finished translation is added to History and saved in localStorage", async () => {
        const n = await items(page), list = await stored(page), e = list && list[0];
        if (n !== 1) return "list shows " + n + " items";
        if (!e) return "nothing saved under a translation history key: " + (await page.evaluate(readKey));
        if (e.from !== "English" || e.to !== "French" || !e.input.startsWith("Good morning") || e.output !== "Bonjour ! Comment allez-vous ?" || !(e.time || e.t))
          return "saved: " + JSON.stringify(e);
      });
      await page.reload();
      await scenario("History is still there after a reload", async () => (await items(page)) === 1 ? "" : "items after reload: " + (await items(page)));

      await translate(page, "Hallo Welt");
      await page.selectOption("#from", "Spanish");
      await page.selectOption("#to", "German");
      await translate(page, "Buenas noches");
      await page.click("#new");
      await openHistory(page);
      await scenario("the newest item is first and shows its language pair", async () => {
        const first = await page.textContent("#history-list > li:first-child");
        return (await items(page)) === 3 && first.includes("Buenas noches") && /Spanish/.test(first) && /German/.test(first) ? "" : "items " + (await items(page)) + ", first: " + first;
      });
      await scenario("clicking an item restores the languages, the input and the output", async () => {
        await page.click("#history-list > li:first-child .hist-open");
        const s = await page.evaluate(() => ({
          from: document.querySelector("#from").value, to: document.querySelector("#to").value,
          src: (document.querySelector(".bubble") || {}).textContent, out: (document.querySelector(".answer") || {}).textContent }));
        return s.from === "Spanish" && s.to === "German" && s.src === "Buenas noches" && /Bonjour/.test(s.out || "") ? "" : JSON.stringify(s);
      });
      await scenario("a restored item can be translated again", async () => {
        await page.click("[aria-label='Translate again']");
        await idle(page);
        return /Bonjour/.test(await page.textContent(".answer")) ? "" : "no answer after Translate again";
      });
      await scenario("each item has its own Delete", async () => {
        await openHistory(page);
        const before = await items(page);
        await page.click("#history-list > li:last-child .hist-del");
        const left = await stored(page);
        // The last row is the oldest: the example sentence the page opens with.
        return (await items(page)) === before - 1 && left && left.length === before - 1 && !left.some((e) => e.input.startsWith("Good morning"))
          ? "" : "after delete: " + JSON.stringify(left);
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
      await translate(page);
      await scenario("a failed request is not saved", () => nothingSaved(page));
      await ctx.close();
    }
    {
      const { page, ctx } = await open(browser, { reply: { hang: true } });
      await page.click("#send");
      await page.waitForFunction(() => document.querySelector("#send").getAttribute("aria-label") === "Stop");
      await page.click("#send");
      await idle(page);
      await scenario("a stopped request is not saved", () => nothingSaved(page));
      await ctx.close();
    }
    {
      const { page, ctx } = await open(browser);
      const old = Array.from({ length: 20 }, (_, n) => 19 - n).map((i) => ({ time: 1700000000000 + i, from: "English", to: "French", form: "vous", input: "old " + i, output: "out " + i }));
      await page.evaluate((o) => localStorage.setItem("lp.translation.history.v1", JSON.stringify(o)), old);
      await page.reload();
      await translate(page, "the 21st");
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
      await translate(page, "x".repeat(5000));
      await scenario("a long input is shortened when saved, with the output kept", async () => {
        const list = await stored(page), e = list && list[0];
        if (!e) return "nothing saved";
        if (e.input.length > 2000 || e.input.length < 1000) return "input length " + e.input.length;
        if (e.output !== "Bonjour ! Comment allez-vous ?") return "output: " + e.output;
      });
      await ctx.close();
    }
    for (const [label, init] of [["blocked", NO_STORAGE], ["full", FULL_STORAGE]]) {
      const { page, ctx, errors } = await open(browser, { init });
      await translate(page);
      await scenario(`storage ${label}: translating still works`, async () => {
        const out = await page.textContent(".answer");
        return out.includes("Bonjour") ? "" : "answer: " + out;
      });
      await scenario(`storage ${label}: History keeps this visit's items and says they are not saved`, async () => {
        await openHistory(page);
        if ((await items(page)) !== 1) return "items " + (await items(page));
        const note = await page.textContent("#history-note");
        return /not saved|not saving|can.?t save|cannot save|unavailable/i.test(note) ? "" : "note: " + note;
      });
      check(`storage ${label}: no script errors`, errors.join("; "));
      await ctx.close();
    }
    for (const [width, scheme] of [[360, "light"], [360, "dark"], [1280, "dark"]]) {
      const { page, ctx } = await open(browser, { width, scheme });
      await translate(page, "A long text ".repeat(40));
      await translate(page, "Another text with-a-very-long-unbroken-word-" + "w".repeat(120));
      await openHistory(page);
      await scenario(`History layout at ${width}px, ${scheme}`, async () => page.evaluate(() => {
        const d = document.documentElement, problems = [];
        if (d.scrollWidth > d.clientWidth + 1) problems.push(`scrolls sideways: ${d.scrollWidth}px in ${d.clientWidth}px`);
        const h = document.querySelector("#history");
        if (!h) return "no #history";
        for (const b of h.querySelectorAll("button, summary")) {
          if (b.offsetParent === null) continue;
          if (!(b.getAttribute("aria-label") || b.innerText.trim())) problems.push("a history control without a name");
          const r = b.getBoundingClientRect();
          if (innerWidth <= 480 && (r.height < 32 || r.width < 32)) problems.push(`tap target ${Math.round(r.width)}x${Math.round(r.height)}: ${b.className || b.tagName}`);
        }
        const r = h.getBoundingClientRect();
        if (r.bottom > innerHeight + 1 || r.top < 0) problems.push("History is not fully on screen");
        const leaked = h.innerText.match(/\b(null|undefined|NaN|\[object Object\])\b/);
        if (leaked) problems.push(`"${leaked[0]}" in History`);
        if (getComputedStyle(h).color === getComputedStyle(document.body).backgroundColor) problems.push("History text has the background's colour");
        return problems.join("; ");
      }));
      await ctx.close();
    }
  } catch (e) {
    check("the check script ran to the end", String(e && e.message || e).split("\n")[0]);
  } finally {
    await browser.close();
  }
  for (const r of results) console.log(JSON.stringify(r));
  process.exit(results.every((r) => r.ok) ? 0 : 1);
})();
