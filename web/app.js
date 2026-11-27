import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { createVad, rms } from "/vad.js";
import { initKnowledgePanel, openKnowledgePanel } from "/kb.js?v=20261125a";
import { initHistoryPanel } from "/history.js?v=20261126a";

const canvas = document.getElementById("stage");
const statusEl = document.getElementById("status");
const bubble = document.getElementById("bubble");
const talk = document.getElementById("talk");
const textInput = document.getElementById("textinput");
const sendBtn = document.getElementById("send");
const askBtn = document.getElementById("ask");
const askMenu = document.getElementById("askmenu");
const metrics = document.getElementById("metrics");
const newConversationBtn = document.getElementById("newconversation");
const modeSwitch = document.getElementById("modeswitch");
const convPicker = document.getElementById("convpicker");
const convTrigger = document.getElementById("convtrigger");
const convLabel = document.getElementById("convlabel");
const convList = document.getElementById("convlist");
const chatmenu = document.getElementById("chatmenu");
const renameBtn = document.getElementById("conv-rename");
const deleteBtn = document.getElementById("conv-delete");
const chatlog = document.getElementById("chatlog");
const chatpanel = document.getElementById("chatpanel");
const chattoggle = document.getElementById("chattoggle");
const toastEl = document.getElementById("toast");
let toastTimer = null;

function notify(text) {
  toastEl.textContent = text;
  toastEl.classList.remove("hidden");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.add("hidden"), 2800);
}

// ---------- three.js scene ----------
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);

const scene = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(32, window.innerWidth / window.innerHeight, 0.1, 20);
camera.position.set(0, 0.15, 2.1);
camera.lookAt(0, 0.05, 0);

scene.add(new THREE.HemisphereLight(0xffe9cf, 0x4a3626, 1.05));
const keyLight = new THREE.DirectionalLight(0xfff1de, 1.35);
keyLight.position.set(1.2, 2, 2);
scene.add(keyLight);
// 窗光方向补一层暖色轮廓光，让人物融进背景
const windowLight = new THREE.DirectionalLight(0xffe2b8, 0.5);
windowLight.position.set(0, 1.6, -1.5);
scene.add(windowLight);

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// ---------- avatar state ----------
let vrm = null;
let avatarInitialYaw = 0;
let placeholder = null;
let placeholderMouth = null;
let mouth = 0;
let blink = 0;
let blinkUntil = 0;
let nextBlink = 2 + Math.random() * 2;
let mood = { comfort: 0, energy: 0.5 };
let headNode = null;
let neckNode = null;
let headBase = null;
let neckBase = null;
const EMOTION_EXPRESSIONS = ["happy", "relaxed", "sad", "angry"];
const expressionValues = new Map(EMOTION_EXPRESSIONS.map((name) => [name, 0]));
const MOOD_EXPRESSIONS = {
  "high-high": ["happy", 0.4],
  "high-mid": ["relaxed", 0.5],
  "high-low": ["relaxed", 0.3],
  "mid-high": ["relaxed", 0.4],
  "mid-mid": ["neutral", 0],
  "mid-low": ["sad", 0.15],
  "low-high": ["angry", 0.12],
  "low-mid": ["sad", 0.2],
  "low-low": ["sad", 0.3],
};

function clamp(value, limit) {
  return Math.max(-limit, Math.min(limit, value));
}

function setMood(comfort, energy) {
  const c = Number(comfort);
  const e = Number(energy);
  mood = {
    comfort: Number.isFinite(c) ? Math.max(-1, Math.min(1, c)) : 0,
    energy: Number.isFinite(e) ? Math.max(0, Math.min(1, e)) : 0.5,
  };
}

function moodExpression({ comfort, energy }) {
  const cLevel = comfort >= 0.4 ? "high" : comfort <= -0.3 ? "low" : "mid";
  const eLevel = energy >= 0.7 ? "high" : energy < 0.4 ? "low" : "mid";
  return MOOD_EXPRESSIONS[`${cLevel}-${eLevel}`];
}

function bindHeadBones(model) {
  const humanoid = model.humanoid;
  headNode = humanoid?.getNormalizedBoneNode?.("head") || null;
  neckNode = humanoid?.getNormalizedBoneNode?.("neck") || null;
  headBase = headNode ? headNode.rotation.clone() : null;
  neckBase = neckNode ? neckNode.rotation.clone() : null;
}

async function buildAvatar() {
  let vrmModule = null;
  try {
    vrmModule = await import("@pixiv/three-vrm");
  } catch (err) {
    console.warn("three-vrm 加载失败，使用占位形象", err);
  }

  if (!vrmModule?.VRMLoaderPlugin) {
    addPlaceholder();
    return;
  }

  const loader = new GLTFLoader();
  loader.register((parser) => new vrmModule.VRMLoaderPlugin(parser));
  loader.load(
    "/assets/avatar.vrm",
    (gltf) => {
      const model = gltf.userData.vrm;
      if (!model) {
        addPlaceholder();
        return;
      }
      try {
        vrmModule.VRMUtils?.removeUnnecessaryVertices?.(gltf.scene);
        vrmModule.VRMUtils?.rotateVRM0?.(model);
      } catch (err) {
        console.warn("VRM 预处理失败，继续加载", err);
      }
      model.scene.position.set(0, 0, 0);
      scene.add(model.scene);
      poseVrm(model);
      poseFingers(model);
      frameVrm();
      vrm = model;
      bindHeadBones(model);
      if (statusEl.textContent === "正在加载形象…") {
        statusEl.textContent = "3D 形象已加载";
      }
    },
    undefined,
    (err) => {
      console.warn("assets/avatar.vrm 不可用，使用占位形象", err);
      addPlaceholder();
    }
  );
}

// VRM 默认是 T-pose；把上臂放下来，变成待机站姿。
function poseVrm(model) {
  const humanoid = model.humanoid;
  if (!humanoid?.getNormalizedBoneNode) return;

  const upperLeft = humanoid.getNormalizedBoneNode("leftUpperArm");
  const upperRight = humanoid.getNormalizedBoneNode("rightUpperArm");
  if (upperLeft) upperLeft.rotation.z = 1.36;
  if (upperRight) upperRight.rotation.z = -1.36;

  const lowerLeft = humanoid.getNormalizedBoneNode("leftLowerArm");
  const lowerRight = humanoid.getNormalizedBoneNode("rightLowerArm");
  if (lowerLeft) lowerLeft.rotation.y = -0.08;
  if (lowerRight) lowerRight.rotation.y = 0.08;
}

// 手指默认并拢平伸；加一点弯曲和外展，变成放松的手。参数按 VRoid 归一化骨骼调。
function poseFingers(model) {
  const humanoid = model.humanoid;
  if (!humanoid?.getNormalizedBoneNode) return;

  const fingers = ["Index", "Middle", "Ring", "Little"];
  const spread = { Index: 0.16, Middle: 0.05, Ring: -0.06, Little: -0.16 };
  const curl = { Proximal: 0.15, Intermediate: 0.22, Distal: 0.14 };

  for (const side of ["left", "right"]) {
    // 左右手的归一化手指骨骼是镜像的：弯曲轴同向，外展轴反向。
    const curlSign = side === "left" ? 1 : -1;
    const spreadSign = side === "left" ? -1 : 1;
    for (const finger of fingers) {
      for (const [segment, amount] of Object.entries(curl)) {
        const bone = humanoid.getNormalizedBoneNode(`${side}${finger}${segment}`);
        if (!bone) continue;
        bone.rotation.z += curlSign * amount;
        if (segment === "Proximal") bone.rotation.y += spreadSign * spread[finger];
      }
    }
    for (const segment of ["Proximal", "Intermediate", "Distal"]) {
      const thumb = humanoid.getNormalizedBoneNode(`${side}Thumb${segment}`);
      if (thumb) thumb.rotation.z += curlSign * 0.08;
    }
  }
}

// 半身取景：面部在画面上部，胸口到桌面之间，给左侧气泡留位置。
function frameVrm() {
  camera.position.set(0, 1.1, 2.9);
  camera.lookAt(0, 1.0, 0);
  camera.updateProjectionMatrix();
}

