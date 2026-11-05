// Draws what capture.py cannot draw with ffmpeg alone. Prints one JSON object per line.
//
//   node tools/docs-media/render.js card OUT.png "TEXT"
//       A title card for a sped-up stretch of a video ("Downloading took 3 min 12 s. Shown 32x faster.").
//   node tools/docs-media/render.js cast IN.cast WORKDIR LAST.png
//       Plays an asciicast v2 recording in xterm.js (a real terminal emulator, the one VS Code uses) and records it,
//       so colours, cursor moves and redrawn menus look as they did. Pauses longer than the file's idle_time_limit
//       are shortened to it. -> {"webm", "start", "size"}; capture.py cuts the video from "start".
"use strict";
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const ROOT = path.resolve(__dirname, "..", "..");
const XTERM = path.join(ROOT, "node_modules", "@xterm", "xterm");
const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

async function card(browser, out, text, width, height) {
  const page = await browser.newPage({ viewport: { width: Number(width) || 1280, height: Number(height) || 800 } });
  await page.setContent(`<!doctype html><meta charset="utf-8"><body style="margin:0;height:100vh;display:grid;
    place-items:center;background:#1f2328;color:#f0f3f6;font:600 34px system-ui,sans-serif">
    <div style="text-align:center;max-width:960px;line-height:1.4">${esc(text)}
    <div style="margin-top:28px;font:400 18px system-ui,sans-serif;color:#9198a1">Card added by
    tools/docs-media/capture.py. Everything else in this video is recorded as it happened.</div></div></body>`);
  await page.screenshot({ path: out });
  await page.close();
  console.log(JSON.stringify({ png: out }));
}

async function cast(browser, file, work, last) {
  const lines = fs.readFileSync(file, "utf8").trim().split("\n").map((l) => JSON.parse(l));
  const head = lines[0];
  const idle = head.idle_time_limit || Infinity;
  let t = 0, prev = 0;
  const events = lines.slice(1).map(([at, , data]) => { t += Math.min(at - prev, idle); prev = at; return [t, data]; });
  const size = { width: 1000, height: 600 };
  const ctx = await browser.newContext({ viewport: size, deviceScaleFactor: 2, recordVideo: { dir: work, size } });
  const page = await ctx.newPage();
  const t0 = Date.now();
  await page.setContent(`<!doctype html><meta charset="utf-8"><body style="margin:0;background:#1f2328;
    height:100vh;display:grid;place-items:center"><div id="t"></div></body>`);
  await page.addStyleTag({ path: path.join(XTERM, "css", "xterm.css") });
  await page.addScriptTag({ path: path.join(XTERM, "lib", "xterm.js") });
  await page.evaluate(({ cols, rows }) => {
    window.term = new Terminal({ cols, rows, fontSize: 16, fontFamily: "DejaVu Sans Mono, Menlo, Consolas, monospace",
      theme: { background: "#1f2328", foreground: "#e6edf3" }, cursorBlink: false, convertEol: false });
    window.term.open(document.getElementById("t"));
  }, { cols: head.width, rows: head.height });
  const fits = await page.evaluate(() => {
    const r = document.querySelector(".xterm-screen").getBoundingClientRect();
    return r.width <= innerWidth && r.height <= innerHeight;
  });
  if (!fits) throw new Error(`a ${head.width}x${head.height} terminal does not fit in ${size.width}x${size.height}`);
  await page.waitForTimeout(500);
  const start = (Date.now() - t0) / 1000;
  await page.evaluate((events) => new Promise((done) => {
    const begin = performance.now();
    let i = 0;
    (function next() {
      while (i < events.length && events[i][0] * 1000 <= performance.now() - begin) window.term.write(events[i++][1]);
      if (i < events.length) setTimeout(next, 10); else window.term.write("", () => setTimeout(done, 1500));
    })();
  }), events);
  await page.screenshot({ path: last });
  const video = page.video();
  await ctx.close();
  console.log(JSON.stringify({ webm: await video.path(), start, size: [size.width, size.height] }));
}

(async () => {
  const [mode, ...args] = process.argv.slice(2);
  const browser = await chromium.launch();
  try {
    if (mode === "card") await card(browser, args[0], args[1], args[2], args[3]);
    else if (mode === "cast") await cast(browser, args[0], args[1], args[2]);
    else throw new Error(`unknown mode ${mode}`);
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e.stack || String(e)); process.exit(1); });
