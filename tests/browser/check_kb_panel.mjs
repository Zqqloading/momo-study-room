// 手动/本地浏览器验收：知识库面板、提议、掌握程度与结果卡。
// 面板请求用 page.route 模拟；WebSocket 用假实现注入事件。
// 先启动静态服务：
//   PROVIDER_MODE=fake DB_PATH=data/test-kb.db \
//     .venv/Scripts/python -m uvicorn bff.main:app --port 8799
// 再运行：
//   PLAYWRIGHT_CORE="D:/gstack/gstack-main/node_modules/playwright-core" \
//     BASE_URL="http://127.0.0.1:8799" node tests/browser/check_kb_panel.mjs

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

const overview = {
  date: "2026-11-25",
  stats: {
    active: 3,
    known: 0,
    skipped: 0,
    proposed: 0,
    orphaned: 0,
    avg_mastery: 0.7,
    distribution: [
      { mastery: 0, label: "未掌握", count: 2 },
      { mastery: 1, label: "初识", count: 1 },
      { mastery: 2, label: "有印象", count: 0 },
      { mastery: 3, label: "基本掌握", count: 0 },
      { mastery: 4, label: "熟练", count: 0 },
      { mastery: 5, label: "精通", count: 0 },
    ],
    due: 1,
    overdue: 0,
    weak: 1,
  },
  concepts: [
    {
      id: "agent-loop",
      name: "Agent 循环",
      plain_def: "反复观察、行动、检查。",
      mastery: 1,
      mastery_label: "初识",
      status: "active",
      last_seen: "2026-11-20",
      review_due_at: null,
      overdue_days: 0,
    },
    {
      id: "memory",
      name: "记忆",
      plain_def: "保存跨轮次信息。",
      mastery: 0,
      mastery_label: "未掌握",
      status: "active",
      last_seen: null,
      review_due_at: null,
      overdue_days: 0,
    },
  ],
  recent_units: [
    {
      session_id: "s0",
      date: "2026-11-24",
      kind: "daily",
      status: "completed",
      session_score: 76,
      concept_names: ["Agent 循环"],
    },
    {
      session_id: "s-1",
      date: "2026-11-23",
      kind: "review",
      status: "partial",
      session_score: 62,
      concept_names: ["工具调用"],
    },
  ],
};

const proposal = {
  available: true,
  date: "2026-11-25",
  kind: "daily",
  estimate_minutes: 20,
  question_count: 5,
  deferred_reviews: 0,
  main: {
    id: "agent-loop",
    name: "Agent 循环",
    plain_def: "反复观察、行动、检查。",
    difficulty: 1,
    mastery: 1,
    mastery_label: "初识",
    last_seen: "2026-11-20",
    review_due_at: null,
    overdue_days: 0,
    last_score: 70,
    prerequisites: [],
    reason: "上次学过 2026-11-20，已 5 天没学；当前可解锁概念里难度最低（难度 1）",
  },
  review: null,
  same_concept: false,
  slots: [
    { slot: 1, type: "concept", label: "概念理解", role: "new", concept_id: "agent-loop" },
    { slot: 2, type: "business", label: "业务运用", role: "new", concept_id: "agent-loop" },
    { slot: 3, type: "tradeoff", label: "取舍权衡", role: "new", concept_id: "agent-loop" },
    { slot: 4, type: "cost_risk", label: "成本风险", role: "new", concept_id: "agent-loop" },
    { slot: 5, type: "synthesis", label: "综合判断", role: "new", concept_id: "agent-loop" },
  ],
};

const question = {
  type: "question",
  id: 1,
  role: "new",
  kind: "apply",
  question_type: "concept",
  origin: "generated",
  text: "用你自己的话说说 Agent 循环。",
  options: null,
  index: 1,
  total: 5,
};

const result = {
  type: "session_result",
  session_id: "s1",
  status: "completed",
  session_score: 78,
  mastery: { "agent-loop": 2 },
  review_due_at: null,
  concepts: [
    {
      id: "agent-loop",
      name: "Agent 循环",
      roles: ["new"],
      new_score: 78,
      review_score: null,
      mastery_before: 1,
      mastery_before_label: "初识",
      mastery_after: 2,
      mastery_after_label: "有印象",
      mastery_updated: true,
      review_due_at: null,
    },
  ],
  scores: [
    {
      question_id: 1,
      score: 78,
      why: "方向对，但没说清检查条件",
      question_type: "concept",
      source_url: "fixture://agent-loop",
      source_excerpt: "Agent 通过观察环境、选择行动并执行。",
    },
  ],
};

let proposalMode = "ok";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("console", (message) => {
  if (message.type() === "error") errors.push(message.text());
});
page.on("pageerror", (error) => errors.push(String(error)));

await page.route("**/api/kb/**", async (route) => {
  const url = route.request().url();
  if (url.endsWith("/api/kb/overview")) {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(overview),
    });
    return;
  }
  if (proposalMode === "error") {
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ error: "模拟读取失败" }),
    });
    return;
  }
  const body =
    proposalMode === "unavailable"
      ? {
          available: false,
          date: "2026-11-25",
          reason: "没有可解锁的新概念，也没有到期复习",
        }
      : proposal;
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
});