function addPlaceholder() {
  placeholder = new THREE.Group();
  const skin = new THREE.MeshStandardMaterial({ color: 0x8fb3ff, roughness: 0.55, metalness: 0.05 });
  const dark = new THREE.MeshStandardMaterial({ color: 0x11162a, roughness: 0.4 });

  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.26, 0.7, 6, 16), skin);
  body.position.y = -0.55;
  placeholder.add(body);

  const head = new THREE.Mesh(new THREE.SphereGeometry(0.32, 32, 32), skin);
  head.position.y = 0.18;
  placeholder.add(head);

  for (const x of [-0.12, 0.12]) {
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.035, 16, 16), dark);
    eye.position.set(x, 0.25, 0.29);
    placeholder.add(eye);
  }

  placeholderMouth = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.02, 0.02), dark);
  placeholderMouth.position.set(0, 0.05, 0.31);
  placeholder.add(placeholderMouth);

  scene.add(placeholder);
  if (statusEl.textContent === "正在加载形象…") {
    statusEl.textContent = "占位形象已就绪。把 VRM 放到 assets/avatar.vrm 可换成 3D 形象。";
  }
}

buildAvatar();

// ---------- drag to rotate ----------
let dragging = false;
let lastPointerX = 0;

function avatarTarget() {
  return vrm?.scene ?? null;
}

canvas.addEventListener("pointerdown", (event) => {
  if (event.button !== 0 || !avatarTarget()) return;
  dragging = true;
  lastPointerX = event.clientX;
  canvas.classList.add("dragging");
  try {
    canvas.setPointerCapture(event.pointerId);
  } catch (err) {
    // 合成事件没有活动指针，忽略即可。
  }
});

canvas.addEventListener("pointermove", (event) => {
  if (!dragging) return;
  const target = avatarTarget();
  if (!target) return;
  const dx = event.clientX - lastPointerX;
  lastPointerX = event.clientX;
  target.rotation.y += dx * 0.012;
});

function endDrag(event) {
  if (!dragging) return;
  dragging = false;
  canvas.classList.remove("dragging");
  try {
    canvas.releasePointerCapture(event.pointerId);
  } catch (err) {
    // 同上
  }
}

canvas.addEventListener("pointerup", endDrag);
canvas.addEventListener("pointercancel", endDrag);

canvas.addEventListener("dblclick", () => {
  const target = avatarTarget();
  if (target) target.rotation.y = avatarInitialYaw;
});

// ---------- audio ----------
let audioCtx = null;
let analyser = null;
let speaking = false;
let activeSource = null;

function ensureAudioCtx() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (audioCtx.state === "suspended") audioCtx.resume();
  return audioCtx;
}

function base64ToArrayBuffer(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

function arrayBufferToBase64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

function mergeBase64Chunks(chunks) {
  const arrays = chunks.map((chunk) => new Uint8Array(base64ToArrayBuffer(chunk)));
  const total = arrays.reduce((sum, array) => sum + array.length, 0);
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const array of arrays) {
    merged.set(array, offset);
    offset += array.length;
  }
  return merged.buffer;
}

async function playBuffer(buffer) {
  if (!buffer) return null;
  const ctx = ensureAudioCtx();
  try {
    if (ctx.state === "suspended") await ctx.resume();
    const decoded = await ctx.decodeAudioData(buffer);
    const source = ctx.createBufferSource();
    source.buffer = decoded;
    activeSource = source;

    const node = ctx.createAnalyser();
    node.fftSize = 1024;
    node.smoothingTimeConstant = 0.2;

    source.connect(node);
    node.connect(ctx.destination);

    analyser = node;
    speaking = true;

    let firstFrameMs = null;
    // 半双工：播放结束前不放开"按住说话"。
    // 自动播放被拦截时 onended 可能永远不来，用音频时长 + 1.5s 兜底。
    await new Promise((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (activeSource === source) activeSource = null;
        speaking = false;
        analyser = null;
        resolve();
      };
      const timer = window.setTimeout(finish, decoded.duration * 1000 + 1500);
      source.onended = finish;
      try {
        source.start();
      } catch (err) {
        console.warn("音频播放失败", err);
        finish();
        return;
      }
      firstFrameMs = lastSendAt ? Math.round(performance.now() - lastSendAt) : null;
    });
    return firstFrameMs;
  } catch (err) {
    console.warn("音频播放失败", err);
    speaking = false;
    analyser = null;
    return null;
  }
}

// ---------- microphone ----------
let stream = null;
let recorder = null;
let chunks = [];
let recording = false;
let starting = false;
let stopRequested = false;
let busy = false;
let lastSendAt = 0; // 松手/发送时刻，用来算"松手到出声"
let vad = createVad();
let vadTimer = null;
let vadAnalyser = null;
let pendingInputMode = "text";

function setBusy(on, label) {
  busy = on;
  talk.disabled = on;
  sendBtn.disabled = on;
  if (label) statusEl.textContent = label;
}

function setTalking(on) {
  talk.classList.toggle("talking", on);
  talk.textContent = on ? "结束作答" : "开始说话";
}

async function startRecording() {
  if (recording || starting || busy) return;
  ensureAudioCtx();

  starting = true;
  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("这个浏览器不支持录音，请用 Edge/Chrome 打开本页");
    }
    // 每次录音重新拿流，录完就关麦（半双工：它说话时麦克风不常开）。
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
      });
    } catch (err) {
      throw new Error(`拿不到麦克风（${err.name}）：${err.message}`);
    }

    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"].find((m) =>
      window.MediaRecorder.isTypeSupported(m)
    );
    if (!mime) {
      stream.getTracks().forEach((track) => track.stop());
      stream = null;
      throw new Error("这个浏览器不支持录音，请用 Edge 或 Chrome");
    }

    chunks = [];
    recorder = new MediaRecorder(stream, { mimeType: mime });
    recorder.ondataavailable = (event) => {
      if (event.data.size) chunks.push(event.data);
    };
    recorder.onstop = async () => {
      recording = false;
      setTalking(false);
      lastSendAt = performance.now();
      stream?.getTracks().forEach((track) => track.stop());
      stream = null;
      const blob = new Blob(chunks, { type: mime });
      await sendRecording(blob);
    };
    recorder.start();
    recording = true;
    setTalking(true);
    statusEl.textContent = "我在听…";

    // 能量 VAD：说话后 1.5 秒静音自动提交；短停不切断。
    const ctx = ensureAudioCtx();
    const source = ctx.createMediaStreamSource(stream);
    const node = ctx.createAnalyser();
    node.fftSize = 512;
    source.connect(node);
    vadAnalyser = node;
    vad = createVad();
    vadTimer = window.setInterval(() => {
      if (!vadAnalyser) return;
      const frame = new Float32Array(vadAnalyser.fftSize);
      vadAnalyser.getFloatTimeDomainData(frame);
      if (vad.push(rms(frame), 100) === "submit") {
        statusEl.textContent = "听到你停下了，正在识别…";
        stopRecording();
      }
    }, 100);
  } catch (err) {
    stopRequested = false;
    throw err;
  } finally {
    starting = false;
  }

  // 松手早于麦克风就绪：拿到流后立刻结束这次录音。
  if (stopRequested) {
    stopRequested = false;
    stopRecording();
  }
}

function stopRecording() {
  if (starting) {
    stopRequested = true;
    return;
  }
  if (!recording || !recorder) return;
  if (vadTimer) {
    clearInterval(vadTimer);
    vadTimer = null;
  }
  vadAnalyser = null;
  recorder.stop();
}

