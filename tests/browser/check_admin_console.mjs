// 真实浏览器验收：react-admin 管理后台（demo 内容）。
// 先起 BFF（空库 + demo 内容 + fake）：
//   CONTENT_DIR=demo DB_PATH=data/app-admin-demo.db PROVIDER_MODE=fake \
//     .venv/Scripts/python -m uvicorn bff.main:app --port 8799
// 再运行：
//   PLAYWRIGHT_CORE="D:/gstack/gstack-main/node_modules/playwright-core" \
//     BASE_URL="http://127.0.0.1:8799" node tests/browser/check_admin_console.mjs

import { pathToFileURL } from "node:url";

const configured = process.env.PLAYWRIGHT_CORE;
const moduleRef = configured
  ? pathToFileURL(
      configured.endsWith(".mjs")
        ? configured
        : `${configured.replace(/[\\/]$/, "")}/index.mjs`,
    ).href
  : "playwright-core";
const baseUrl = (process.env.BASE_URL || "http://127.0.0.1:8799").replace(
  /\/$/,
  "",
);
const { chromium } = await import(moduleRef);

const failures = [];
let checks = 0;
function check(name, ok, detail = "") {
  checks += 1;
  if (ok) console.log(`PASS  ${name}`);
  else {
    failures.push({ name, detail });
    console.log(`FAIL  ${name} — ${detail}`);
  }
}
function equal(name, actual, expected) {
  check(
    name,
    String(actual) === String(expected),
    `expected=${expected} actual=${actual}`,
  );
}
function includes(name, haystack, needle) {
  check(name, String(haystack).includes(needle), `missing=${needle}`);
}

const browser = await chromium.launch({
  headless: true,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
});
await context.grantPermissions(["clipboard-read", "clipboard-write"], {
  origin: baseUrl,
});
const page = await context.newPage();
const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));

async function bodyText() {
  return ((await page.textContent("body")) || "").replace(/\s+/g, " ");
}
async function gotoHash(hash) {
  await page.goto(`${baseUrl}/admin/${hash}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
}
async function rows() {
  return page.locator("tbody tr").count();
}

// 1. Dashboard
await gotoHash("#/");
equal("后台标题", await page.title(), "内容影响面 · 管理后台");
const dashboard = await bodyText();
includes("Dashboard 计数材料", dashboard, "材料2");
includes("Dashboard 计数题库题", dashboard, "题库题28");
includes("Dashboard DB 版本", dashboard, "DB v8/8");
check(
  "Dashboard 无 console error",
  consoleErrors.length === 0,
  consoleErrors.join(" | "),
);

// 2. 菜单 → 材料列表 → 详情 → 返回
await page.getByRole("link", { name: "材料", exact: true }).first().click();
await page.waitForURL(/#\/materials$/);
await page.waitForTimeout(500);
equal("材料列表行数", await rows(), 2);
const materialListText = await bodyText();
check("材料列表无删除", !materialListText.includes("删除"));
check("材料列表无导出", !materialListText.includes("导出"));

await page
  .locator("tbody tr", { hasText: "Agent-工具调用基础" })
  .first()
  .click();
await page.waitForURL(/#\/materials\/.+\/show/);
await page.waitForTimeout(800);
const material = await bodyText();
includes("材料详情标题", material, "Agent-工具调用基础");
includes("材料详情块数", material, "块8");
includes("材料详情父块", material, "父块2");
includes("材料详情概念数", material, "概念3");
includes("材料详情修复计划", material, "修复材料");
check(
  "材料详情有返回列表",
  (await page.locator("text=← 材料列表").count()) > 0,
);
await page.getByRole("button", { name: "← 材料列表" }).click();
await page.waitForURL(/#\/materials$/);
await page.waitForTimeout(300);
equal("返回材料列表", await rows(), 2);

// 3. 概念详情
await gotoHash("#/concepts/" + encodeURIComponent("切块") + "/show");
const concept = await bodyText();
includes("概念标题", concept, "切块");
includes("概念出处", concept, "出处1");
includes("概念题库题", concept, "题库题5");
includes("概念后继", concept, "后继概念2");

// 4. 题库题详情
await gotoHash("#/bank-questions/" + encodeURIComponent("切块-1") + "/show");
const bank = await bodyText();
includes("题库题 URL 级", bank, "URL 级");
includes("题库题使用记录", bank, "使用记录");

// 5. 全局搜索
await gotoHash("#/search");
await page.fill('input[type="text"]', "切块");
await page.waitForTimeout(1200);
includes("全局搜索有结果", await bodyText(), "切块");

check(
  "全流程无 console error",
  consoleErrors.length === 0,
  consoleErrors.join(" | "),
);

await browser.close();
console.log(`\n${checks - failures.length}/${checks} checks passed`);
if (failures.length) {
  for (const item of failures) console.log(`FAIL  ${item.name} — ${item.detail}`);
  process.exit(1);
}
