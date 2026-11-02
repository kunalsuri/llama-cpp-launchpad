// Opens the real setup page in a real browser (Chromium via Playwright) and checks what the fake-DOM harness cannot:
// layout, rendering and real DOM behaviour. Prints one JSON line per check: {"name", "ok", "detail"}.
// Driven by tests/test_browser.py, which starts the real server with a fake computer and no network.
// Usage: node tests/browser_check.js PORT
//
// Why: the page once rendered 835 px wide on a 390 px phone (the header could not wrap) and printed the word "null"
// in tool cards. Both passed every fake-DOM scenario. Each check below names the rule it protects.
"use strict";
const { chromium } = require("playwright");

const BASE = `http://127.0.0.1:${process.argv[2]}/`;
const WIDTHS = [[360, 740, "phone"], [768, 1024, "tablet"], [1280, 900, "desktop"]];
const VIEWS = { "": "#tiles .tile", "#tools": "#tools-list .tool", "#radar": "#radar-list .m-card, #radar-list .empty", "#history": "#history-content .card, #history-content .empty",
  "#llama": "#llama-body .btn, #llama-body .note" };
const results = [];
const check = (name, detail) => results.push({ name, ok: !detail, detail: detail || "" });

// Everything that can be judged from one rendered view.
async function inspect(page, phone) {
  return page.evaluate((phone) => {
    const problems = [];
    const doc = document.documentElement;
    if (doc.scrollWidth > doc.clientWidth + 1) {
      const wide = [...document.querySelectorAll("body *")].filter((e) => e.getBoundingClientRect().right > doc.clientWidth + 1 && e.offsetParent !== null);
      const culprit = wide.find((e) => ![...e.children].some((c) => wide.includes(c))) || wide[0];
      // Content that spills out of its own box (a label that cannot wrap) leaves the box narrow: name it too.
      // Scrollers (the nav) are skipped: their overflow is meant to scroll.
      const spill = [...document.querySelectorAll("body *")].filter((e) => e.offsetParent !== null && e.scrollWidth > e.clientWidth + 1
        && e.clientWidth > 0 && !["auto", "scroll", "hidden"].includes(getComputedStyle(e).overflowX) && !e.closest("nav"));
      const leaf = spill.find((e) => ![...e.children].some((c) => spill.includes(c)));
      problems.push(`page scrolls sideways: ${doc.scrollWidth}px wide in a ${doc.clientWidth}px window` +
        (culprit ? ` (widest: <${culprit.tagName.toLowerCase()} class="${culprit.className}">)` : "") +
        (leaf ? ` (content spills out of <${leaf.tagName.toLowerCase()} class="${leaf.className}">: "${(leaf.innerText || "").slice(0, 40)}")` : ""));
    }
    const text = document.body.innerText;
    const leaked = text.match(/\b(null|undefined|NaN|\[object Object\])\b/);
    if (leaked) problems.push(`"${leaked[0]}" is shown on the page`);
    const visible = (e) => e.offsetParent !== null && getComputedStyle(e).visibility !== "hidden";
    for (const b of document.querySelectorAll("button, a[href], select, input")) {
      if (!visible(b)) continue;
      const name = (b.getAttribute("aria-label") || b.innerText || b.value || b.placeholder || b.title || "").trim()
        || (b.labels && b.labels[0] && b.labels[0].innerText.trim());
      if (!name) problems.push(`a <${b.tagName.toLowerCase()}> has no accessible name: ${b.outerHTML.slice(0, 80)}`);
      if (phone && b.matches(".btn, .nav, .tab, .copy-btn, .theme-btn, .tile")) {
        const r = b.getBoundingClientRect();
        if (r.height < 32) problems.push(`tap target ${Math.round(r.height)}px high: "${name}"`);
      }
    }
    return problems;
  }, phone);
}

async function openView(page, hash) {
  await page.goto("about:blank");
  await page.goto(BASE + hash);
  await page.waitForSelector(VIEWS[hash], { state: "visible", timeout: 15000 });
  await page.waitForLoadState("networkidle");
}