function encodeWav(float32, sampleRate) {
  const length = float32.length;
  const buffer = new ArrayBuffer(44 + length * 2);
  const view = new DataView(buffer);
  const writeString = (offset, text) => {
    for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
  };

  writeString(0, "RIFF");
  view.setUint32(4, 36 + length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, length * 2, true);

  let offset = 44;
  for (let i = 0; i < length; i += 1) {
    const sample = Math.max(-1, Math.min(1, float32[i]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    offset += 2;
  }
  return buffer;
}

async function sendRecording(blob) {
  setBusy(true, "正在识别…");
  try {
    const ctx = ensureAudioCtx();
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
    const targetRate = 16000;
    const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * targetRate), targetRate);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const rendered = await offline.startRendering();
    const wav = encodeWav(rendered.getChannelData(0), targetRate);

    if (ws?.readyState !== WebSocket.OPEN) {
      setBusy(false, "还没连上服务，稍等一秒再试");
      return;
    }
    const payload = {
      type: "audio",
      turn_id: nextTurnId(),
      sample_rate: targetRate,
      mime: "audio/wav",
      data: arrayBufferToBase64(wav),
      retry: retryPending,
    };
    if (sessionId && currentQuestion) {
      payload.session_id = sessionId;
      payload.question_id = currentQuestion.id;
    } else {
      if (conversationId) payload.conversation_id = conversationId;
      payload.mode = freeTalkMode;
    }
    ws.send(JSON.stringify(payload));
    statusEl.textContent = sessionId && currentQuestion ? "正在识别…" : "正在想…";
  } catch (err) {
    console.error(err);
    setBusy(false, `录音处理失败：${err.message}`);
  }
}

// ---------- session state ----------
const sessionPanel = document.getElementById("session-panel");
const progressEl = document.getElementById("progress");
const questionEl = document.getElementById("question");
const introEl = document.getElementById("intro");
const optionsEl = document.getElementById("options");
const scoreLine = document.getElementById("score-line");
const advanceHint = document.getElementById("advance-hint");
const resultEl = document.getElementById("result");
const startBtn = document.getElementById("start");
const finishBtn = document.getElementById("finish");
const textrow = document.getElementById("textrow");
const knowledgeBtn = document.getElementById("knowledge");
const unitLabel = document.getElementById("unitlabel");
const openingEl = document.getElementById("opening");
const lectureEl = document.getElementById("lecture");

let ws = null;
let sessionId = null;
let currentQuestion = null;
let agentHarness = false;
const SESSION_KEY = "coach.session";
let turnSeq = 0;
let pendingTurnId = null;
const REPEAT_COMMANDS = new Set([
  "重复",
  "重复一遍",
  "再读一遍",
  "再说一遍",
  "再念一遍",
]);
let awaitingEnd = false;
let pendingQuestion = null;
let pendingResult = null;
let pendingQuestionAudio = [];
let currentAnswered = false;
let audioMuted = false;
let feedbackPending = false;
let forceAdvance = false;
let retryPending = false;
let revealedCurrent = false;
let cancelPending = false; // 出题还没回来就点了「提前结束」
let cancelling = false; // 取消的那一场只收尾，不弹结果卡
let settling = false;
let audioSuppressed = false; // 结束/取消后，等结果回来前把语音全丢掉
const DEFAULT_ADVANCE_HINT = "看完点「下一题」继续";
// 点「开始说话」/「下一题」会立刻切音；被切断那一轮朗读的后续分句一律丢弃，
// 只有新一轮朗读（seq=1）到达才恢复。
const mutedUtterances = new Set();

// 单元外的自由对话：默认闲聊，用户可切到教学讲解。
let freeTalkMode = "chat";
try {
  if (localStorage.getItem("coach.freetalkmode") === "teach") freeTalkMode = "teach";
} catch (err) {
  freeTalkMode = "chat";
}

let conversationId = null;
let conversationItems = [];
let menuConversationId = null;
try {
  conversationId = localStorage.getItem("coach.conversation");
} catch (err) {
  conversationId = null;
}

function setConversation(id) {
  conversationId = id;
  try {
    localStorage.setItem("coach.conversation", id);
  } catch (err) {
    // 隐私模式禁写存储时只保留内存状态。
  }
}

function setUnitLabel(unit) {
  if (!unitLabel) return;
  const main = unit?.main?.name || unit?.main?.id || "";
  const review = unit?.review?.name || unit?.review?.id || "";
  let text = "";
  if (main && review && unit.main?.id !== unit.review?.id) {
    text = `今日单元：${main}（复习：${review}）`;
  } else if (main) {
    text = `今日单元：${main}${review ? "（含复习）" : ""}`;
  } else if (review) {
    text = `今日单元：复习 ${review}`;
  }
  unitLabel.textContent = text;
  unitLabel.classList.toggle("hidden", !text);
  syncOpening();
}

function clearUnitLabel() {
  if (!unitLabel) return;
  unitLabel.textContent = "";
  unitLabel.classList.add("hidden");
  syncOpening();
}

function setIntro(text) {
  if (!introEl) return;
  const clean = String(text || "").trim();
  introEl.textContent = clean;
  show(introEl, Boolean(clean));
  syncOpening();
}

function clearIntro() {
  setIntro("");
}

// 开场讲解：和「今日单元」同一块，紧贴题目框上方。
function setLecture(text) {
  if (!lectureEl) return;
  const clean = String(text || "").trim();
  lectureEl.textContent = clean;
  show(lectureEl, Boolean(clean));
  syncOpening();
}

function clearLecture() {
  setLecture("");
}

// 开场块（今日单元 + 生活句 + 讲解）有空内容才显示。
function syncOpening() {
  if (!openingEl) return;
  const hasContent = [unitLabel, introEl, lectureEl].some(
    (el) => el && el.textContent.trim()
  );
  show(openingEl, hasContent);
}

function appendChatMessage(role, text, mode = null, sources = null) {
  if (!text) return;
  const wrap = document.createElement("div");
  wrap.className = `chat-message ${role}`;
  const meta = document.createElement("div");
  meta.className = "chat-meta";
  meta.textContent =
    role === "user" ? "你" : mode === "teach" ? "教学" : "自由对话";
  const body = document.createElement("div");
  body.className = "chat-text";
  body.textContent = text;
  wrap.append(meta, body);
  if (Array.isArray(sources) && sources.length) {
    const list = document.createElement("ul");
    list.className = "chat-sources";
    for (const source of sources) {
      const item = document.createElement("li");
      const kind = source.kind || "material";
      let label = `[${source.index || "?"}] ${source.title || (kind === "web" ? "网页" : "材料")}`;
      if (kind === "web") {
        const domain = source.domain || "网页";
        const date = source.published_at || "未标注日期";
        const retrieved = source.retrieved_at ? ` · 检索于 ${source.retrieved_at}` : "";
        label += `（${domain} · ${date}${retrieved}）`;
        item.classList.add("chat-source-web");
      }
      const excerpt = source.excerpt ? `：${source.excerpt}` : "";
      item.textContent = `${label}${excerpt}`;
      if (source.url) {
        item.title = source.url;
        if (kind === "web") {
          const link = document.createElement("a");
          link.href = source.url;
          link.target = "_blank";
          link.rel = "noreferrer";
          link.className = "chat-source-link";
          link.textContent = "打开来源";
          item.append(" ", link);
        }
      }
      list.appendChild(item);
    }
    wrap.appendChild(list);
  }
  chatlog.appendChild(wrap);
  chatpanel.classList.remove("hidden");
  chatlog.scrollTop = chatlog.scrollHeight;
}

function renderConversation(messages) {
  chatlog.innerHTML = "";
  if (!messages.length) {
    chatpanel.classList.remove("hidden");
    return;
  }
  for (const message of messages) {
    appendChatMessage(message.role, message.text, message.mode, message.sources);
  }
  chatpanel.classList.remove("hidden");
}

function conversationLabel(item) {
  return `${item.title || "未命名对话"}（${item.message_count}）`;
}

function renderConversationList() {
  convList.innerHTML = "";
  for (const item of conversationItems) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "conv-item";
    btn.dataset.id = item.conversation_id;
    btn.textContent = conversationLabel(item);
    if (item.conversation_id === conversationId) btn.classList.add("active");
    convList.appendChild(btn);
  }
  const current = conversationItems.find(
    (item) => item.conversation_id === conversationId
  );
  convLabel.textContent = current ? conversationLabel(current) : "历史对话";
}

function syncConversationSelect(items) {
  conversationItems = items;
  renderConversationList();
}

function setConvListOpen(open) {
  convList.classList.toggle("hidden", !open);
  convTrigger.setAttribute("aria-expanded", String(open));
}

function closeChatmenu() {
  chatmenu.classList.add("hidden");
  menuConversationId = null;
}

