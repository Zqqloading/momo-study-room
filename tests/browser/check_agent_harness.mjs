// 页面验收：agent_status、teach_reply、重复命令、重复提交提示、刷新恢复。
// 用假 WebSocket 注入事件，不需要真实后端；页面由静态服务提供。
// 先启动静态服务：
//   .venv/Scripts/python -m http.server 8799 --directory web
// 再运行：
//   PLAYWRIGHT_CORE="D:/gstack/gstack-main/node_modules/playwright-core" \
//     BASE_URL="http://127.0.0.1:8799" node tests/browser/check_agent_harness.mjs

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

await page.addInitScript(() => {
  window.__sent = [];
  const question = (id) => ({
    type: "question",
    id,
    role: "new",
    kind: "apply",
    question_type: "concept",
    origin: "generated",
    text: `第 ${id} 题：说说 Agent 循环为什么需要停止条件。`,
    options: null,
    index: id,
    total: 5,
  });
  class FakeWebSocket {
    static OPEN = 1;
    static CLOSED = 3;
    constructor(url) {
      this.url = url;
      this.readyState = 1;
      window.__socket = this;
      setTimeout(() => {
        this.onopen?.();
        this.emit({
          type: "ready",
          modes: { llm: "fake", scorer: "fake" },
          notes: [],
        });
      }, 0);
    }
    emit(payload) {
      this.onmessage?.({ data: JSON.stringify(payload) });
    }
    send(raw) {
      const message = JSON.parse(raw);
      window.__sent.push(message);
      if (message.type === "conversation_list") {
        this.emit({
          type: "conversation_list",
          items: [{ conversation_id: "c1", title: "测试对话" }],
        });
      } else if (message.type === "conversation_load") {
        this.emit({
          type: "conversation_loaded",
          conversation_id: "c1",
          title: "测试对话",
          messages: [],
        });
      } else if (message.type === "conversation_new") {
        this.emit({
          type: "conversation_created",
          conversation_id: "c1",
          title: "测试对话",
          message_count: 0,
        });
      } else if (message.type === "session_start") {
        this.emit({
          type: "session_ready",
          session_id: "s1",
          kind: "daily",
          unit: { kind: "daily", main: null, review: null },
          question: question(1),
        });
      } else if (message.type === "session_resume") {
        this.emit({
          type: "session_ready",
          session_id: "s1",
          kind: "daily",
          unit: { kind: "daily", main: null, review: null },
          question: question(3),
        });
      } else if (message.type === "repeat") {
        this.emit(question(Number(message.question_id)));
      } else if (message.type === "answer") {
        const id = Number(message.question_id);
        this.emit({
          type: "score",
          question_id: id,
          score: 70,
          why: "方向对",
          question_type: "concept",
          source_url: "",
          source_excerpt: "",
          duplicate: false,
          turn_id: message.turn_id,
        });
        this.emit(question(id + 1));
        this.emit({ type: "feedback_end", turn_id: message.turn_id });
      }
    }
    close() {
      this.readyState = 3;
    }
  }
  window.WebSocket = FakeWebSocket;
});

