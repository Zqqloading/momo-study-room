# Intended vs Implemented Audit — m05-life-pool

Date: 2026-11-26
Method: `intended-vs-implemented` — documented intent vs code evidence, one boundary at a time.
Status: implemented, uncommitted; 544 tests pass.

## Intent sources

- **Latest user instruction**：生活素材池“先建池；按日期确定性从池里抽一条，一天只变一次；只在单元开场注入一句”。
- **Handoff**：`docs/designs/m05-persona-handoff.md` §本次范围、§与既有设计的差异、§审查结论。
- **Spec**：`openspec/changes/m05-life-pool/specs/persona-life-pool/spec.md`、`specs/coach-session/spec.md`。
- **Full persona design**：`docs/designs/persona-settings-v0.1.md` §注入矩阵（`:132`）与 PS-06（`:416`）把 LIFE 放在自由对话 FT-C / AG-F。

## Implementation evidence

- 加载/校验：`core/persona.py:121` `load_persona()`；默认池 `:82`；错误 `PersonaError`。
- 按日抽取：`core/persona.py:68` `LifePool.for_date()`，`date.toordinal() % len(enabled)`。
- 启动加载：`bff/main.py:486` 存在则 `load_persona`，否则 `default_life_pool()`。
- 开场注入：`bff/main.py:636` `intro_prefix=life_pool.for_date(clock.today())`；`bff/main.py:403` `_send_session_ready` 拼 `prefix + started.intro`，事件与 TTS 使用同一个 `intro`。
- 内容：`persona.yaml` 30 条，`life-01`～`life-30`。
- 测试：`tests/test_persona.py` 14 条；`tests/test_ws.py:1219`～`:1256` 覆盖开场、日期、损坏文件、恢复不重播。

## Findings

### A1 — 设计文档与最新指令不一致：LIFE 的注入面

- **Intent**：`persona-settings-v0.1.md:132` 的矩阵把 LIFE 放在 FT-C / AG-F；`:416` PS-06 写“只在自由对话注入”。
- **Implemented**：`bff/main.py:636` 只在 `session_start` 注入；自由对话路径不引用 `life_pool`。
- **分类**：文档过期，不是运行时 bug。最新用户指令（单元开场）和 handoff/spec 覆盖了旧矩阵。
- **建议**：本切片验收后更新 `persona-settings-v0.1.md` 的矩阵与 PS-06，或在文档里标注“小版已改为单元开场，自由对话注入待全量人设”。

### A2 — 有意收窄：`entries` 被接受但不校验、不注入

- **Intent**：完整设定集同时有 `entries` 与 `life_pool`（`persona-settings-v0.1.md` L1/L2）。
- **Implemented**：`core/persona.py:129` 把 `entries` 当已知键；`:133` 只校验它是列表；不解析、不注入。
- **分类**：有意 scope gap，已在 handoff §差异第 2 条记录。不是越权，也不是静默忽略：未知键仍报错。
- **建议**：全量人设落地时在同一加载器上加 `entries` 校验；本次不动。

### A3 — “一条一句”是写作规则，加载器只校验长度

- **Intent**：spec 要求每条一句、≤60 字。
- **Implemented**：`core/persona.py:96` 只校验非空与 ≤60 字；不解析句数。
- **分类**：轻微 doc/code 口径差；30 条默认素材都是一句。spec 已补“一句是写作规则；加载器不解析句数”。
- **建议**：保持作者规则；若要强约束，再加粗粒度句号计数，但会误伤引号内的句号。

### A4 — 同一天编辑池子，当日素材可能变化

- **Intent**：spec 要求“同一池子内容下同一天稳定；一天只变一次”。
- **Implemented**：`for_date()` 是 `日期 + 启用列表` 的纯函数；池子内容不变则稳定，编辑后可能变。
- **分类**：边界行为，已写进 spec 与 handoff §审查结论第 8 条。不是 bug。
- **建议**：若要求“编辑池子也不改变当天选择”，需要把当日选择落库；本次刻意不做。

## No-finding checks

- **缺失文件**：`bff/main.py:486` 回退 `default_life_pool()`；测试用 `CONTENT_DIR=tmp_path` 且无文件，544 条全绿。
- **格式错误**：`load_persona` 抛 `PersonaError`；`test_broken_persona_fails_startup` 覆盖。
- **日期确定性**：同一天稳定、次日不同；`test_for_date_is_stable_and_changes_next_day` 覆盖。
- **启用过滤**：`for_date` 只从 `enabled` 条目取；`test_disabled_items_are_skipped` 覆盖。
- **开场 TTS**：`_send_session_ready` 的 `intro` 同时用于事件和 `_send_intro_audio`；`TTSCache.key` 已含文本，不会复用旧音频。
- **恢复/自由对话**：`session_resume` 不调用 `_send_session_ready`；自由对话不引用 `life_pool`；测试覆盖恢复路径。
- **数据边界**：无新表、无 schema 变更、不写会话/题目/分数/进度；`persona.yaml` 是静态内容，不含用户数据。
- **评分/出题/抽取**：`git diff` 未触碰 `core/scoring.py`、`core/question_generation.py`、`core/extraction.py`；提示词逐字不变。
- **页面**：`session_ready.intro` 的现有展示直接包含生活句；`web/` 无改动。

## Summary

- **Consequential**：A1（设计文档与最新指令不一致，需在验收后更新 persona 设计文档的矩阵）。
- **Intentional scope**：A2（`entries` 本切片不实现）。
- **Documented edge**：A3、A4（写作规则与池子编辑的当日稳定性）。
- **Unenforced-intent / undocumented behavior**：无。
- **Security / privacy / data-boundary findings**：无；本切片不接触用户数据、不新增网络路径、不改权限。