function startRename(targetId) {
  const item = conversationItems.find(
    (entry) => entry.conversation_id === targetId
  );
  const btn = convList.querySelector(`.conv-item[data-id="${targetId}"]`);
  if (!item || !btn) return;
  const input = document.createElement("input");
  input.className = "conv-edit";
  input.value = item.title || "";
  btn.replaceWith(input);
  let done = false;
  const finish = (commit) => {
    if (done) return;
    done = true;
    const title = input.value.trim();
    if (
      commit &&
      title &&
      title !== (item.title || "") &&
      ws?.readyState === WebSocket.OPEN
    ) {
      ws.send(
        JSON.stringify({
          type: "conversation_rename",
          conversation_id: targetId,
          title,
        })
      );
      return;
    }
    renderConversationList();
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      finish(true);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      finish(false);
    }
  });
  input.addEventListener("blur", () => finish(true));
  input.focus();
  input.select();
}

function showChatlog() {
  // 即使还没有消息，也把工具行（模式切换 / 收起对话）露出来。
  chatpanel.classList.remove("hidden");
}

function hideChatlog() {
  chatpanel.classList.add("hidden");
}

function show(el, visible) {
  el.classList.toggle("hidden", !visible);
}

function setInputEnabled(on) {
  if (on) busy = false;
  textInput.disabled = !on;
  sendBtn.disabled = !on;
  askBtn.disabled = !on || !agentHarness;
  if (!on) askMenu.classList.add("hidden");
  show(textrow, on);
  if (on) textInput.focus();
}

function nextTurnId() {
  turnSeq += 1;
  return `t${turnSeq}`;
}

function kindLabel(kind) {
  return { recall: "回忆", discriminate: "辨析", apply: "应用" }[kind] || kind;
}

const QUESTION_TYPE_LABELS = {
  concept: "概念理解",
  business: "业务运用",
  tradeoff: "取舍权衡",
  cost_risk: "成本风险",
  synthesis: "综合判断",
};

function questionTypeLabel(type) {
  return QUESTION_TYPE_LABELS[type] || null;
}

function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderScore(message) {
  scoreLine.textContent =
    message.score == null
      ? `本题未评分：${message.why}`
      : `${message.score} 分：${message.why}`;
  if (message.source_excerpt) {
    const block = document.createElement("div");
    block.className = "score-source";
    const label = document.createElement("span");
    label.className = "score-source-label";
    label.textContent = "出处：";
    const excerpt = document.createElement("span");
    excerpt.textContent = message.source_excerpt;
    block.append(label, excerpt);
    if (message.source_url) {
      const link = document.createElement("a");
      link.className = "score-source-link";
      link.href = message.source_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "看材料";
      block.append(" ", link);
    }
    scoreLine.appendChild(block);
  }
  scoreLine.classList.remove("hidden");
}

function showQuestion(question) {
  currentQuestion = question;
  pendingQuestion = null;
  pendingInputMode = "text";
  pendingTurnId = null;
  currentAnswered = false;
  retryPending = false;
  revealedCurrent = false;
  forceAdvance = false;
  audioSuppressed = false;
  clearLecture(); // 开场讲解只属于本场第一题
  bubble.classList.add("hidden");
  bubble.textContent = "";
  textInput.value = "";
  hideChatlog();
  show(scoreLine, false);
  scoreLine.textContent = "";
  advanceHint.textContent = DEFAULT_ADVANCE_HINT;
  show(advanceHint, false);
  show(sessionPanel, true);
  show(resultEl, false);
  show(finishBtn, true);
  talk.disabled = false;
  startBtn.textContent = "下一题";
  startBtn.disabled = false;
  const typeLabel =
    questionTypeLabel(question.question_type) || kindLabel(question.kind);
  const fallbackLabel = question.origin === "fallback" ? " · 旧题回退" : "";
  progressEl.textContent = `${question.role === "review" ? "复习" : "新题"} · 第 ${question.index} / ${question.total} 题 · ${typeLabel}${fallbackLabel}`;
  questionEl.textContent = question.text;
  optionsEl.innerHTML = "";
  if (question.options) {
    for (const [key, text] of Object.entries(question.options)) {
      const button = document.createElement("button");
      button.className = "option";
      button.textContent = `${key}. ${text}`;
      button.addEventListener("click", () => sendAnswer(key));
      optionsEl.appendChild(button);
    }
  }
  setInputEnabled(true);
  statusEl.textContent = "请作答";
  if (pendingQuestionAudio.length) {
    audioQueue.push(pendingQuestionAudio);
    pendingQuestionAudio = [];
  }
  void pumpAudio();
}

function formatScore(value) {
  if (value == null) return "—";
  return Number(value).toFixed(1).replace(/\.0$/, "");
}

function showResult(result) {
  sessionId = null;
  currentQuestion = null;
  pendingQuestion = null;
  pendingResult = null;
  pendingQuestionAudio = [];
  audioMuted = true;
  feedbackPending = false;
  forceAdvance = false;
  retryPending = false;
  revealedCurrent = false;
  audioSuppressed = false;
  settling = false;
  hideChatlog();
  scoreLine.textContent = "";
  show(advanceHint, false);
  bubble.textContent = "";
  bubble.classList.add("hidden");
  talk.disabled = false;
  show(sessionPanel, false);
  show(finishBtn, false);
  show(textrow, false);
  show(resultEl, true);
  const statusText =
    { completed: "完成", partial: "提前结束", unscored: "未评分" }[result.status] || result.status;
  const scoreText =
    result.session_score == null ? "没有评分" : `${result.session_score} 分`;
  const conceptRows = (result.concepts || [])
    .map((item) => {
      const name = escapeHtml(item.name || item.id || "概念");
      const mastery = item.mastery_updated
        ? `掌握度 ${item.mastery_before} → ${item.mastery_after}（${escapeHtml(
            item.mastery_after_label || ""
          )}）`
        : `掌握度 ${item.mastery_after ?? "—"}（本场未更新）`;
      const scoreParts = [];
      if (item.new_score != null) {
        scoreParts.push(`新题均分 ${formatScore(item.new_score)}`);
      }
      if (item.review_score != null) {
        scoreParts.push(`复习均分 ${formatScore(item.review_score)}`);
      }
      const due = item.review_due_at
        ? `下次复习 ${escapeHtml(item.review_due_at)}`
        : "无复习排期";
      return `<li><strong>${name}</strong>：${mastery}${
        scoreParts.length ? `；${scoreParts.join("，")}` : ""
      }；${due}</li>`;
    })
    .join("");
  const updated = (result.concepts || []).some((item) => item.mastery_updated);
  let note = "";
  if (result.status === "partial") {
    note = "本单元未完成，掌握度未更新；已评分题可能已更新复习排期。";
  } else if (result.status === "unscored") {
    note = "本场没有评上分，掌握度未更新。";
  } else if (!updated) {
    note = "本场掌握度未更新（复习场或没有新题得分）。";
  }
  const scores = (result.scores || [])
    .map((item) => {
      const type = questionTypeLabel(item.question_type);
      const typeText = type ? `【${type}】` : "";
      const source = item.source_excerpt
        ? `<span class="result-source">出处：${escapeHtml(item.source_excerpt)}</span>`
        : "";
      return `<li>${typeText}${
        item.score == null ? "未评分" : item.score + " 分"
      }：${item.why || ""}${source}</li>`;
    })
    .join("");
  resultEl.innerHTML = `<h3>本场结果</h3><p>${statusText} · ${scoreText}</p>${
    conceptRows ? `<ul class="result-concepts">${conceptRows}</ul>` : ""
  }${note ? `<p class="result-note">${note}</p>` : ""}
    <p id="kbsummaryline" class="result-overview">全库：读取中…</p>
    <ol>${scores}</ol>
    <button id="kbfromresult" type="button" class="result-kb">查看知识库</button>`;
  resultEl.querySelector("#kbfromresult")?.addEventListener("click", () => {
    openKnowledgePanel();
  });
  void updateOverviewLine();
  awaitingEnd = true;
  startBtn.textContent = "结束今天的学习";
  startBtn.disabled = false;
  statusEl.textContent = "本场结束";
}