// Start chatting, end to end against the real server and a fake llama-server: done -> Start -> running -> Stop.
async function chatFlow(browser) {
  for (const [width, height, label] of [WIDTHS[0], WIDTHS[2]]) {
    const name = `${label} ${width}px: start chatting, open the chat, stop it`;
    const page = await browser.newPage({ viewport: { width, height } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    let problems = [];
    try {
      await openView(page, "");
      await page.getByRole("button", { name: /General chat/ }).click();
      await page.waitForSelector("#v-pick:not([hidden]) .pick");
      await page.getByRole("button", { name: /Get this model|Use this model/ }).click();
      await page.waitForSelector("#v-done:not([hidden])", { timeout: 15000 });
      await page.getByRole("button", { name: "Start chatting" }).click();
      const link = page.getByRole("link", { name: "Open the chat" });
      await link.waitFor({ timeout: 30000 });
      problems = problems.concat(await inspect(page, label === "phone"));
      const href = await link.getAttribute("href");
      const health = await page.request.get(href + "health");
      if (health.status() !== 200) problems.push(`the chat link ${href} does not answer: ${health.status()}`);
      await page.locator("#chat-box").getByRole("button", { name: "Stop" }).click();
      await page.locator("#chat-box").getByText("The chat server is stopped.").waitFor({ timeout: 15000 });
      problems = problems.concat(await inspect(page, label === "phone"));
    } catch (e) { problems.push("flow broke: " + e.message.split("\n")[0]); }
    check(name, [...problems, ...errors].join("; "));
    await page.close();
  }
}

(async () => {
  const browser = await chromium.launch();
  if (process.argv[3] === "chat") {
    try { await chatFlow(browser); } finally { await browser.close(); }
    for (const r of results) console.log(JSON.stringify(r));
    process.exit(results.length && results.every((r) => r.ok) ? 0 : 1);
  }
  try {
    for (const [width, height, label] of WIDTHS) {
      for (const scheme of ["light", "dark"]) {
        const page = await browser.newPage({ viewport: { width, height }, colorScheme: scheme });
        const errors = [];
        page.on("pageerror", (e) => errors.push(String(e)));
        page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
        for (const hash of Object.keys(VIEWS)) {
          const name = `${label} ${width}px ${scheme}: ${hash || "#home"}`;
          try {
            await openView(page, hash);
            const problems = await inspect(page, label === "phone");
            check(name, [...problems, ...errors.splice(0)].join("; "));
          } catch (e) { check(name, "did not render: " + e.message.split("\n")[0]); }
        }
        await page.close();
      }
    }

    // The whole wizard, at the smallest and largest width: choose -> pick -> copy -> download -> done -> get llama.cpp.
    // (This server has no llama.cpp, so the done screen offers to install it rather than a command to copy.)
    for (const [width, height, label] of [WIDTHS[0], WIDTHS[2]]) {
      const name = `${label} ${width}px: choose, copy a command, download, then go to install llama.cpp and back`;
      const context = await browser.newContext({ viewport: { width, height } });
      await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: BASE.slice(0, -1) });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (e) => errors.push(String(e)));
      try {
        await openView(page, "");
        await page.getByRole("button", { name: /General chat/ }).click();
        await page.waitForSelector("#v-pick:not([hidden]) .pick");
        let problems = await inspect(page, label === "phone");
        await page.locator("#top details.terminal summary").click();
        const copy = page.locator("#top .copy-btn").first();
        await copy.click();
        await page.waitForFunction(() => /Copied/.test(document.querySelector("#top .copy-btn").innerText));
        const pasted = await page.evaluate(() => navigator.clipboard.readText());
        const shown = await page.locator("#top code").first().innerText();
        if (pasted !== shown) problems.push(`copied ${JSON.stringify(pasted)} but the page shows ${JSON.stringify(shown)}`);
        await page.getByRole("button", { name: /Get this model|Use this model/ }).click();
        await page.waitForSelector("#v-done:not([hidden])", { timeout: 15000 });
        problems = problems.concat(await inspect(page, label === "phone"));
        await page.locator("#done-next").getByRole("button", { name: "Install llama.cpp" }).click();
        await page.waitForSelector("#v-llama:not([hidden]) #llama-body .btn", { timeout: 15000 });
        problems = problems.concat(await inspect(page, label === "phone"));
        await page.locator("#llama-back").click();
        await page.waitForSelector("#v-done:not([hidden])", { timeout: 5000 });
        check(name, [...problems, ...errors].join("; "));
      } catch (e) { check(name, "flow broke: " + e.message.split("\n")[0]); }
      await context.close();
    }

    // Real browser history (the harness models it; this proves the browser agrees).
    {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      let detail = "";
      try {
        await openView(page, "");
        await page.getByRole("button", { name: "Model radar" }).click();
        await page.waitForSelector("#v-radar:not([hidden])");
        await page.getByRole("button", { name: "Installed tools" }).click();
        await page.waitForSelector("#v-tools:not([hidden])");
        await page.goBack();
        await page.waitForSelector("#v-radar:not([hidden])", { timeout: 5000 });
        await page.goBack();
        await page.waitForSelector("#v-use:not([hidden])", { timeout: 5000 });
        await page.goForward();
        await page.waitForSelector("#v-radar:not([hidden])", { timeout: 5000 });
      } catch (e) { detail = "browser Back did not move between views: " + e.message.split("\n")[0]; }
      check("browser Back and Forward in a real browser", detail);
      await page.close();
    }
  } finally {
    await browser.close();
  }
  for (const r of results) console.log(JSON.stringify(r));
  process.exit(results.every((r) => r.ok) ? 0 : 1);
})().catch((e) => { console.log(JSON.stringify({ name: "browser check", ok: false, detail: String(e && e.stack || e) })); process.exit(1); });
