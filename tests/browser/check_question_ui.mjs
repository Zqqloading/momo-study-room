// 手动/本地浏览器验收：题型标签、评分后出处、回退标记。
// 用假 WebSocket 注入事件，不需要真实后端会话语义；页面仍由 BFF 静态服务提供。
// 先启动：
//   PROVIDER_MODE=fake DB_PATH=data/test-question-ui.db \
//     .venv/Scripts/python -m uvicorn bff.main:app --port 8798
// 再运行：
//   PLAYWRIGHT_CORE="D:/gstack/gstack-main/node_modules/playwright-core" \
//     BASE_URL="http://127.0.0.1:8798" node tests/browser/check_question_ui.mjs

import { pathToFileURL } from "node:url";

const configured = process.env.PLAYWRIGHT_CORE;
const moduleRef = configured
  ? pathToFileURL(
      configured.endsWith(".mjs")
        ? configured
        : `${configured.replace(/[\\/]$/, "")}/index.mjs`,
    ).href
  : "playwright-core";
const baseUrl = process.env.BASE_URL || "http://127.0.0.1:8798";
const { chromium } = await import(moduleRef);

const generatedQuestion = {
  type: "question",
  id: 1,
  role: "new",
  kind: "apply",
  question_type: "tradeoff",
  origin: "generated",
  text: "客户预算有限时，你会选 A 还是 B？放弃什么？",
  options: null,
  index: 1,
  total: 5,
};
const fallbackQuestion = {
  type: "question",
  id: 2,
  role: "review",
  kind: "recall",
  question_type: null,
  origin: "fallback",
  text: "旧题库回退题",
  options: null,
  index: 2,
  total: 5,
};

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("console", (message) => {
  if (message.type() === "error") errors.push(message.text());
});
page.on("pageerror", (error) => errors.push(String(error)));

await page.addInitScript(
  ({ generated, fallback }) => {
    window.__sent = [];
    window.__fakeQuestion = generated;
    window.__fakeFallback = fallback;
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
          if (window.__failNextStart) {
            window.__failNextStart = false;
            setTimeout(() => {
              this.onmessage?.({
                data: JSON.stringify({
                  type: "error",
                  stage: "session",
                  message: "生成失败且旧题库不足：测试主题 需要 5 题，只有 0 题",
                }),
              });
            }, 0);
            return;
          }
          this.onmessage?.({
            data: JSON.stringify({
              type: "session_ready",
              session_id: "s1",
              kind: "daily",
              intro: "上次「MVP」这道题你没答好，今天先把它补上。",
              focus: {
                concept_id: "mvp",
                name: "MVP",
                reason_kind: "recent_miss",
              },
              question: window.__fakeQuestion,
            }),
          });
        } else if (message.type === "answer") {
          this.onmessage?.({
            data: JSON.stringify({
              type: "score",
              question_id: message.question_id,
              score: 88,
              why: "方向对，但没说清放弃什么",
              question_type: "tradeoff",
              source_url: "https://example.com/m",
              source_excerpt: "MVP 先把验证范围压到核心流程。",
            }),
          });
          this.onmessage?.({
            data: JSON.stringify({
              type: "feedback_end",
              turn_id: message.turn_id,
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
  { generated: generatedQuestion, fallback: fallbackQuestion },
);

try {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => (document.querySelector("#status")?.textContent || "").includes("已就绪"),
    null,
    { timeout: 30000 },
  );

  await page.click("#start");
  await page.waitForFunction(
    () => (document.querySelector("#progress")?.textContent || "").includes("取舍权衡"),
    null,
    { timeout: 10000 },
  );
  const progress = await page.locator("#progress").innerText();
  const questionText = await page.locator("#question").innerText();
  const introText = await page.locator("#intro").innerText();

  await page.fill("#textinput", "我选 B，放弃短期上线速度");
  await page.click("#send");
  await page.waitForFunction(
    () => (document.querySelector("#score-line")?.textContent || "").includes("出处"),
    null,
    { timeout: 10000 },
  );
  const scoreText = await page.locator("#score-line").innerText();
  const href = await page
    .locator("#score-line a.score-source-link")
    .getAttribute("href");

  await page.evaluate(() => {
    const event = {
      type: "question",
      id: 2,
      role: "review",
      kind: "recall",
      question_type: null,
      origin: "fallback",
      text: "旧题库回退题",
      options: null,
      index: 2,
      total: 5,
    };
    window.__socket.onmessage({ data: JSON.stringify(event) });
  });
  await page.waitForFunction(
    () => (document.querySelector("#progress")?.textContent || "").includes("旧题回退"),
    null,
    { timeout: 10000 },
  );
  const fallbackProgress = await page.locator("#progress").innerText();
  const introAfterQuestion = await page.locator("#intro").innerText();

  await page.evaluate(() => {
    const event = {
      type: "session_result",
      session_id: "s1",
      status: "completed",
      session_score: 88,
      mastery: {},
      review_due_at: null,
      scores: [
        {
          question_id: 1,
          score: 88,
          why: "方向对",
          question_type: "tradeoff",
          source_url: "https://example.com/m",
          source_excerpt: "MVP 先把验证范围压到核心流程。",
        },
      ],
    };
    window.__socket.onmessage({ data: JSON.stringify(event) });
  });
  await page.waitForFunction(
    () => (document.querySelector("#result")?.textContent || "").includes("本场结果"),
    null,
    { timeout: 10000 },
  );
  const resultText = await page.locator("#result").innerText();

  await page.click("#start");
  await page.waitForFunction(
    () => (document.querySelector("#start")?.textContent || "").includes("开始今天的学习"),
    null,
    { timeout: 10000 },
  );
  await page.evaluate(() => {
    window.__failNextStart = true;
  });
  // Regression: ISSUE-001 — session start failure left the primary button disabled.
  // Found by /qa on 2026-11-25
  // Report: .gstack/qa-reports/qa-report-progress-driven-start-2026-11-25.md
  await page.click("#start");
  await page.waitForFunction(
    () => (document.querySelector("#status")?.textContent || "").includes("生成失败且旧题库不足"),
    null,
    { timeout: 10000 },
  );
  const retryText = await page.locator("#start").innerText();
  const retryDisabled = await page.locator("#start").isDisabled();

  const checks = {
    generatedTypeLabel: progress.includes("取舍权衡"),
    generatedNoFallbackBadge: !progress.includes("旧题回退"),
    questionText: questionText.includes("预算") && questionText.includes("放弃"),
    introShown: introText.includes("MVP") && introText.includes("没答好"),
    introPersists: introAfterQuestion.includes("MVP"),
    retryEnabled: !retryDisabled && retryText.includes("开始今天的学习"),
    scoreValue: scoreText.includes("88 分"),
    sourceExcerpt: scoreText.includes("MVP 先把验证范围压到核心流程"),
    sourceLink: href === "https://example.com/m",
    fallbackLabel: fallbackProgress.includes("回忆"),
    fallbackBadge: fallbackProgress.includes("旧题回退"),
    resultType: resultText.includes("【取舍权衡】"),
    resultScore: resultText.includes("88 分"),
    resultSource: resultText.includes("MVP 先把验证范围压到核心流程"),
    noConsoleErrors: errors.length === 0,
  };
  console.log(
    JSON.stringify(
      {
        progress,
        questionText,
        scoreText,
        href,
        fallbackProgress,
        resultText,
        checks,
        errors,
      },
      null,
      2,
    ),
  );
  if (Object.values(checks).some((value) => !value)) process.exitCode = 1;
} finally {
  await browser.close();
}
