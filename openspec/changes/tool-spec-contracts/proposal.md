# Proposal

## Why

现有 `agent-harness` 只定义了 3 个 agent 工具和 3 次/2 次/30 秒预算；实际工具清单已经扩展到 17 个当前工具 + 3 个回合，并确定了 A/P/U 结果分离。需要把这套契约写进 spec，否则“工具能调但结果乱说”“程序工具被 agent 越权”“预算口径不一致”都无法验收。

## What Changes

- 把 `agent-harness` 的工具契约从 3 个只读工具扩展为完整工具目录：3 个 agent 工具、9 个程序工具、3 个用户命令、2 个离线工具；另列 3 个 agent 回合（不是工具）。
- **BREAKING**：每回合预算从 3 次工具 / 2 次网页 / 30 秒改为 8 次 / 4 次 / 60 秒；三个 agent 工具各限 4 次；每次 `tool_call` 计 1 次，失败也计，被预算拦下不计。
- 新增 A/P/U 结果分离：A 回 agent 组织语言，P 直传程序/前端执行，U 页面直显；agent MUST NOT 复述、改写或冒充 P/U 字段。
- 新增 G1–G8 通用禁令：不写库、不改流程、不评分、不泄露答案、不执行网页指令、不绕过程序发事件、不跨会话、不绕过预算。
- 明确程序工具不暴露给 agent；`skip_question` / `repeat_question` / `end_session` 只由用户命令触发；`free_talk` / `teach` / `clarify` 是回合不是工具。
- 明确 `last_scored` 可原样引用，但不得改数、不得说“我给你评分”。
- 4 个选做工具（`read_material` / `read_progress` / `validate_questions` / `capture_hot_item`）本次不做，不进 spec。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-harness`: 工具目录与归属、8/4/60 预算与计数口径、A/P/U 结果分离、G1–G8、程序工具不暴露、`last_scored` 引用边界、硬校验/软判断。
- `web-search`: 每回合 `search_web` 上限从 2 次改为 4 次，与 `agent-harness` 的 8/4/60 预算一致。

## Impact

- 代码：`core/agent_tools.py`（预算常量、工具注册）、`core/agent_loop.py`（8/4/60、单工具 4 次、计数口径）、`bff/agent_tools.py`（结果字段与 A/P/U 标签）、`bff/main.py`（事件路由与结果直传）、`core/agent_steps.py`（`last_scored` 裁剪）、`web/app.js`（来源/状态/分数展示）。
- 测试：`tests/test_agent_tools.py`、`tests/test_agent_loop.py`、`tests/test_agent_ws.py`、`tests/test_agent_steps.py`、`tests/browser/check_agent_harness.mjs`。
- 文档：`docs/designs/tool-specs-v0.1.md`、`docs/designs/VERSIONS.md`。
- 数据：不改 schema，不新增表。
- 回滚：`AGENT_HARNESS=off` 仍回旧路径；预算放宽只在新路径生效。
