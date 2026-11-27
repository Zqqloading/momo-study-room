# Proposal

## Why

点「开始今天的学习」时，主按钮直接走 `Coach.start()` → `Planner.next_concept`，只按“难度低 + 最久没见”选主概念，完全不看最近答题得分；知识库面板里的 `propose()` 是另一套只读预览，按钮并不经过它。结果是：同一个可解锁主题会被反复选中，最近答错的主题不会被提议复习，会话也没有任何开场说明。

本次把开始学习改成“看进度说话”：先找最近失手的主题，再找掌握度最低的主题，都没有时稳定随机；第一句话说出提议，然后直接出第一题。验收标准：页面上故意答错一个主题，再点开始，第一句话提议复习该主题；新建对话后判断仍然存在。

## What Changes

- **进度选题**：新增选题器，顺序为“最近失手 → 掌握度最低（包含未学过的 0）→ 无信号时按天稳定随机”。选中主题作为本场主概念（`role=new`），沿用 3 新 + 2 复习；mastery 会更新。
- **最近失手口径**：按主题取最近一次有评分的作答；任一题 <60 或该次均分 <80 即命中；未结算但已作答的题也算。同一天答错、`review_due_at` 为次日时仍能命中。
- **开场白**：`session_ready` 增加 `intro` 与 `focus`；开场白由程序按事实拼，先于第一题音频播放；TTS 失败不阻塞；`session_resume` 不重播。
- **面板口径统一**：`GET /api/kb/overview` 的 `weak` 改为“最近失手或 mastery<=1 且学过”，与 agent 的提议一致。
- **长期记忆**：复用现有 SQLite 读模型（`concepts` + `sessions` + `session_questions`），不新增表/列，schema 仍为 v6；新建对话不影响进度。
- **主题清单**：继续用 `concepts.yaml` 维护，不新增管理 UI。
- 不改变：mastery 公式、5 题配比、复习间隔、出题/评分/语音链路、自由对话协议。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `coach-session`: 会话启动的主概念改按进度选题；`session_ready` 增加 `intro`/`focus` 并在第一题前朗读。
- `learning-unit`: 今日提议的主概念与理由改按进度档位；总览 `weak` 口径与 agent 统一。

## Impact

- 代码：`core/coach.py`（选题、开场白、`propose()` 复用）、`core/store.py`（按概念取最近一次评分）、`core/progress.py`（weak 口径）、`bff/main.py`（`session_ready` 序列化与 intro 音频）、`web/app.js` / `web/style.css`（显示开场白）。
- 测试：新增选题器与最近失手查询测试；更新 `test_proposal` / `test_progress` / `test_ws`；新增“答错 → 新对话 → 开始”验收用例。
- 数据：无迁移；现有 `data/app-v5.db`（schema v6）可直接使用。
- 外部服务：不新增依赖；TTS 只多一段短开场白，失败可降级为纯文本。
- 取代：`docs/designs/learning-unit-v0.1.md` D9「主按钮保持无提议快捷开始」由本次改为“带开场白的快捷开始”。
