const panel = document.getElementById("kbpanel");
const closeButton = document.getElementById("kbclose");
const todayEl = document.getElementById("kbtoday");
const progressEl = document.getElementById("kbprogress");
const historyEl = document.getElementById("kbhistory");

let canStartUnit = () => true;
let startBlockedText = () => "当前单元进行中";
let onStartUnit = () => {};
let initialized = false;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      if (data?.error) message = data.error;
    } catch (err) {
      // 非 JSON 错误体，保留状态码。
    }
    throw new Error(message);
  }
  return response.json();
}

function showError(container, title, error) {
  container.innerHTML = `<h3>${escapeHtml(title)}</h3>
    <p class="kb-error">读取失败：${escapeHtml(error?.message || String(error))}</p>
    <button type="button" class="kb-retry">重试</button>`;
  container.querySelector(".kb-retry")?.addEventListener("click", () => {
    void refreshKnowledgePanel();
  });
}

function conceptCard(concept, badge) {
  const due = concept.review_due_at
    ? ` · 复习到期 ${escapeHtml(concept.review_due_at)}`
    : "";
  return `<div class="kb-concept">
    <div class="kb-concept-head">
      <strong>${escapeHtml(concept.name || concept.id)}</strong>
      <span class="kb-badge">${escapeHtml(badge)}</span>
    </div>
    <p class="kb-muted">${escapeHtml(concept.plain_def || "")}</p>
    <p class="kb-meta">掌握度 ${concept.mastery ?? 0} / 5 · ${escapeHtml(
      concept.mastery_label || ""
    )}${due}</p>
    <p class="kb-reason">${escapeHtml(concept.reason || "")}</p>
  </div>`;
}

function renderProposal(proposal) {
  if (!proposal.available) {
    todayEl.innerHTML = `<h3>今天学什么</h3>
      <div class="kb-empty">
        <p>${escapeHtml(proposal.reason || "今天没有可出的题")}</p>
        <p class="kb-muted">可以补充材料或确认新概念，也可以先自由对话。</p>
      </div>`;
    return;
  }

  const main = proposal.main ? conceptCard(proposal.main, "主学") : "";
  const review = proposal.review
    ? conceptCard(proposal.review, proposal.same_concept ? "同概念复习" : "复习")
    : "";
  const chips = (proposal.slots || [])
    .map(
      (slot) =>
        `<span class="kb-chip ${slot.role === "review" ? "review" : ""}">${escapeHtml(
          slot.label || slot.type
        )}<em>${slot.role === "review" ? "复习" : "新题"}</em></span>`
    )
    .join("");
  const deferred =
    proposal.deferred_reviews > 0
      ? `<p class="kb-muted">另有 ${proposal.deferred_reviews} 个到期复习顺延。</p>`
      : "";
  const enabled = canStartUnit();
  const blockedText = enabled ? "" : startBlockedText();
  todayEl.innerHTML = `<h3>今天学什么</h3>
    <div class="kb-unit-meta">
      <span>约 ${proposal.estimate_minutes || 20} 分钟 · ${
        proposal.question_count || 5
      } 题</span>
      <span class="kb-muted">${escapeHtml(proposal.date || "")}</span>
    </div>
    ${main}
    ${review}
    <div class="kb-chips">${chips}</div>
    ${deferred}
    <button id="kbstart" type="button" class="kb-start" ${
      enabled ? "" : "disabled"
    }>${enabled ? "开始这个单元" : escapeHtml(blockedText)}</button>`;
  todayEl.querySelector("#kbstart")?.addEventListener("click", () => {
    if (!canStartUnit()) return;
    closeKnowledgePanel();
    onStartUnit();
  });
}