async function updateOverviewLine() {
  const el = document.getElementById("kbsummaryline");
  if (!el) return;
  try {
    const response = await fetch("/api/kb/overview", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const stats = data.stats || {};
    const average =
      stats.avg_mastery == null ? "—" : Number(stats.avg_mastery).toFixed(1);
    el.textContent = `全库：在学 ${stats.active ?? 0} 个 · 平均 ${average} / 5 · 待复习 ${
      stats.due ?? 0
    }`;
  } catch (err) {
    el.textContent = "全库总览暂时不可用";
  }
}

function sendAnswer(text) {
  const clean = String(text || "").trim();
  if (!clean || !sessionId || !currentQuestion) return;
  if (ws?.readyState !== WebSocket.OPEN) {
    statusEl.textContent = "还没连上服务";
    return;
  }
  // 提交答案（回车/按钮/选项）也算一次用户动作：先把正在念的切掉。
  cutAudio();
  audioSuppressed = false;
  if (REPEAT_COMMANDS.has(clean)) {
    const turnId = pendingTurnId || nextTurnId();
    pendingTurnId = null;
    pendingInputMode = "text";
    textInput.value = "";
    show(scoreLine, false);
    setInputEnabled(false);
    statusEl.textContent = "重读题目…";
    ws.send(
      JSON.stringify({
        type: "repeat",
        session_id: sessionId,
        question_id: currentQuestion.id,
        turn_id: turnId,
      })
    );
    return;
  }
  const retry = beginRetry() || retryPending;
  ws.send(
    JSON.stringify({
      type: "answer",
      session_id: sessionId,
      question_id: currentQuestion.id,
      turn_id: pendingTurnId || nextTurnId(),
      text: clean,
      input_mode: pendingInputMode,
      retry,
    })
  );
  retryPending = false;
  pendingTurnId = null;
  pendingInputMode = "text";
  textInput.value = "";
  show(scoreLine, false);
  setInputEnabled(false);
  statusEl.textContent = retry ? "重新评分中…" : "评分中…";
}

// 已评分的题再次开口/提交时，先清掉上一次的分数和回答，只留题目。
function beginRetry() {
  if (!currentAnswered) return false;
  currentAnswered = false;
  feedbackPending = false;
  forceAdvance = false;
  retryPending = true;
  revealedCurrent = false;
  pendingQuestion = null;
  pendingQuestionAudio = [];
  cutAudio();
  audioMuted = false;
  audioSuppressed = false;
  show(scoreLine, false);
  show(advanceHint, false);
  scoreLine.textContent = "";
  setInputEnabled(true);
  statusEl.textContent = "重新作答…";
  return true;
}

function sendFreeTalkText(text) {
  const clean = String(text || "").trim();
  if (!clean) return;
  if (sessionId || currentQuestion) {
    sendAnswer(clean);
    return;
  }
  if (ws?.readyState !== WebSocket.OPEN) {
    statusEl.textContent = "还没连上服务";
    return;
  }
  ws.send(
    JSON.stringify({
      type: "text",
      text: clean,
      turn_id: nextTurnId(),
      conversation_id: conversationId,
      mode: freeTalkMode,
    })
  );
  textInput.value = "";
  setInputEnabled(false);
  statusEl.textContent = "正在想…";
}

function sendTeach(intent) {
  const clean = String(textInput.value || "").trim();
  if (!clean) {
    textInput.focus();
    statusEl.textContent = "先写下你想问什么";
    return;
  }
  if (!sessionId || !currentQuestion) {
    statusEl.textContent = "先开始学习";
    return;
  }
  if (ws?.readyState !== WebSocket.OPEN) {
    statusEl.textContent = "还没连上服务";
    return;
  }
  ws.send(
    JSON.stringify({
      type: "text",
      session_id: sessionId,
      question_id: currentQuestion.id,
      intent,
      turn_id: nextTurnId(),
      text: clean,
    })
  );
  textInput.value = "";
  askMenu.classList.add("hidden");
  setInputEnabled(false);
  statusEl.textContent = intent === "teach" ? "正在准备讲解…" : "正在想怎么解释…";
}

function startSession() {
  if (ws?.readyState !== WebSocket.OPEN) {
    statusEl.textContent = "还没连上服务";
    return;
  }
  localStorage.removeItem(SESSION_KEY);
  sessionId = null;
  currentQuestion = null;
  turnSeq = 0;
  awaitingEnd = false;
  clearUnitLabel();
  clearIntro();
  clearLecture();
  pendingQuestion = null;
  pendingResult = null;
  pendingQuestionAudio = [];
  currentAnswered = false;
  audioMuted = false;
  feedbackPending = false;
  forceAdvance = false;
  startBtn.textContent = "开始今天的学习";
  talk.disabled = true;
  show(resultEl, false);
  show(sessionPanel, false);
  show(finishBtn, true);
  show(textrow, false);
  hideChatlog();
  cancelPending = false;
  cancelling = false;
  settling = false;
  audioSuppressed = false;
  startBtn.disabled = true;
  startBtn.textContent = "正在出题…";
  ws.send(JSON.stringify({ type: "session_start", kind: "daily" }));
  statusEl.textContent = "正在出题…";
}

function finishSession() {
  cutAudio();
  audioSuppressed = true;
  if (!sessionId) {
    // 还在出题：标记取消，等出题回来立刻结算掉，不留一场空会话。
    if (cancelPending) return;
    cancelPending = true;
    cancelling = true;
    show(finishBtn, false);
    statusEl.textContent = "正在结束…";
    return;
  }
  if (settling) return;
  settling = true;
  ws.send(JSON.stringify({ type: "finish", session_id: sessionId, turn_id: nextTurnId() }));
  statusEl.textContent = "正在结算…";
}

function endDay() {
  awaitingEnd = false;
  clearUnitLabel();
  clearIntro();
  clearLecture();
  localStorage.removeItem(SESSION_KEY);
  sessionId = null;
  currentQuestion = null;
  pendingQuestion = null;
  pendingResult = null;
  pendingQuestionAudio = [];
  audioMuted = true;
  feedbackPending = false;
  forceAdvance = false;
  cancelPending = false;
  cancelling = false;
  settling = false;
  audioSuppressed = false;
  stopAudio();
  talk.disabled = false;
  show(sessionPanel, false);
  show(resultEl, false);
  setInputEnabled(true);
  show(finishBtn, false);
  startBtn.textContent = "开始今天的学习";
  startBtn.disabled = false;
  showChatlog();
  statusEl.textContent = "本场已结束，可以继续说话或开始下一场";
}

function stopAudio() {
  if (activeSource) {
    try {
      activeSource.stop();
    } catch (err) {
      // 已经结束的音频源，忽略。
    }
    activeSource = null;
  }
  audioQueue.length = 0;
  audioBatch = [];
  if (audioTimer) {
    clearTimeout(audioTimer);
    audioTimer = null;
  }
  analyser = null;
  speaking = false;
}

// 立刻切音：停掉正在播的，并把这一轮朗读标记成已切断（后续分句丢弃）。
function cutAudio() {
  for (const utterance of playingUtterances) mutedUtterances.add(utterance);
  for (const batch of audioQueue) {
    for (const item of batch) mutedUtterances.add(item.utterance || "");
  }
  for (const item of audioBatch) mutedUtterances.add(item.utterance || "");
  stopAudio();
}

function advanceNow() {
  const next = pendingQuestion;
  const result = pendingResult;
  cutAudio();
  // 点「下一题」等于放弃本题这一串朗读：开场/讲解/题干后面陆续到达的分句也一并丢掉，
  // 直到下一题真正展示（showQuestion）才恢复。
  audioSuppressed = true;
  show(advanceHint, false);

  if (next) {
    pendingQuestion = null;
    pendingResult = null;
    feedbackPending = false;
    retryPending = false;
    audioMuted = true;
    showQuestion(next);
    return;
  }
  if (result) {
    pendingResult = null;
    showResult(result);
    return;
  }
  if (currentAnswered) {
    // 下一题事件已经在路上；到达后立即展示。
    forceAdvance = true;
    statusEl.textContent = "正在切换下一题…";
    return;
  }
  if (!sessionId || !currentQuestion || ws?.readyState !== WebSocket.OPEN) return;

  if (!revealedCurrent) {
    // 未作答：先取参考答案留在屏上，再点一次才跳过。
    revealedCurrent = true;
    startBtn.textContent = "再点一次跳过";
    ws.send(
      JSON.stringify({
        type: "reveal",
        session_id: sessionId,
        question_id: currentQuestion.id,
      })
    );
    statusEl.textContent = "正在取参考答案…";
    return;
  }

  ws.send(
    JSON.stringify({
      type: "skip",
      session_id: sessionId,
      question_id: currentQuestion.id,
      turn_id: nextTurnId(),
    })
  );
  statusEl.textContent = "跳过中…";
}

// ---------- audio queue ----------
// 每段语音先按到达顺序缓冲，120ms 内没有新块就按 seq 排序去重后播放。
let audioBatch = [];
const audioQueue = [];
let audioTimer = null;
let audioPlaying = false;
const playingUtterances = new Set();

async function playBatch(batch) {
  const seen = new Set();
  const ordered = [];
  for (const item of batch.slice().sort((a, b) => a.seq - b.seq)) {
    // intro 和第一题都从 seq=1 开始；按 utterance+seq 去重，避免丢掉其中一段。
    const key = `${item.utterance || ""}:${item.seq}`;
    if (seen.has(key)) continue;
    seen.add(key);
    ordered.push(item);
  }
  if (!ordered.length) return;
  playingUtterances.clear();
  for (const item of ordered) playingUtterances.add(item.utterance || "");
  statusEl.textContent = "说话中…";
  // 分句合成的每段都是完整 WAV，拼在一起会丢后段；WAV 逐段播，其它格式（mp3 流）按序拼。
  const isWav = ordered.every((item) => (item.mime || "").includes("wav"));
  if (isWav) {
    for (const item of ordered) {
      await playBuffer(base64ToArrayBuffer(item.data));
    }
    return;
  }
  await playBuffer(mergeBase64Chunks(ordered.map((item) => item.data)));
}

async function pumpAudio() {
  if (audioPlaying) return;
  audioPlaying = true;
  while (audioQueue.length) {
    await playBatch(audioQueue.shift());
    // 反馈播完再展示下一题/结果；若还有反馈批次则继续播。
    if ((pendingQuestion || pendingResult) && audioQueue.length === 0) break;
  }
  audioPlaying = false;
  if (pendingQuestion || pendingResult) {
    flushPendingAfterAudio();
    return;
  }
  if (currentQuestion) {
    statusEl.textContent = currentAnswered ? "点「下一题」继续" : "请作答";
  } else if (resultEl.classList.contains("hidden")) {
    statusEl.textContent = "可以继续说话";
  }
}

function audioPending() {
  return audioPlaying || audioQueue.length > 0 || audioBatch.length > 0 || audioTimer !== null;
}

function flushPendingAfterAudio() {
  if (feedbackPending || audioPending()) return;
  if (pendingResult) {
    showResult(pendingResult);
    return;
  }
  if (pendingQuestion) {
    // 反馈播完不再自动跳题：留在本题，等用户点「下一题」。
    show(advanceHint, true);
    statusEl.textContent = "点「下一题」继续";
  }
}

function flushAudioBatch() {
  if (audioTimer) {
    clearTimeout(audioTimer);
    audioTimer = null;
  }
  if (audioBatch.length) {
    audioQueue.push(audioBatch);
    audioBatch = [];
  }
  void pumpAudio();
}

function enqueueToBatch(message) {
  const seq = Number(message.seq) || 1;
  if (
    !audioBatch.some(
      (item) => item.utterance === message.utterance && item.seq === seq,
    )
  ) {
    audioBatch.push(message);
  }
  if (audioTimer) clearTimeout(audioTimer);
  audioTimer = window.setTimeout(() => {
    audioTimer = null;
    flushAudioBatch();
  }, 120);
}

function enqueueAudio(message) {
  if (audioSuppressed) return;
  const seq = Number(message.seq) || 1;
  const utterance = message.utterance || "";
  // 被切音切断的那一轮朗读，后续分句直接丢弃；只有新一轮（seq=1）才恢复。
  if (mutedUtterances.has(utterance)) {
    if (seq !== 1) return;
    mutedUtterances.delete(utterance);
  }
  // 下一题还没展示时，它的题目音频先存着，等展示后再播。
  if (utterance === "question") {
    if (pendingQuestion) {
      if (!pendingQuestionAudio.some((item) => item.seq === seq)) {
        pendingQuestionAudio.push(message);
      }
      return;
    }
    enqueueToBatch(message);
    return;
  }
  if (audioMuted) return;
  enqueueToBatch(message);
}

// ---------- websocket ----------
function connect() {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${scheme}://${window.location.host}/ws`);

  ws.onopen = () => {
    statusEl.textContent = "已连接，等它就绪…";
  };
  ws.onclose = () => {
    setInputEnabled(false);
    statusEl.textContent = "连接断开，3 秒后重连";
    notify("连接断开，3 秒后重连");
    window.setTimeout(connect, 3000);
  };
  ws.onerror = () => {
    setInputEnabled(false);
    statusEl.textContent = "连接出错，检查服务是否在运行";
    notify("连接出错，检查服务是否在运行");
  };
  ws.onmessage = async (event) => {
    const message = JSON.parse(event.data);

    if (message.type === "ready") {
      const modes = message.modes || {};
      const fake = Object.keys(modes).filter((key) => modes[key] === "fake");
      const label = fake.length ? ` · 离线假模式（${fake.join("/")}）` : "";
      if (message.emotion) setMood(message.emotion.comfort, message.emotion.energy);
      agentHarness = message.agent_harness !== false;
      askBtn.classList.toggle("hidden", !agentHarness);
      askBtn.disabled = !agentHarness;
      startBtn.disabled = false;
      startBtn.textContent = "开始今天的学习";
      statusEl.textContent = `已就绪${label}，点“开始今天的学习”`;
      if (!sessionId) {
        const saved = localStorage.getItem(SESSION_KEY);
        if (saved) sessionId = saved;
      }
      if (!sessionId) {
        talk.disabled = false;
        setInputEnabled(true);
      }
      if (message.notes?.length) metrics.textContent = message.notes.join(" / ");
      ws.send(JSON.stringify({ type: "conversation_list" }));
      if (sessionId) {
        ws.send(JSON.stringify({ type: "session_resume", session_id: sessionId }));
        statusEl.textContent = "正在恢复上一场…";
      }
      return;
    }

    if (message.type === "conversation_list") {
      const items = message.items || [];
      syncConversationSelect(items);
      if (!items.length) {
        ws.send(JSON.stringify({ type: "conversation_new" }));
        return;
      }
      const exists = items.some((item) => item.conversation_id === conversationId);
      if (!exists) setConversation(items[0].conversation_id);
      ws.send(
        JSON.stringify({
          type: "conversation_load",
          conversation_id: conversationId,
        })
      );
      return;
    }

    if (message.type === "conversation_created") {
      setConversation(message.conversation_id);
      renderConversation([]);
      conversationItems = [
        {
          conversation_id: message.conversation_id,
          title: message.title || "",
          message_count: 0,
        },
        ...conversationItems,
      ];
      renderConversationList();
      statusEl.textContent = "新对话，可以开始说话";
      return;
    }

    if (message.type === "conversation_loaded") {
      setConversation(message.conversation_id);
      renderConversation(message.messages || []);
      renderConversationList();
      statusEl.textContent = "已加载历史对话，可以继续说话";
      return;
    }

    if (message.type === "conversation_renamed") {
      const item = conversationItems.find(
        (entry) => entry.conversation_id === message.conversation_id
      );
      if (item) {
        item.title = message.title;
        renderConversationList();
      }
      statusEl.textContent = "已重命名";
      return;
    }

    if (message.type === "conversation_deleted") {
      conversationItems = conversationItems.filter(
        (entry) => entry.conversation_id !== message.conversation_id
      );
      renderConversationList();
      if (message.conversation_id !== conversationId) {
        statusEl.textContent = "已删除对话";
        return;
      }
      const next = conversationItems[0];
      if (next) {
        setConversation(next.conversation_id);
        ws.send(
          JSON.stringify({
            type: "conversation_load",
            conversation_id: next.conversation_id,
          })
        );
        statusEl.textContent = "已删除当前对话，切换到最新一个";
      } else {
        renderConversation([]);
        ws.send(JSON.stringify({ type: "conversation_new" }));
        statusEl.textContent = "已删除当前对话";
      }
      return;
    }

    if (message.type === "emotion") {
      setMood(message.comfort, message.energy);
      return;
    }

    if (message.type === "session_ready") {
      sessionId = message.session_id;
      localStorage.setItem(SESSION_KEY, sessionId);
      if (cancelPending) {
        // 出题期间已经点了「提前结束」：直接把这场结算掉，不展示、不播。
        cancelPending = false;
        settling = true;
        ws.send(
          JSON.stringify({
            type: "finish",
            session_id: sessionId,
            turn_id: nextTurnId(),
          })
        );
        statusEl.textContent = "正在结束…";
        return;
      }
      if (message.emotion) setMood(message.emotion.comfort, message.emotion.energy);
      setUnitLabel(message.unit);
      if (message.intro) setIntro(message.intro);
      bubble.classList.add("hidden");
      scoreLine.classList.add("hidden");
      showQuestion(message.question);
      return;
    }

    if (message.type === "question") {
      // 同一题的重复事件（重答时服务端会再发一遍）不再展示、不再重念题干。
      if (
        !forceAdvance &&
        (currentQuestion?.id === message.id || pendingQuestion?.id === message.id)
      ) {
        return;
      }
      bubble.classList.add("hidden");
      if (forceAdvance) {
        forceAdvance = false;
        feedbackPending = false;
        audioMuted = true;
        cutAudio();
        showQuestion(message);
        return;
      }
      if (feedbackPending || audioPending()) {
        pendingQuestion = message;
        flushPendingAfterAudio();
        return;
      }
      showQuestion(message);
      return;
    }

    if (message.type === "reveal") {
      if (!currentQuestion || message.question_id !== currentQuestion.id) return;
      const text = String(message.text || "").trim();
      scoreLine.innerHTML = "";
      const block = document.createElement("div");
      block.className = "score-source";
      const label = document.createElement("span");
      label.className = "score-source-label";
      label.textContent = text ? "参考答案：" : "这题没有现成参考答案。";
      block.appendChild(label);
      if (text) {
        const body = document.createElement("span");
        body.textContent = text;
        block.appendChild(body);
      }
      scoreLine.appendChild(block);
      show(scoreLine, true);
      advanceHint.textContent = "再点一次「下一题」跳过本题";
      show(advanceHint, true);
      statusEl.textContent = "看完点「下一题」跳过";
      return;
    }

    if (message.type === "score") {
      currentAnswered = true;
      feedbackPending = true;
      retryPending = false;
      audioMuted = false;
      renderScore(message);
      bubble.classList.add("hidden");
      if (message.duplicate) {
        statusEl.textContent = "这题已经评过分，继续下一题";
      }
      return;
    }

    if (message.type === "lecture") {
      setLecture(message.text);
      return;
    }

    if (message.type === "agent_status") {
      if (message.phase === "searching") {
        statusEl.textContent =
          message.tool === "search_web"
            ? "正在查网上资料…"
            : message.tool === "read_concept"
              ? "正在查概念…"
              : "正在查材料…";
      } else {
        statusEl.textContent = "正在想…";
      }
      return;
    }

    if (message.type === "teach_reply") {
      bubble.textContent = `讲解：${message.text}`;
      if (Array.isArray(message.sources) && message.sources.length) {
        const lines = message.sources.map(
          (source) => `[${source.index}] ${source.title || source.url || "来源"}`
        );
        bubble.textContent += `\n来源：${lines.join("；")}`;
      }
      bubble.classList.remove("hidden");
      setInputEnabled(true);
      talk.disabled = false;
      statusEl.textContent = "讲完了，继续答当前题";
      return;
    }

    if (message.type === "reply") {
      busy = false;
      talk.disabled = false;
      audioMuted = false;
      if (message.conversation_id) setConversation(message.conversation_id);
      appendChatMessage("assistant", message.text, message.mode, message.sources);
      setInputEnabled(true);
      statusEl.textContent = "说话中…";
      return;
    }

    if (message.type === "probe") {
      bubble.textContent = `追问：${message.text}`;
      bubble.classList.remove("hidden");
      setInputEnabled(true);
      talk.disabled = false;
      statusEl.textContent = "请回答追问";
      return;
    }

    if (message.type === "transcript") {
      if (!sessionId || !currentQuestion) {
        if (message.conversation_id) setConversation(message.conversation_id);
        appendChatMessage("user", message.text);
        statusEl.textContent = "正在想…";
        return;
      }
      bubble.textContent = `你：${message.text}`;
      bubble.classList.remove("hidden");
      if (message.needs_confirmation) {
        pendingInputMode = "voice";
        pendingTurnId = message.turn_id || null;
        textInput.value = message.text;
        setInputEnabled(true);
        talk.disabled = false;
        statusEl.textContent =
          message.reason === "mixed"
            ? "像在提问：可改一下再提交"
            : "没听清：确认或修改后再提交";
      } else {
        statusEl.textContent =
          sessionId && currentQuestion ? "识别完成，正在评分…" : "正在想…";
      }
      return;
    }

    if (message.type === "session_result") {
      localStorage.removeItem(SESSION_KEY);
      bubble.classList.add("hidden");
      if (cancelling) {
        // 出题期间取消的那一场：静默收尾，不回结果卡。
        cancelling = false;
        settling = false;
        endDay();
        statusEl.textContent = "已结束，可以重新开始";
        return;
      }
      settling = false;
      if (forceAdvance || (!feedbackPending && !audioPending())) {
        forceAdvance = false;
        feedbackPending = false;
        audioMuted = true;
        stopAudio();
        showResult(message);
        return;
      }
      pendingResult = message;
      return;
    }

    if (message.type === "feedback_end") {
      feedbackPending = false;
      if (pendingQuestion || pendingResult) flushPendingAfterAudio();
      return;
    }

    if (message.type === "session_expired") {
      localStorage.removeItem(SESSION_KEY);
      sessionId = null;
      currentQuestion = null;
      pendingQuestion = null;
      pendingResult = null;
      pendingQuestionAudio = [];
      feedbackPending = false;
      forceAdvance = false;
      audioMuted = true;
      awaitingEnd = false;
      clearUnitLabel();
      clearIntro();
      clearLecture();
      startBtn.textContent = "开始今天的学习";
      talk.disabled = false;
      showChatlog();
      show(sessionPanel, false);
      show(finishBtn, false);
      show(textrow, false);
      startBtn.disabled = false;
      statusEl.textContent = "上一场已过期，点“开始今天的学习”";
      return;
    }

    if (message.type === "audio_chunk") {
      enqueueAudio(message);
      return;
    }

    if (message.type === "error") {
      busy = false;
      const active = Boolean(sessionId && currentQuestion);
      setInputEnabled(active);
      talk.disabled = false;
      if (message.stage === "session" && !active) {
        // 出题失败时回到初始态，避免主按钮停在 disabled。
        endDay();
      }
      statusEl.textContent = message.message;
      return;
    }

    if (message.type === "warning") {
      metrics.textContent = message.message;
      return;
    }
  };
}

connect();

// ---------- controls ----------
initKnowledgePanel({
  canStartUnit: () => !sessionId && !awaitingEnd,
  startBlockedText: () =>
    awaitingEnd ? "先结束本场" : "当前单元进行中",
  onStartUnit: () => {
    startSession();
  },
});
initHistoryPanel();
knowledgeBtn?.addEventListener("click", () => {
  openKnowledgePanel();
});
startBtn.addEventListener("click", () => {
  if (awaitingEnd) {
    endDay();
    return;
  }
  if (sessionId && currentQuestion) {
    advanceNow();
    return;
  }
  startSession();
});
// ---------- 自由对话 / 教学讲解 模式 ----------
function renderModeSwitch() {
  if (!modeSwitch) return;
  const teaching = freeTalkMode === "teach";
  modeSwitch.textContent = teaching ? "教学" : "自由";
  modeSwitch.classList.toggle("teaching", teaching);
  modeSwitch.setAttribute("aria-pressed", String(teaching));
}

modeSwitch?.addEventListener("click", () => {
  freeTalkMode = freeTalkMode === "teach" ? "chat" : "teach";
  try {
    localStorage.setItem("coach.freetalkmode", freeTalkMode);
  } catch (err) {
    // 隐私模式禁写存储：只保留内存状态。
  }
  renderModeSwitch();
  notify(
    freeTalkMode === "teach"
      ? "教学模式：按讲解方式回答"
      : "自由模式：像聊天一样说"
  );
});
renderModeSwitch();

finishBtn.addEventListener("click", finishSession);
newConversationBtn.addEventListener("click", () => {
  if (ws?.readyState !== WebSocket.OPEN) {
    statusEl.textContent = "还没连上服务";
    return;
  }
  ws.send(JSON.stringify({ type: "conversation_new" }));
  statusEl.textContent = "正在新建对话…";
});
convTrigger.addEventListener("click", () => {
  setConvListOpen(convList.classList.contains("hidden"));
});
convList.addEventListener("click", (event) => {
  const item = event.target.closest(".conv-item");
  if (!item) return;
  setConvListOpen(false);
  if (item.dataset.id === conversationId) return;
  if (ws?.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: "conversation_load", conversation_id: item.dataset.id }));
  statusEl.textContent = "正在加载对话…";
});
convList.addEventListener("contextmenu", (event) => {
  const item = event.target.closest(".conv-item");
  if (!item) return;
  event.preventDefault();
  menuConversationId = item.dataset.id;
  const width = 132;
  const height = 84;
  chatmenu.style.left = `${Math.min(event.clientX, window.innerWidth - width - 8)}px`;
  chatmenu.style.top = `${Math.min(event.clientY, window.innerHeight - height - 8)}px`;
  chatmenu.classList.remove("hidden");
});
document.addEventListener("click", (event) => {
  if (!convPicker.contains(event.target) && !chatmenu.contains(event.target)) {
    setConvListOpen(false);
  }
  if (!chatmenu.contains(event.target)) closeChatmenu();
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  setConvListOpen(false);
  closeChatmenu();
});
renameBtn.addEventListener("click", () => {
  const targetId = menuConversationId;
  closeChatmenu();
  if (!targetId || ws?.readyState !== WebSocket.OPEN) {
    statusEl.textContent = "还没连上服务";
    return;
  }
  startRename(targetId);
});
deleteBtn.addEventListener("click", () => {
  const item = conversationItems.find(
    (entry) => entry.conversation_id === menuConversationId
  );
  closeChatmenu();
  if (!item || ws?.readyState !== WebSocket.OPEN) {
    statusEl.textContent = "还没连上服务";
    return;
  }
  const label = item.title || "未命名对话";
  if (!window.confirm(`删除对话「${label}」？消息会一并删除，不能恢复。`)) return;
  ws.send(
    JSON.stringify({ type: "conversation_delete", conversation_id: item.conversation_id })
  );
});
chattoggle.addEventListener("click", () => {
  const collapsed = chatpanel.classList.toggle("collapsed");
  chattoggle.textContent = collapsed ? "展开对话" : "收起对话";
  chattoggle.setAttribute("aria-expanded", String(!collapsed));
  if (!collapsed) chatlog.scrollTop = chatlog.scrollHeight;
});
sendBtn.addEventListener("click", () => sendFreeTalkText(textInput.value));
textInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") sendFreeTalkText(textInput.value);
});
askBtn.addEventListener("click", () => {
  if (!sessionId || !currentQuestion) {
    statusEl.textContent = "先开始学习";
    return;
  }
  askMenu.classList.toggle("hidden");
});
askMenu.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-intent]");
  if (!button) return;
  sendTeach(button.dataset.intent);
});
document.addEventListener("click", (event) => {
  if (askMenu.classList.contains("hidden")) return;
  if (askMenu.contains(event.target) || askBtn.contains(event.target)) return;
  askMenu.classList.add("hidden");
});

