// 浏览器端能量 VAD：纯函数，便于用合成 PCM 测试。
// 判定与录音解耦；调用方负责开始/结束录音。

export const DEFAULT_VAD = {
  threshold: 0.02,
  silenceMs: 1500,
  minSpeechMs: 200,
};

export function rms(frame) {
  let sum = 0;
  for (let i = 0; i < frame.length; i += 1) {
    const value = frame[i];
    sum += value * value;
  }
  return Math.sqrt(sum / (frame.length || 1));
}

export function createVad(options = {}) {
  const config = { ...DEFAULT_VAD, ...options };
  let sawSpeech = false;
  let speechMs = 0;
  let silenceMs = 0;

  function push(level, deltaMs) {
    if (level >= config.threshold) {
      sawSpeech = true;
      speechMs += deltaMs;
      silenceMs = 0;
      return "speech";
    }
    if (!sawSpeech) return "idle";
    silenceMs += deltaMs;
    if (silenceMs >= config.silenceMs && speechMs >= config.minSpeechMs) return "submit";
    return "silence";
  }

  // 手动结束优先：只要说过话就提交。
  function end() {
    return sawSpeech ? "submit" : "idle";
  }

  return { config, push, end };
}
