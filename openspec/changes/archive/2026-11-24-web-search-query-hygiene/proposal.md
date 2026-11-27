# Proposal

## Why

2026-11-24 真实 Tavily smoke 暴露：无意义问题「联网查一下 zzqqxxjj9876543210 这个词是什么」返回了 3 条完全无关的「联网搜索」文章，且 `web_status=ok`，前端会照常展示这些链接。

根因有两处：

1. 搜索 query 直接用用户原文，「联网/查一下」这类指令词被发给 Tavily，搜索主题被带偏。
2. 预过滤把 query 的所有中文 2-gram 都当作有效词项，「不存在」「这个」「是什么」等虚词也能让垃圾结果通过「至少共享一个 2 字词项」的检查。

当前该路段只有 fake 测试覆盖，规则在真实数据上不够用；修掉后无意义 query 会落到已有的 `empty` 兜底文案，而不是把无关链接展示给用户。

## What Changes

- 搜索 query 发送给 Tavily 前剥离联网触发词（`联网`、`上网查`、`搜索一下`、`搜一下`、`查一下`），复用 `core/router._WEB_EXPLICIT`；时效词（最新/最近等）保留，并继续追加当前年月。
- 网页结果预过滤提取词项时排除小停用词表（触发词 + 高频虚词），只要求实义词项重叠；query 剥完没有实义词项时视为无可用结果。
- `web_status=empty` 因此能在真实环境触达，走已有的「材料里没有直接讲到，联网也没查到」文案，不改文案本身。

不改变：触发条件、Tavily 参数（`basic`、`max_results=5`、top3）、来源边界、日期标注规则、空/失败文案、是否配置 key 的降级行为。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `web-search`: 「Tavily 搜索与结果预过滤」要求增加 query 触发词剥离与停用词排除；无实义词项时 MUST 视为无网页结果。

## Impact

- 代码：`bff/web_sources.py`（词项提取、预过滤）、`core/router.py`（`search_query`）；`bff/main.py` 不改调用顺序。
- 测试：`tests/test_web_sources.py`、`tests/test_router.py` 新增/调整用例；fake 场景验收保持通过。
- 行为：显式联网问题返回更少无关链接；无意义 query 从「3 条无关链接」变为「联网也没查到」。`reply.sources` 结构不变。
- 依赖与数据：无新增依赖，无 DB 变更，不影响已落库来源。
