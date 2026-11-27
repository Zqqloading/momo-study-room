# Proposal

## Why

学习单元的开场现在只有进度说明，没有 MOMO 自己的日常。先做一个很小的生活素材池：建池、按日期确定性抽一条、一天只变一次、只在单元开场注入一句。它为后续完整设定集留出接口，但本次不实现人设条目、教学纪律、用户记忆或情绪状态。

## What Changes

- **建池**：新增 `persona.yaml` 的 `life_pool`，30 条静态生活素材，一条一句、≤60 字；每条可单独 `enabled`。
- **加载**：新增 `core/persona.py`；`persona.yaml` 缺失时用内置默认池，格式错时启动失败并指出坏节点。
- **抽取**：按 `date.toordinal() % len(enabled)` 确定性取一条；同一天同一条，次日换一条；不使用随机数、不写数据库。
- **注入**：只在学习单元开场拼一句到 `session_ready.intro`；开场 TTS 与事件使用同一份文本；`session_resume` 和自由对话不注入。
- **不做**：人设条目、教学纪律、自由对话注入、用户记忆、情绪状态、Web 面板、SQLite 表、schema 迁移。
- **不改变**：评分、出题、知识检索、题目配比、TTS 参数。

## Capabilities

### New Capabilities

- `persona-life-pool`: 生活素材池的加载、校验、按日抽取和开场句式。

### Modified Capabilities

- `coach-session`: 单元开场白可带一句生活素材；其余会话行为不变。

## Impact

- 代码：新增 `core/persona.py`；`bff/main.py` 启动加载池、`session_start` 计算当日素材、`_send_session_ready` 拼 `intro_prefix`；新增 `persona.yaml`。
- 测试：新增 `tests/test_persona.py`；在 `tests/test_ws.py` 或新文件里覆盖开场注入、同日稳定、次日变化、缺失/损坏文件。
- 数据：无迁移；不新增 SQLite 表；不写会话/题目/分数。
- 外部服务：无新增依赖；开场 TTS 只多一句，TTS 缓存按文本哈希自然区分。
- 设计差异：`persona-settings-v0.1.md` 的 LIFE 注入面是自由对话；本次按用户最新要求改为“只在单元开场”，自由对话注入留到后续。
