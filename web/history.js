// 最近 24 小时答题记录：右上角按钮 + 右侧抽屉，只读接口。

const panel = document.getElementById("historypanel");
const closeButton = document.getElementById("historyclose");
const listEl = document.getElementById("historylist");
const trigger = document.getElementById("historybtn");

let initialized = false;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatTime(iso) {
  const text = String(iso || "");
  return text.length >= 16 ? `${text.slice(5, 10)} ${text.slice(11, 16)}` : text;
}

function renderItem(item) {
  const concept = item.concept_name ? ` · ${escapeHtml(item.concept_name)}` : "";
  const answer = item.answer_text
    ? `<p class="history-answer"><span>我的回答</span>${escapeHtml(item.answer_text)}</p>`
    : "";
  const feedback = item.feedback
    ? `<p class="history-feedback"><span>评语与答案</span>${escapeHtml(item.feedback)}</p>`
    : "";
  return `<li class="history-item">
    <div class="history-top">
      <strong class="history-score">${escapeHtml(item.score)} 分</strong>
      <span class="history-meta">${escapeHtml(formatTime(item.answered_at))}${concept}</span>
    </div>
    <p class="history-question">${escapeHtml(item.question_text)}</p>
    <div class="history-detail hidden">${answer}${feedback}</div>
  </li>`;
}

async function refresh() {
  if (!listEl) return;
  listEl.innerHTML = `<p class="kb-muted">正在读取…</p>`;
  try {
    const response = await fetch("/api/history/answers?hours=24&limit=50", {
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const items = data.items || [];
    if (!items.length) {
      listEl.innerHTML = `<p class="kb-empty">最近 24 小时还没有答过题。</p>`;
      return;
    }
    listEl.innerHTML = `<h3>已答 ${items.length} 题</h3>
      <ul class="history-list">${items.map(renderItem).join("")}</ul>`;
    listEl.querySelectorAll(".history-item").forEach((item) => {
      item.addEventListener("click", () => {
        item.classList.toggle("open");
        item.querySelector(".history-detail")?.classList.toggle("hidden");
      });
    });
  } catch (err) {
    listEl.innerHTML = `<p class="kb-error">读取失败：${escapeHtml(err?.message || err)}</p>
      <button type="button" class="kb-retry">重试</button>`;
    listEl.querySelector(".kb-retry")?.addEventListener("click", () => void refresh());
  }
}

export function openHistoryPanel() {
  if (!panel) return;
  panel.classList.remove("hidden");
  void refresh();
}

export function closeHistoryPanel() {
  panel?.classList.add("hidden");
}

export function initHistoryPanel() {
  if (initialized) return;
  initialized = true;
  trigger?.addEventListener("click", openHistoryPanel);
  closeButton?.addEventListener("click", closeHistoryPanel);
  panel?.addEventListener("click", (event) => {
    if (event.target === panel) closeHistoryPanel();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && panel && !panel.classList.contains("hidden")) {
      closeHistoryPanel();
    }
  });
}
