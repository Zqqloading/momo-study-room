// 手动浏览器验收：网页来源显示与刷新回看。
// 先启动 fake 模式 BFF（FakeSearch 会返回一条可过滤的网页结果）：
//   PROVIDER_MODE=fake DB_PATH=data/test-web-ui.db \
//     .venv/Scripts/python -m uvicorn bff.main:app --port 8797
// 再运行：
//   PLAYWRIGHT_CORE="D:/gstack/gstack-main/node_modules/playwright-core" \
//     BASE_URL="http://127.0.0.1:8797" node tests/browser/check_web_sources.mjs

import { pathToFileURL } from "node:url";

const configured = process.env.PLAYWRIGHT_CORE;
const moduleRef = configured
  ? pathToFileURL(
      configured.endsWith(".mjs")
        ? configured
        : `${configured.replace(/[\\/]$/, "")}/index.mjs`,
    ).href
  : "playwright-core";
const baseUrl = process.env.BASE_URL || "http://127.0.0.1:8797";
const { chromium } = await import(moduleRef);

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("console", (message) => {
  if (message.type() === "error") errors.push(message.text());
});
page.on("pageerror", (error) => errors.push(String(error)));

try {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => (document.querySelector("#status")?.textContent || "").includes("已就绪"),
    null,
    { timeout: 30000 },
  );
  await page.click("#newconversation");
  await page.waitForTimeout(500);
  await page.fill("#textinput", "最新的 agent 版本");
  await page.press("#textinput", "Enter");
  await page.waitForSelector(".chat-source-web", { timeout: 60000 });
  const source = await page.locator(".chat-source-web").last().innerText();
  const link = await page.locator(".chat-source-web .chat-source-link").last();
  const href = await link.getAttribute("href");

  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForSelector(".chat-source-web", { timeout: 30000 });
  const persisted = await page.locator(".chat-source-web").last().innerText();

  console.log(JSON.stringify({ source, href, persisted, errors }, null, 2));
  if (!href?.startsWith("http") || errors.length) process.exitCode = 1;
} finally {
  await browser.close();
}
