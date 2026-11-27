# Tasks

## 1. 生活素材池

- [x] 1.1 新增根目录 `persona.yaml`：`version: 1` + `life_pool.enabled: true` + 30 条素材（`id`、`text`、`enabled`）；每条一句、≤60 字；验证 `python -c` 或加载测试可读出 30 条
- [x] 1.2 新增 `core/persona.py`：`LifeItem` / `LifePool` / `PersonaError` / `DEFAULT_LIFE_TEXTS` / `default_life_pool()` / `load_persona(path)` / `LifePool.for_date(day)`；缺失文件由 BFF 回退默认池，格式错抛 `PersonaError`；验证 `tests/test_persona.py`
- [x] 1.3 `bff/main.py` 启动加载：`content_dir / "persona.yaml"` 存在则 `load_persona`，否则 `default_life_pool()`；存 `app.state.life_pool`；验证缺失/损坏两种启动路径
- [x] 1.4 `bff/main.py` 开场注入：`session_start` 用 `clock.today()` 取当日素材；`_send_session_ready` 增加 `intro_prefix`；事件 `intro` 与 `_send_intro_audio` 使用同一份拼接文本；`session_resume` / 自由对话不注入；验证 `tests/test_ws.py`

## 2. 测试

- [x] 2.1 加载器：合法 30 条、缺失文件默认池、`version` 错、`text` >60、`id` 重复、未知顶层键、`entries` 缺省为空、单条 `enabled: false`
- [x] 2.2 抽取：同一天稳定、次日不同、只从启用条目抽、池子关闭/空池返回 None、非法日期返回 None
- [x] 2.3 开场：`session_ready.intro` 以当日素材开头并后接原 `intro`；TTS 调用文本与事件一致；`session_resume` 无生活句；无素材时 `intro` 不变
- [x] 2.4 隔离：自由对话提示词不含生活素材；评分/出题/抽取提示词逐字不变；`persona.yaml` 不含人设/纪律/记忆/情绪字段

## 3. 回归

- [x] 3.1 跑 `python -m pytest -q` 全量通过；544 passed
- [x] 3.2 若前端 `web/` 无改动，确认 `session_ready.intro` 现有展示直接可见；不做页面改动

## 4. 审计与导出

- [x] 4.1 按 `intended-vs-implemented` 方法审计：逐条对照 `persona-settings-v0.1.md`、`user-memory-v0.1.md`、`emotion-state-v0.1.md` 与本次 spec，记录差异、遗漏和理由
- [x] 4.2 导出本对话用户提示词到 `docs/designs/m05-user-prompts.md`，只保留提示词，不做分析
- [x] 4.3 不提交；等用户确认后再按用户指定的提交信息提交

## Workflow follow-up

- 评审通过后运行 `openspec archive m05-life-pool`，同步 `persona-life-pool` / `coach-session` main specs。
- 后续全量人设落地时，把自由对话注入加回 `persona-settings-v0.1.md` 的注入矩阵。
