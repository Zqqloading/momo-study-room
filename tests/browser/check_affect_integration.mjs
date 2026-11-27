// 手动浏览器验收：情绪状态进入待机表情 + 开场拼入用户记忆。
// 先准备隔离 DB 并写入一条记忆与一条情绪状态，再启动 fake 模式 BFF：
//   DB_PATH=<tmp>/qa.db DATA_DIR=<tmp>/data CONTENT_DIR=<tmp>/empty \
//     PROVIDER_MODE=fake TTS_KIND=fake ASR_KIND=fake SEARCH_KIND=off AGENT_HARNESS=off \
//     .venv/Scripts/python -m uvicorn bff.main:app --host 127.0.0.1 --port 8799
// 再运行：
//   PLAYWRIGHT_CORE="D:/gstack/gstack-main/node_modules/playwright-core" \
//     BASE_URL="http://127.0.0.1:8799" node tests/browser/check_affect_integration.mjs

import { pathToFileURL } from "node:url";

const configured = process.env.PLAYWRIGHT_CORE;
const moduleRef = configured
  ? pathToFileURL(
      configured.endsWith(".mjs")
        ? configured
        : `${configured.replace(/[\\/]$/, "")}/index.mjs`,
    ).href
  : "playwright-core";
const baseUrl = process.env.BASE_URL || "http://127.0.0.1:8799";
const { chromium } = await import(moduleRef);

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("console", (message) => {
  if (message.type() === "error") errors.push(message.text());
});
page.on("pageerror", (error) => errors.push(String(error)));

const problems = [];

function expect(name, condition, detail) {
  if (!condition) problems.push(`${name}: ${detail}`);
}

try {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => (document.querySelector("#status")?.textContent || "").includes("已就绪"),
    null,
    { timeout: 30000 },
  );
  await page.waitForFunction(
    () => window.__emotionFace?.snapshot().hasVrm === true,
    null,
    { timeout: 30000 },
  );

  const mood = await page.evaluate(() => window.__emotionFace.snapshot().mood);
  expect("seeded comfort", Math.abs(mood.comfort - 0.8) < 0.05, JSON.stringify(mood));
  expect("seeded energy", Math.abs(mood.energy - 0.9) < 0.05, JSON.stringify(mood));

  await page.click("#start");
  await page.waitForFunction(
    () => (document.querySelector("#intro")?.textContent || "").includes("先想起几件你说过的事"),
    null,
    { timeout: 30000 },
  );
  const intro = await page.locator("#intro").innerText();
  expect("memory line", intro.includes("更习惯先看例子"), intro);
  expect("memory before progress", intro.indexOf("先想起") < intro.indexOf("今天从"), intro);

  console.log(JSON.stringify({ mood, intro, errors, problems }, null, 2));
  if (problems.length || errors.length) process.exitCode = 1;
} finally {
  await browser.close();
}