talk.addEventListener("click", async () => {
  if (recording) {
    vad.end();
    statusEl.textContent = "手动结束，正在识别…";
    stopRecording();
    return;
  }
  if (ws?.readyState !== WebSocket.OPEN) {
    notify("还没连上服务");
    return;
  }
  const retried = beginRetry();
  if (!retried) {
    // 未作答时点「开始说话」：先立刻切音，再开麦。
    cutAudio();
  }
  try {
    await startRecording();
  } catch (err) {
    notify(err.message);
  }
});

// ---------- render loop ----------
const clock = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);
  const delta = Math.min(clock.getDelta(), 0.05);

  let level = 0;
  if (analyser && speaking) {
    const data = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i += 1) {
      const value = (data[i] - 128) / 128;
      sum += value * value;
    }
    level = Math.sqrt(sum / data.length);
  }

  const target = Math.min(1, level * 6);
  mouth += (target - mouth) * Math.min(1, delta * 18);

  nextBlink -= delta;
  if (nextBlink <= 0) {
    blinkUntil = 0.12;
    nextBlink = 2.5 + Math.random() * 3;
  }
  blink = blinkUntil > 0 ? 1 : 0;
  blinkUntil -= delta;

  if (vrm?.expressionManager) {
    const [expression, intensity] = moodExpression(mood);
    const scale = speaking ? 0.15 : 1;
    for (const name of EMOTION_EXPRESSIONS) {
      const target = name === expression ? intensity * scale : 0;
      const current = expressionValues.get(name) ?? 0;
      const next = current + (target - current) * Math.min(1, delta * 4);
      expressionValues.set(name, next);
      const applied = name === "happy" && blink > 0 ? Math.min(next, 0.25) : next;
      vrm.expressionManager.setValue(name, applied);
    }
    vrm.expressionManager.setValue("aa", mouth);
    vrm.expressionManager.setValue("blink", blink);

    if (headNode && headBase) {
      const t = clock.elapsedTime;
      const speed = 0.35 + mood.energy * 0.35;
      const lowEnergy = Math.max(0, 0.5 - mood.energy);
      const lowComfort = mood.comfort < -0.3 ? 0.02 : 0;
      const pitch = clamp(
        lowEnergy * 0.08 + lowComfort + Math.sin(t * speed) * 0.015,
        0.04
      );
      const yaw = clamp(Math.sin(t * speed * 0.6 + 1.2) * 0.025, 0.03);
      headNode.rotation.x = headBase.x + pitch;
      headNode.rotation.y = headBase.y + yaw;
    }
    if (neckNode && neckBase) {
      const t = clock.elapsedTime;
      const speed = 0.35 + mood.energy * 0.35;
      const lowEnergy = Math.max(0, 0.5 - mood.energy);
      neckNode.rotation.x =
        neckBase.x + clamp(lowEnergy * 0.04 + Math.sin(t * speed + 0.5) * 0.008, 0.02);
    }
    vrm.update(delta);
  }

  if (placeholder) {
    placeholder.rotation.y = Math.sin(clock.elapsedTime * 0.5) * 0.08;
    placeholder.position.y = Math.sin(clock.elapsedTime * 0.9) * 0.01;
    if (placeholderMouth) placeholderMouth.scale.y = 1 + mouth * 8;
  }

  renderer.render(scene, camera);
}

animate();

// 浏览器验收钩子：只读快照 + 设置 mood/说话态，方便 Playwright 校验表情与头部幅度。
window.__emotionFace = {
  setMood,
  setSpeaking(on) {
    speaking = Boolean(on);
  },
  snapshot() {
    return {
      mood: { ...mood },
      speaking,
      hasVrm: Boolean(vrm?.expressionManager),
      expressions: Object.fromEntries(expressionValues),
      head: headNode && headBase
        ? {
            pitch: headNode.rotation.x - headBase.x,
            yaw: headNode.rotation.y - headBase.y,
          }
        : null,
    };
  },
};