function renderProgress(overview) {
  const stats = overview.stats || {};
  const average =
    stats.avg_mastery == null ? "—" : Number(stats.avg_mastery).toFixed(1);
  const distribution = stats.distribution || [];
  const max = Math.max(1, ...distribution.map((item) => item.count || 0));
  const bars = distribution
    .map(
      (item) => `<div class="kb-dist-row">
        <span>${escapeHtml(item.label)}</span>
        <div class="kb-bar"><i style="width:${Math.round(
          ((item.count || 0) / max) * 100
        )}%"></i></div>
        <span>${item.count || 0}</span>
      </div>`
    )
    .join("");
  const rows = (overview.concepts || [])
    .map((concept) => {
      const dots = [0, 1, 2, 3, 4]
        .map((index) => `<i class="${index < (concept.mastery || 0) ? "on" : ""}"></i>`)
        .join("");
      const due = concept.review_due_at
        ? concept.overdue_days > 0
          ? `逾期 ${concept.overdue_days} 天`
          : "今日待复习"
        : concept.last_seen
          ? `上次 ${concept.last_seen}`
          : "未学过";
      return `<li class="kb-concept-row">
        <div class="kb-concept-name"><strong>${escapeHtml(
          concept.name || concept.id
        )}</strong><span class="kb-muted">${escapeHtml(
          concept.mastery_label || ""
        )}</span></div>
        <div class="kb-dots">${dots}</div>
        <span class="kb-due">${escapeHtml(due)}</span>
      </li>`;
    })
    .join("");
  progressEl.innerHTML = `<h3>掌握程度</h3>
    <p class="kb-stats">在学 ${stats.active ?? 0} 个 · 平均 ${average} / 5 · 待复习 ${
      stats.due ?? 0
    } · 薄弱 ${stats.weak ?? 0}</p>
    <p class="kb-muted">已掌握 ${stats.known ?? 0} · 跳过 ${
      stats.skipped ?? 0
    } · 待确认 ${stats.proposed ?? 0}</p>
    <div class="kb-dist">${bars}</div>
    ${
      rows
        ? `<ul class="kb-concept-list">${rows}</ul>`
        : `<p class="kb-empty">还没有在学概念，先去确认概念或补材料。</p>`
    }`;
}

function renderHistory(units) {
  const statusLabels = {
    completed: "完成",
    partial: "提前结束",
    unscored: "未评分",
  };
  const kindLabels = { daily: "日常", review: "复习" };
  const rows = units
    .map(
      (unit) => `<li>
        <span>${escapeHtml(unit.date || "")}</span>
        <span class="kb-muted">${escapeHtml(kindLabels[unit.kind] || unit.kind || "")}</span>
        <span class="kb-status ${escapeHtml(unit.status || "")}">${escapeHtml(
          statusLabels[unit.status] || unit.status || ""
        )}</span>
        <span>${unit.session_score == null ? "未评分" : `${unit.session_score} 分`}</span>
        <span class="kb-muted">${(unit.concept_names || [])
          .map((name) => escapeHtml(name))
          .join("、")}</span>
      </li>`
    )
    .join("");
  historyEl.innerHTML = `<h3>最近单元</h3>${
    rows
      ? `<ul class="kb-history">${rows}</ul>`
      : `<p class="kb-empty">还没有完成过单元。</p>`
  }`;
}

function renderLoading() {
  todayEl.innerHTML = `<h3>今天学什么</h3><p class="kb-muted">正在读取知识库…</p>`;
  progressEl.innerHTML = `<h3>掌握程度</h3><p class="kb-muted">正在读取…</p>`;
  historyEl.innerHTML = `<h3>最近单元</h3><p class="kb-muted">正在读取…</p>`;
}

export async function refreshKnowledgePanel() {
  if (!panel || panel.classList.contains("hidden")) return;
  renderLoading();
  const [proposalResult, overviewResult] = await Promise.allSettled([
    fetchJson("/api/kb/unit/proposal"),
    fetchJson("/api/kb/overview"),
  ]);
  if (proposalResult.status === "fulfilled") {
    renderProposal(proposalResult.value);
  } else {
    showError(todayEl, "今天学什么", proposalResult.reason);
  }
  if (overviewResult.status === "fulfilled") {
    renderProgress(overviewResult.value);
    renderHistory(overviewResult.value.recent_units || []);
  } else {
    showError(progressEl, "掌握程度", overviewResult.reason);
    showError(historyEl, "最近单元", overviewResult.reason);
  }
}

export function openKnowledgePanel() {
  if (!panel) return;
  panel.classList.remove("hidden");
  void refreshKnowledgePanel();
}

export function closeKnowledgePanel() {
  panel?.classList.add("hidden");
}

export function initKnowledgePanel({
  canStartUnit: canStart,
  startBlockedText: blocked,
  onStartUnit: start,
}) {
  if (typeof canStart === "function") canStartUnit = canStart;
  if (typeof blocked === "function") startBlockedText = blocked;
  if (typeof start === "function") onStartUnit = start;
  if (initialized) return;
  initialized = true;
  closeButton?.addEventListener("click", closeKnowledgePanel);
  panel?.addEventListener("click", (event) => {
    if (event.target === panel) closeKnowledgePanel();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && panel && !panel.classList.contains("hidden")) {
      closeKnowledgePanel();
    }
  });
}
