import test from "node:test";
import assert from "node:assert/strict";

import { createVad, rms, DEFAULT_VAD } from "../web/vad.js";

function tone(frames, amplitude) {
  const samples = [];
  for (let i = 0; i < frames; i += 1) {
    samples.push(amplitude * Math.sin((2 * Math.PI * i) / 16));
  }
  return samples;
}

function silence(frames) {
  return new Array(frames).fill(0);
}

test("rms 静音为 0，单音大于阈值", () => {
  assert.equal(rms(silence(160)), 0);
  assert.ok(rms(tone(160, 0.5)) > DEFAULT_VAD.threshold);
});

test("静音不触发提交", () => {
  const vad = createVad();
  for (let i = 0; i < 100; i += 1) {
    assert.equal(vad.push(0, 100), "idle");
  }
});

test("说话后 1.5 秒静音触发提交", () => {
  const vad = createVad();
  for (let i = 0; i < 5; i += 1) assert.equal(vad.push(0.5, 100), "speech");
  for (let i = 0; i < 14; i += 1) vad.push(0, 100);
  assert.equal(vad.push(0, 100), "submit");
});

test("短停不触发提交", () => {
  const vad = createVad();
  for (let i = 0; i < 5; i += 1) vad.push(0.5, 100);
  for (let i = 0; i < 5; i += 1) assert.equal(vad.push(0, 100), "silence");
  for (let i = 0; i < 5; i += 1) {
    assert.equal(vad.push(0.5, 100), "speech");
  }
  for (let i = 0; i < 10; i += 1) assert.notEqual(vad.push(0, 100), "submit");
});

test("手动结束优先，但从未说话时不提交", () => {
  const idle = createVad();
  for (let i = 0; i < 5; i += 1) idle.push(0, 100);
  assert.equal(idle.end(), "idle");

  const vad = createVad();
  vad.push(0.5, 100);
  assert.equal(vad.end(), "submit");
});