await page.addInitScript(
  ({ fakeQuestion }) => {
    window.__sent = [];
    class FakeWebSocket {
      static OPEN = 1;
      static CLOSED = 3;
      constructor(url) {
        this.url = url;
        this.readyState = 1;
        window.__socket = this;
        setTimeout(() => {
          this.onopen?.();
          this.onmessage?.({
            data: JSON.stringify({
              type: "ready",
              modes: { llm: "fake", scorer: "fake" },
              notes: [],
            }),
          });
        }, 0);
      }
      send(raw) {
        const message = JSON.parse(raw);
        window.__sent.push(message);
        if (message.type === "conversation_list") {
          this.onmessage?.({
            data: JSON.stringify({
              type: "conversation_list",
              items: [{ conversation_id: "c1", title: "t" }],
            }),
          });
        } else if (message.type === "session_start") {
          this.onmessage?.({
            data: JSON.stringify({
              type: "session_ready",
              session_id: "s1",
              kind: "daily",
              unit: {
                kind: "daily",
                main: { id: "agent-loop", name: "Agent 循环" },
                review: null,
              },
              question: fakeQuestion,
            }),
          });
        }
      }
      close() {
        this.readyState = 3;
      }
    }
    window.WebSocket = FakeWebSocket;
  },
  { fakeQuestion: question },
);