try {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () =>
      (document.querySelector("#status")?.textContent || "").includes("可以继续说话"),
    null,
    { timeout: 30000 },
  );
  await page.click("#start");
  await page.waitForFunction(
    () => (document.querySelector("#question")?.textContent || "").includes("第 1 题"),
    null,
    { timeout: 10000 },
  );

  const questionBeforeRepeat = await page.locator("#question").innerText();
  await page.fill("#textinput", "重复");
  await page.click("#send");
  await page.waitForFunction(
    () => (window.__sent || []).some((message) => message.type === "repeat"),
    null,
    { timeout: 10000 },
  );
  const repeatSent = await page.evaluate(() =>
    (window.__sent || []).some((message) => message.type === "repeat"),
  );
  await page.waitForFunction(
    () => (document.querySelector("#status")?.textContent || "").includes("请作答"),
    null,
    { timeout: 10000 },
  );
  const questionAfterRepeat = await page.locator("#question").innerText();
  const scoreAfterRepeat = await page.locator("#score-line").innerText();

  await page.evaluate(() => {
    window.__socket.onmessage({
      data: JSON.stringify({
        type: "agent_status",
        phase: "searching",
        tool: "search_materials",
        turn_id: "t1",
      }),
    });
  });
  await page.waitForFunction(
    () => (document.querySelector("#status")?.textContent || "").includes("正在查材料"),
    null,
    { timeout: 10000 },
  );
  const searchStatus = await page.locator("#status").innerText();

  const questionBeforeTeach = await page.locator("#question").innerText();
  await page.evaluate(() => {
    window.__socket.onmessage({
      data: JSON.stringify({
        type: "teach_reply",
        session_id: "s1",
        question_id: 1,
        mode: "teach",
        text: "Agent 循环需要一个停止条件，否则会一直行动。",
        sources: [{ index: 1, title: "材料 A", url: "fixture://a" }],
        turn_id: "t1",
      }),
    });
  });
  await page.waitForFunction(
    () => (document.querySelector("#bubble")?.textContent || "").includes("讲解"),
    null,
    { timeout: 10000 },
  );
  const teachBubble = await page.locator("#bubble").innerText();
  const questionAfterTeach = await page.locator("#question").innerText();

  await page.evaluate(() => {
    window.__socket.onmessage({
      data: JSON.stringify({
        type: "score",
        question_id: 1,
        score: 70,
        why: "方向对",
        question_type: "concept",
        source_url: "",
        source_excerpt: "",
        duplicate: true,
        turn_id: "t1",
      }),
    });
  });
  await page.waitForFunction(
    () => (document.querySelector("#status")?.textContent || "").includes("已经评过分"),
    null,
    { timeout: 10000 },
  );
  const duplicateStatus = await page.locator("#status").innerText();

  await page.fill("#textinput", "回答一");
  await page.click("#send");
  await page.waitForFunction(
    () => (document.querySelector("#question")?.textContent || "").includes("第 2 题"),
    null,
    { timeout: 10000 },
  );
  await page.fill("#textinput", "回答二");
  await page.click("#send");
  await page.waitForFunction(
    () => (document.querySelector("#question")?.textContent || "").includes("第 3 题"),
    null,
    { timeout: 10000 },
  );
  const stored = await page.evaluate(() => localStorage.getItem("coach.session"));

  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => (document.querySelector("#question")?.textContent || "").includes("第 3 题"),
    null,
    { timeout: 30000 },
  );
  const afterReloadQuestion = await page.locator("#question").innerText();
  const resumed = await page.evaluate(() =>
    (window.__sent || []).some(
      (message) => message.type === "session_resume" && message.session_id === "s1",
    ),
  );

  const checks = {
    agentStatusShown: searchStatus.includes("正在查材料"),
    repeatSent,
    repeatDoesNotChangeQuestion: questionAfterRepeat === questionBeforeRepeat,
    repeatDidNotScore: !scoreAfterRepeat.trim(),
    teachShown: teachBubble.includes("Agent 循环需要一个停止条件"),
    teachSources: teachBubble.includes("来源") && teachBubble.includes("材料 A"),
    teachDoesNotChangeQuestion: questionAfterTeach === questionBeforeTeach,
    duplicateHint: duplicateStatus.includes("已经评过分"),
    sessionPersisted: stored === "s1",
    resumedAfterReload: resumed,
    questionAfterReload: afterReloadQuestion.includes("第 3 题"),
    noScriptErrors: errors.every((error) =>
      error.includes("Failed to load resource"),
    ),
  };
  console.log(
    JSON.stringify(
      {
        searchStatus,
        questionBeforeTeach,
        questionAfterTeach,
        teachBubble,
        duplicateStatus,
        stored,
        afterReloadQuestion,
        checks,
        errors,
      },
      null,
      2,
    ),
  );
  if (Object.values(checks).some((value) => !value)) {
    process.exitCode = 1;
  }
} finally {
  await browser.close();
}
