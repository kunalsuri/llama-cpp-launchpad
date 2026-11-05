// Drives the real pages in Chromium (Playwright) and records what a person would see. Run by capture.py, which starts
// the servers first; prints one JSON object per line: a screenshot {"file", "kind", "shows"} or a recording
// {"name", "webm", "shows", "length", "waits": [{"what", "start", "end"}]} that capture.py turns into MP4 and GIF.
//
// Usage: node tools/docs-media/scenes.js setup-page BASE WORK OUT setup,views
//        node tools/docs-media/scenes.js tasks|translation LLAMA_SERVER_URL WORK OUT
//
// Nothing on the page is changed. Text typed into the pages comes from this project's own files (named below), so
// what a model is asked is real, and its replies are shown exactly as it wrote them.
"use strict";
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [mode, BASE, WORK, OUT, which = ""] = process.argv.slice(2);
const ROOT = path.resolve(__dirname, "..", "..");
const SIZE = { width: 1280, height: 800 };
const LONG = 3600 * 1000;                 // a download on a slow line can take most of an hour
const say = (obj) => console.log(JSON.stringify(obj));
const pause = (ms) => new Promise((r) => setTimeout(r, ms));

async function recorded(browser, name) {
  const ctx = await browser.newContext({ viewport: SIZE, deviceScaleFactor: 2, colorScheme: "light",
    recordVideo: { dir: path.join(WORK, name), size: SIZE } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const t0 = Date.now();
  const rec = { ctx, page, name, waits: [], errors, at: () => (Date.now() - t0) / 1000 };
  // A wait: time spent on something slow (a download, a model loading), which capture.py may speed up and label.
  rec.wait = async (what, promise) => {
    const start = rec.at();
    const value = await promise;
    rec.waits.push({ what, start, end: rec.at() });
    return value;
  };
  return rec;
}

async function finish(rec, shows) {
  const video = rec.page.video();
  const length = rec.at();
  await rec.ctx.close();                                   // the video file is complete only after this
  if (rec.errors.length) throw new Error(`${rec.name}: the page reported errors: ${rec.errors.join("; ")}`);
  say({ name: rec.name, webm: await video.path(), shows, length, waits: rec.waits, size: [SIZE.width, SIZE.height] });
}

async function shot(page, file, shows, full = false) {
  await page.screenshot({ path: path.join(OUT, file), fullPage: full });
  say({ file, kind: "screenshot", shows });
}

// A chat request to llama-server, followed to its last streamed byte.
async function reply(page, send) {
  const done = page.waitForResponse((r) => r.url().includes("/v1/chat/completions"), { timeout: LONG });
  await send();
  const res = await done;
  await res.finished();
  if (res.status() !== 200) throw new Error(`llama-server answered ${res.status()}: ${await res.text()}`);
}

async function setupPage(browser) {
  if (which.includes("setup")) {
    const rec = await recorded(browser, "setup-walkthrough");
    const { page } = rec;
    await page.goto(BASE);
    await page.waitForSelector("#tiles .tile", { state: "visible" });
    await pause(2000);
    await shot(page, "setup-1-use.png", "The setup page's first screen: What will you use it for?");
    await page.getByRole("button", { name: /General chat/ }).click();
    await rec.wait("Finding models that fit", page.waitForSelector("#v-pick:not([hidden]) .pick", { timeout: 300000 }));
    await pause(2500);
    await shot(page, "setup-2-pick.png", "The model recommended for this computer, with what it needs and why");
    const get = page.getByRole("button", { name: /Get this model|Use this model/ }).first();
    const downloading = /Get/.test(await get.innerText());
    await get.click();
    if (downloading) {
      await page.waitForSelector("#v-install:not([hidden])");
      await pause(4000);
      await shot(page, "setup-3-download.png", "Downloading the model: progress, then a checksum check and a speed test");
    }
    await rec.wait(downloading ? "Downloading, checking and speed-testing the model" : "Speed-testing the model",
      page.waitForSelector("#v-done:not([hidden])", { timeout: LONG }));
    await pause(3000);
    await shot(page, "setup-4-done.png", "Ready: the measured speed, the presets with the memory each needs, Start chatting", true);
    await page.getByRole("button", { name: "Start chatting" }).click();
    const link = page.getByRole("link", { name: "Open the chat" });
    await rec.wait("Loading the model into memory", link.waitFor({ timeout: 900000 }));
    await pause(2500);
    await shot(page, "setup-5-running.png", "The chat is running: its address, Stop, and settings for other programs", true);
    const href = await link.getAttribute("href");
    await page.goto(href);
    const box = page.locator("textarea").first();
    await box.waitFor({ timeout: 60000 });
    await pause(1500);
    await box.click();
    await page.keyboard.type("Write a haiku about running an AI model on your own computer.", { delay: 35 });
    await rec.wait("Writing the reply", reply(page, () => page.keyboard.press("Enter")));
    await pause(3000);
    await shot(page, "chat-default.png", "llama.cpp's built-in chat, answering on this computer (the reply is unedited)");
    await finish(rec, "From the setup page to a first reply: choose a use, get the recommended model, start chatting");
  }
  if (which.includes("views")) {
    const views = [["#tools", "#tools-list .tool", "views-tools.png", "Installed tools: what was found on this computer, and how to start each"],
      // With a working llama-server there is no button, only what was found: wait for "Checking…" to be replaced.
      ["#llama", "#llama-body > :not(p.muted:only-child)", "views-llama.png", "Get llama.cpp: the llama-server found, or the build to install"],
      ["#models", "#models-list .tool, #models-sum", "views-models.png", "My models: size, origin, free disk; compare and serve all"],
      ["#radar", "#radar-list .m-card, #radar-list .empty", "views-radar.png", "Model radar: new and trending GGUF models that fit this computer"]];
    const ctx = await browser.newContext({ viewport: SIZE, deviceScaleFactor: 2, colorScheme: "light" });
    const page = await ctx.newPage();
    for (const [hash, ready, file, shows] of views) {
      await page.goto("about:blank");
      await page.goto(BASE + hash);
      await page.waitForSelector(ready, { state: "visible", timeout: 300000 });
      await page.waitForLoadState("networkidle");
      await pause(1000);
      await shot(page, file, shows, true);
    }
    await ctx.close();
  }
}

// What the Tasks page is given: this project's own words and code, read from the files when the scene runs.
function readmeParagraphs() {
  const readme = fs.readFileSync(path.join(ROOT, "README.md"), "utf8");
  const intro = readme.slice(readme.indexOf("A launcher for"), readme.indexOf("```", readme.indexOf("A launcher for")));
  const not = readme.slice(readme.indexOf("**What it is not:**"), readme.indexOf("## Contents"));
  return (intro + "\n" + not).replace(/\*\*/g, "").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").trim();
}

function pythonFunction(file, name) {
  const src = fs.readFileSync(path.join(ROOT, file), "utf8");
  const start = src.indexOf(`def ${name}(`);
  if (start < 0) throw new Error(`${file} has no function ${name}`);
  const rest = src.slice(start);
  const end = rest.search(/\n(?=\S)/);
  return (end < 0 ? rest : rest.slice(0, end)).trimEnd();
}

async function tasks(browser) {
  const jobs = [["summarize", "short", readmeParagraphs(), "Summarizing", "tasks-summarize.png",
    "Tasks, Summarize: this project's README introduction as a few bullet points (the model's unedited answer)"],
  ["explain", "beginner", pythonFunction("utils/model_setup.py", "upgrade_label"), "Explaining", "tasks-explain.png",
    "Tasks, Explain code, for a beginner: a function from utils/model_setup.py (the model's unedited answer)"],
  ["rewrite", "plain", "Every download (page, model-setup, radar --download) is checked against the SHA-256 Hugging Face " +
    "publishes for the file; a file that does not match is not kept.", "Rewriting", "tasks-rewrite.png",
    "Tasks, Rewrite, plainer: a sentence from docs/setup-page.md (the model's unedited answer)"]];
  const rec = await recorded(browser, "tasks-demo");
  const { page } = rec;
  await page.goto(BASE);
  await page.waitForSelector("#text");
  await page.waitForFunction(() => document.getElementById("model").textContent.trim() !== "");
  await pause(1500);
  for (const [task, option, text, what, file, shows] of jobs) {
    await page.click(`#tasks button[data-task="${task}"]`);
    await pause(800);
    await page.selectOption("#option", option);
    await page.fill("#text", text);
    await pause(1200);
    await rec.wait(what, reply(page, () => page.click("#run")));
    await page.waitForFunction(() => document.getElementById("run-text").textContent === "Run");
    await pause(2500);
    await shot(page, file, shows, true);
  }
  await finish(rec, "The Tasks page: summarize, explain code and rewrite, with a model running on this computer");
}

async function translation(browser) {
  const rec = await recorded(browser, "translation-demo");
  const { page } = rec;
  await page.goto(BASE);
  await page.waitForSelector("#text");
  await pause(1500);
  await page.selectOption("#from", "English");
  await page.selectOption("#to", "French");
  await pause(800);
  await page.fill("#text", "");                            // the page opens with its own example text in the box
  await page.click("#text");
  await page.keyboard.type("The model runs on your machine; nothing is sent anywhere.", { delay: 35 });
  await pause(800);
  await rec.wait("Translating", reply(page, () => page.click("#send")));
  await pause(1500);
  await page.selectOption("#to", "Spanish");
  await page.fill("#text", "");
  await page.click("#text");
  await page.keyboard.type("Speeds it shows are measured on your machine.", { delay: 35 });
  await pause(800);
  await rec.wait("Translating", reply(page, () => page.click("#send")));
  await pause(2500);
  await shot(page, "translation.png", "The Translation page: two README sentences into French (formal) and Spanish (unedited)");
  await finish(rec, "The Translation page: English to French, then to Spanish, with a model running on this computer");
}

(async () => {
  const browser = await chromium.launch();
  try {
    if (mode === "setup-page") await setupPage(browser);
    else if (mode === "tasks") await tasks(browser);
    else if (mode === "translation") await translation(browser);
    else throw new Error(`unknown mode ${mode}`);
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e.stack || String(e)); process.exit(1); });
