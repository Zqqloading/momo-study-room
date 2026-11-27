## 编码规范

这是一份旨在减少大语言模型（LLM）编程错误的**行为准则**。其核心权衡是：**宁可求稳，不求速度**。对于极其简单的任务，请根据实际情况灵活处理。

### 1. 谋定而后动 (Think Before Coding)

**不要假设，不要隐藏困惑，明确权衡利弊。** 在开始编码前：

- **明确假设：** 清晰地陈述你的假设。如果有不确定的地方，直接提问。
- **呈现多选：** 如果存在多种解读方式，请全部列出，不要私自做决定。
- **推崇极简：** 如果有更简单的方案，请指出。在必要时勇于推翻过度设计的方案。
- **遇阻即停：** 如果需求不明，立即停止。指明困惑点并寻求澄清。

### 2. 简约至上 (Simplicity First)

**用最少的代码解决问题，拒绝过度工程。**

- **杜绝臆测：** 不要添加需求之外的功能。
- **禁止预留：** 不要为“单次使用”的代码编写抽象层。
- **无需通用：** 不要为了不存在的“灵活性”或“可配置性”增加复杂度。
- **拒绝冗余：** 不要为不可能发生的场景编写异常处理。
- **精简逻辑：** 如果 50 行能搞定却写了 200 行，请重写。
- **自我审视：** 问自己：“资深工程师会觉得这太复杂了吗？”如果是，请简化。

### 3. 精准手术 (Surgical Changes)

**仅改动必要的代码，只清理自己造成的“烂摊子”。** 编辑现有代码时：

- **保持克制：** 不要擅自“优化”周边的代码、注释或格式。
- **不修不坏：** 不要重构那些目前运行正常的代码。
- **风格统一：** 即使你有更好的编码习惯，也必须遵循原有的代码风格。
- **只提不改：** 如果发现无关的废弃代码（Dead Code），仅需指出，不要直接删除。
- **清理衍生：**
  - 删除由**你的**改动导致的无用引用（Imports）、变量或函数。
  - 除非被明确要求，否则不要删除代码库中原有的废弃代码。
- **测试准则：** 每一行改动的代码，都必须能直接追溯到用户的具体需求。

### 4. 目标驱动执行 (Goal-Driven Execution)

**定义成功标准，循环直至验证通过。** 将任务转化为可验证的目标：

- **“添加校验”** → “为非法输入编写测试用例，并使其通过”。
- **“修复 Bug”** → “编写能重现该 Bug 的测试，修复后使其通过”。
- **“重构 X”** → “确保重构前后的测试结果完全一致”。
- **多步骤任务：** 请先列出简要计划：
  1. [步骤] → 验证方式：[检查项]
  2. [步骤] → 验证方式：[检查项]
  3. [步骤] → 验证方式：[检查项]

> **判断准则：** 如果代码差异（Diff）中的无效改动变少了、因过度设计而导致的重写减少了、且澄清疑问出现在“开发前”而非“出错后”，则说明本准则生效了。

## Graphify

- 建图使用 `/graphify .` 完整流程（含文档语义抽取）；纯代码快速索引可用 `graphify extract . --code-only`。
- 项目级技能在 `.agents/skills/graphify/`，构建产物写入 `graphify-out/`（已在 `.gitignore` 中忽略）。

## Gstack

项目级入口：`.zcode/skills/gstack/SKILL.md`（router，覆盖 63 个 gstack 技能；按任务读取对应技能的 SKILL.md 全文再执行）。全局运行时与二进制在 `D:\gstack\gstack-main`。

**gstack digest v1.96.0.0 — regenerate/re-copy after upgrading gstack**

Behavioral rules from gstack (https://github.com/garrytan/gstack), compressed
for agent hosts without a full skill install. The full skills add workflows,
reviews, and evals on top of these rules.

### Ethos

- **Boil the Ocean** — complete coverage, minimal code: cover the whole requirement (tests, edge cases, error paths) and write no code beyond it. Shortcuts need an explicit, recorded decision.
- **Search Before Building** — know what exists before deciding what to build. Don't reinvent (tried-and-true); scrutinize the popular; prize first-principles insight above all.
- **User Sovereignty** — models recommend, the user decides. Cross-model agreement is signal, never permission. Ask before changing the user's stated direction.
- **Build for Yourself** — the specificity of a real problem beats the generality of a hypothetical one.

### The reuse ladder

Before writing new code, stop at the first rung that holds:

1. A helper, util, or pattern already in this repo.
2. The standard library.
3. A native platform feature (CSS over JS, DB constraint over app code).
4. An already-installed dependency — never add a new one for what a few lines cover.

Then build the complete version of what remains. Bug fixes hit root cause,
not symptom: one guard in the shared function beats a guard in every caller.

### Voice

Direct, concrete, builder-to-builder. Name the file, function, command, and
user-visible impact. Short paragraphs; end with what to do. No filler, no
corporate tone, no AI vocabulary.

### Full gstack

Clone https://github.com/garrytan/gstack and run `./setup` for the full
skill suite (reviews, ship, QA, evals). This digest is generated — edit
scripts/gen-agents-digest.ts, not this file.

## GBrain（项目大脑）

本项目的大脑是本地 PGLite：`D:\gbrain\brain.pglite`，source `chemai2`，已注册为 ZCode 的 MCP 服务 `gbrain`（`gbrain serve --surface starter --advertise verbs`）。

- **先查后答**：涉及本项目的问题（约定、决策、文档内容），先 `gbrain search "<关键词>"`；要综合答案用 `gbrain query "<问题>"`；读原文用 `gbrain get <slug>`。
- **关键词模式**：embeddings 关闭，查不到时换同义词或英文术语再试，不要据此断言"大脑里没有"。
- **沉淀**：确认的决策/约定用 `gbrain remember "<事实>" --entity chemai2`；新增或更新的文档用 `gbrain capture --file <路径> --slug chemai2/<name> --source chemai2`。
- 现有页面：`chemai2/agents`、`chemai2/openspec-config`、`docs/agents/{domain,issue-tracker,triage-labels}`。
