// 手动浏览器验收：mood → 待机表情、说话压制、头部幅度。
// 先启动 fake 模式 BFF（8799，隔离 DB）：
//   PROVIDER_MODE=fake DB_PATH=<tmp>/qa.db DATA_DIR=<tmp>/data CONTENT_DIR=<tmp>/empty \
//     TTS_KIND=fake ASR_KIND=fake SEARCH_KIND=off AGENT_HARNESS=off \
//     .venv/Scripts/python -m uvicorn bff.main:app --host 127.0.0.1 --port 8799
// 再运行：
//   PLAYWRIGHT_CORE="D:/gstack/gstack-main/node_modules/playwright-core" \
//     BASE_URL="http://127.0.0.1:8799" node tests/browser/check_emotion_face.mjs

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

  const mood = async (comfort, energy, waitMs = 1000) => {
    await page.evaluate(
      ([c, e]) => window.__emotionFace.setMood(c, e),
      [comfort, energy],
    );
    await page.waitForTimeout(waitMs);
    return page.evaluate(() => window.__emotionFace.snapshot());
  };

  const high = await mood(0.8, 0.9);
  expect("high/high happy", high.expressions.happy > 0.3, JSON.stringify(high));

  const low = await mood(-0.8, 0.2);
  expect("low/low sad", low.expressions.sad > 0.2, JSON.stringify(low));
  expect("low/low happy fades", low.expressions.happy < 0.05, JSON.stringify(low));

  const angry = await mood(-0.8, 0.9);
  expect("low/high angry", angry.expressions.angry > 0.08, JSON.stringify(angry));
  expect("low/high sad fades", angry.expressions.sad < 0.05, JSON.stringify(angry));

  await page.evaluate(() => {
    window.__emotionFace.setMood(0.8, 0.9);
    window.__emotionFace.setSpeaking(true);
  });
  await page.waitForTimeout(800);
  const speaking = await page.evaluate(() => window.__emotionFace.snapshot());
  expect(
    "speaking happy <= 0.15",
    speaking.expressions.happy <= 0.15,
    JSON.stringify(speaking),
  );

  await page.evaluate(() => window.__emotionFace.setSpeaking(false));
  await page.waitForTimeout(800);
  const after = await page.evaluate(() => window.__emotionFace.snapshot());
  expect("speaking off returns", after.expressions.happy > 0.3, JSON.stringify(after));

  const headSamples = [];
  for (let index = 0; index < 20; index += 1) {
    await page.waitForTimeout(50);
    headSamples.push(
      await page.evaluate(() => window.__emotionFace.snapshot().head),
    );
  }
  for (const sample of headSamples) {
    if (!sample) {
      problems.push("head: 没有 head 骨骼");
      break;
    }
    expect("head pitch", Math.abs(sample.pitch) <= 0.041, JSON.stringify(sample));
    expect("head yaw", Math.abs(sample.yaw) <= 0.031, JSON.stringify(sample));
  }

  console.log(
    JSON.stringify(
      { high, low, angry, speaking, after, headSamples, errors, problems },
      null,
      2,
    ),
  );
  if (problems.length || errors.length) process.exitCode = 1;
} finally {
  await browser.close();
}