const checks = {};
try {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => (document.querySelector("#status")?.textContent || "").includes("已就绪"),
    null,
    { timeout: 30000 },
  );

  await page.click("#knowledge");
  await page.waitForFunction(
    () => (document.querySelector("#kbtoday")?.textContent || "").includes("Agent 循环"),
    null,
    { timeout: 10000 },
  );
  const todayText = await page.locator("#kbtoday").innerText();
  const progressText = await page.locator("#kbprogress").innerText();
  const historyText = await page.locator("#kbhistory").innerText();
  checks.proposalMain = todayText.includes("主学") && todayText.includes("Agent 循环");
  checks.proposalSlots = todayText.includes("概念理解") && todayText.includes("综合判断");
  checks.proposalReason = todayText.includes("难度最低");
  checks.overviewStats = progressText.includes("在学 3 个") && progressText.includes("平均 0.7 / 5");
  checks.overviewConcepts = progressText.includes("Agent 循环") && progressText.includes("记忆");
  checks.history = historyText.includes("最近单元") && historyText.includes("提前结束");
  checks.startEnabled = await page.locator("#kbstart").isEnabled();

  proposalMode = "unavailable";
  await page.click("#kbclose");
  await page.click("#knowledge");
  await page.waitForFunction(
    () => (document.querySelector("#kbtoday")?.textContent || "").includes("没有可解锁"),
    null,
    { timeout: 10000 },
  );
  checks.unavailable = (await page.locator("#kbstart").count()) === 0;

  proposalMode = "error";
  await page.click("#kbclose");
  await page.click("#knowledge");
  await page.waitForFunction(
    () => (document.querySelector("#kbtoday")?.textContent || "").includes("读取失败"),
    null,
    { timeout: 10000 },
  );
  checks.errorRetry = (await page.locator("#kbtoday .kb-retry").count()) === 1;
  proposalMode = "ok";
  await page.click("#kbtoday .kb-retry");
  await page.waitForFunction(
    () => (document.querySelector("#kbtoday")?.textContent || "").includes("Agent 循环"),
    null,
    { timeout: 10000 },
  );
  checks.retryRecovered = true;

  await page.click("#kbstart");
  await page.waitForFunction(
    () => (document.querySelector("#unitlabel")?.textContent || "").includes("今日单元"),
    null,
    { timeout: 10000 },
  );
  checks.unitLabel = (await page.locator("#unitlabel").innerText()).includes(
    "Agent 循环",
  );
  checks.sessionStarted = (await page.evaluate(() => window.__sent)).some(
    (message) => message.type === "session_start",
  );

  await page.click("#knowledge");
  await page.waitForFunction(
    () => (document.querySelector("#kbstart")?.textContent || "").includes("当前单元进行中"),
    null,
    { timeout: 10000 },
  );
  checks.activeSessionBlocksStart = await page.locator("#kbstart").isDisabled();
  await page.click("#kbclose");

  await page.evaluate((payload) => {
    window.__socket.onmessage({ data: JSON.stringify(payload) });
  }, result);
  await page.waitForFunction(
    () => (document.querySelector("#result")?.textContent || "").includes("查看知识库"),
    null,
    { timeout: 10000 },
  );
  await page.waitForFunction(
    () => (document.querySelector("#kbsummaryline")?.textContent || "").includes("在学 3 个"),
    null,
    { timeout: 10000 },
  );
  const resultText = await page.locator("#result").innerText();
  checks.resultBeforeAfter = resultText.includes("掌握度 1 → 2");
  checks.resultNoteAbsent = !resultText.includes("掌握度未更新");
  checks.resultOverview = resultText.includes("全库：在学 3 个");
  checks.noRawMastery = !resultText.includes("mastery");

  const partialResult = {
    ...result,
    status: "partial",
    session_score: 70,
    concepts: [
      {
        ...result.concepts[0],
        mastery_after: 1,
        mastery_after_label: "初识",
        mastery_updated: false,
      },
    ],
  };
  await page.evaluate((payload) => {
    window.__socket.onmessage({ data: JSON.stringify(payload) });
  }, partialResult);
  await page.waitForFunction(
    () => (document.querySelector("#result")?.textContent || "").includes("本单元未完成"),
    null,
    { timeout: 10000 },
  );
  const partialText = await page.locator("#result").innerText();
  checks.partialNote = partialText.includes("掌握度未更新");

  const unscoredResult = {
    ...result,
    status: "unscored",
    session_score: null,
    concepts: [
      {
        ...result.concepts[0],
        new_score: null,
        mastery_after: 1,
        mastery_after_label: "初识",
        mastery_updated: false,
      },
    ],
    scores: [],
  };
  await page.evaluate((payload) => {
    window.__socket.onmessage({ data: JSON.stringify(payload) });
  }, unscoredResult);
  await page.waitForFunction(
    () => (document.querySelector("#result")?.textContent || "").includes("本场没有评上分"),
    null,
    { timeout: 10000 },
  );
  checks.unscoredNote = true;

  const reviewResult = {
    ...result,
    status: "completed",
    session_score: 85,
    concepts: [
      {
        id: "tool-use",
        name: "工具调用",
        roles: ["review"],
        new_score: null,
        review_score: 85,
        mastery_before: 1,
        mastery_before_label: "初识",
        mastery_after: 1,
        mastery_after_label: "初识",
        mastery_updated: false,
        review_due_at: null,
      },
    ],
  };
  await page.evaluate((payload) => {
    window.__socket.onmessage({ data: JSON.stringify(payload) });
  }, reviewResult);
  await page.waitForFunction(
    () =>
      (document.querySelector("#result")?.textContent || "").includes(
        "本场掌握度未更新",
      ),
    null,
    { timeout: 10000 },
  );
  const reviewText = await page.locator("#result").innerText();
  checks.reviewOnlyNote = reviewText.includes("复习均分 85");

  await page.click("#kbfromresult");
  await page.waitForFunction(
    () => !document.querySelector("#kbpanel")?.classList.contains("hidden"),
    null,
    { timeout: 10000 },
  );
  checks.resultOpensPanel = true;
  await page.keyboard.press("Escape");
  await page.waitForFunction(
    () => document.querySelector("#kbpanel")?.classList.contains("hidden"),
    null,
    { timeout: 10000 },
  );
  checks.escapeCloses = true;

  await page.click("#knowledge");
  await page.waitForFunction(
    () => !document.querySelector("#kbpanel")?.classList.contains("hidden"),
    null,
    { timeout: 10000 },
  );
  await page.mouse.click(8, 8);
  await page.waitForFunction(
    () => document.querySelector("#kbpanel")?.classList.contains("hidden"),
    null,
    { timeout: 10000 },
  );
  checks.backdropCloses = true;

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  mobile.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  mobile.on("pageerror", (error) => errors.push(String(error)));
  await mobile.route("**/api/kb/**", async (route) => {
    const url = route.request().url();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(url.endsWith("/overview") ? overview : proposal),
    });
  });
  await mobile.addInitScript(() => {
    class FakeWebSocket {
      static OPEN = 1;
      static CLOSED = 3;
      constructor() {
        this.readyState = 1;
        setTimeout(() => {
          this.onopen?.();
          this.onmessage?.({
            data: JSON.stringify({
              type: "ready",
              modes: { llm: "fake" },
              notes: [],
            }),
          });
        }, 0);
      }
      send(raw) {
        const message = JSON.parse(raw);
        if (message.type === "conversation_list") {
          this.onmessage?.({
            data: JSON.stringify({ type: "conversation_list", items: [] }),
          });
        }
      }
      close() {
        this.readyState = 3;
      }
    }
    window.WebSocket = FakeWebSocket;
  });
  await mobile.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await mobile.waitForFunction(
    () => (document.querySelector("#status")?.textContent || "").includes("已就绪"),
    null,
    { timeout: 30000 },
  );
  await mobile.click("#knowledge");
  await mobile.waitForFunction(
    () => (document.querySelector("#kbtoday")?.textContent || "").includes("Agent 循环"),
    null,
    { timeout: 10000 },
  );
  const box = await mobile.locator(".kb-sheet").boundingBox();
  checks.mobilePanel = Boolean(box && box.width <= 390 && box.height > 0);
  await mobile.close();

  checks.noConsoleErrors = errors.filter(
    (message) => !message.includes("status of 500"),
  ).length === 0;
  const unexpectedErrors = errors.filter(
    (message) => !message.includes("status of 500"),
  );

  console.log(
    JSON.stringify(
      {
        checks,
        errors,
        unexpectedErrors,
        todayText,
        progressText,
        historyText,
        resultText,
      },
      null,
      2,
    ),
  );
  if (Object.values(checks).some((value) => !value)) process.exitCode = 1;
} finally {
  await browser.close();
}
