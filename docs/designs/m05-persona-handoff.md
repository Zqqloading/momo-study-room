# Handoff: M05 生活素材池（小版）

Date: 2026-11-26
Branch: feature-mood
Status: IMPLEMENTED (uncommitted, 544 tests green)
Source designs: `persona-settings-v0.1.md`（DRAFT）、`user-memory-v0.1.md`（已认可）、`emotion-state-v0.1.md`（DRAFT）

## 背景

完整设定集、用户记忆、情绪状态三份设计都已经成形，但都还没落地。现在先切一个最小、可独立验收的切片：生活素材池。

用户本次的原话是：

> 生活素材池先做一个很小的版本：先建池；按日期确定性从池里抽一条，一天只变一次；只在单元开场注入一句。

## 本次范围

- 建池：30 条静态生活素材，一条一句，≤60 字。
- 存储：`persona.yaml` 的 `life_pool`；文件缺失用内置默认池；文件格式错则启动失败。
- 抽取：按日期确定性，`date.toordinal() % len(enabled)`；同一天同一条，次日换一条；只从 `enabled: true` 的条目里抽。
- 注入：只在学习单元开场注入一句；拼进 `session_ready.intro`，事件和开场 TTS 使用同一份文本。
- 不做：人设条目、教学纪律、自由对话注入、用户记忆、情绪状态、Web 面板、SQLite 表、schema 迁移。

## 与既有设计的差异

1. **注入面**：`persona-settings-v0.1.md` 的注入矩阵把 LIFE 放在自由对话（FT-C / AG-F）；本次用户明确改为“只在单元开场注入一句”。以本次为准；自由对话注入留到后续。
2. **`persona.yaml` 范围**：全量设计包含 `entries`；本小版只读 `life_pool`，`entries` 缺省为空、不校验、不注入。
3. **开场拼接**：记忆设计也计划在单元开场前拼记忆块；本次先加一个通用 `intro_prefix`，后续可在同一位置叠加记忆块。
4. **不碰评分/出题/抽取**：这三处提示词逐字不变。

## 审查结论（2026-11-26）

审查了 `persona-settings-v0.1.md`、`user-memory-v0.1.md`、`emotion-state-v0.1.md` 与本次 spec/tasks，发现：

1. **注入面冲突**：人设设计把 LIFE 放在自由对话；本次用户要求“只在单元开场注入一句”。按最新要求执行，spec 只写单元开场，自由对话注入留到后续。已在差异第 1 条记录。
2. **`persona.yaml` 范围收窄**：全量设计同时有 `entries` 与 `life_pool`；本次只读 `life_pool`。加载器把 `entries` 当已知键保留但不校验、不注入，避免以后加条目时还要改解析器。
3. **开场拼接接口**：记忆设计也计划在单元开场前拼记忆块；本次用通用 `intro_prefix`，后续记忆块可复用同一位置，不新造第二套拼接。
4. **缺失文件兜底**：测试用 `CONTENT_DIR=tmp_path`，没有 `persona.yaml`；所以 BFF 必须在缺失时回退内置 30 条，否则现有 WS 测试会全部启动失败。
5. **TTS 缓存**：`TTSCache.key` 已把文本纳入哈希；每天生活句不同会自动生成新缓存，不需要改 TTS 缓存。
6. **恢复路径**：`session_resume` 不发 `intro`；本次不注入，符合“单元开场”而不是“每次恢复都念一句”。
7. **自由对话**：本次不注入；spec 明确写“不加”，防止实现时顺手塞进 `build_free_talk_messages`。
8. **同一天编辑池子**：抽取是日期 + 启用列表的纯函数；如果用户当天改池子，当日素材可能变。这是“确定性抽取”的直接结果，不额外存每日选择。
9. **无数据库变更**：不新增表、不改 schema；`persona.yaml` 是内容真相源，和 `concepts.yaml` 同型。
10. **默认池与 YAML 重复**：`DEFAULT_LIFE_POOL` 与 `persona.yaml` 初始内容相同；YAML 是可编辑覆盖，内置池是缺失兜底。测试用临时文件/默认池，不断言根目录文件内容。

## 任务拆分

- 新能力 spec：`openspec/changes/m05-life-pool/specs/persona-life-pool/spec.md`
- 会话开场 spec delta：`openspec/changes/m05-life-pool/specs/coach-session/spec.md`
- 任务清单：`openspec/changes/m05-life-pool/tasks.md`
- 变更提案：`openspec/changes/m05-life-pool/proposal.md`

## 验收

- 同一天多次开始单元，开场生活句相同；次日不同。
- 关闭某条素材后，它不再被抽到；全部关闭时不注入。
- `persona.yaml` 缺失时用内置 30 条；格式错时启动失败并指出坏节点。
- `session_ready.intro` 与开场 TTS 文本一致；`session_resume` 不重复注入；自由对话不注入。
- `persona.yaml` 不出现人设条目、纪律、记忆、情绪字段；评分/出题/抽取提示词不变。
- 全量测试通过；不提交，等用户确认。
