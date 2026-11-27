# Tasks

## 1. Query 规范化

- [x] 1.1 把 `core/router.py` 的 `_WEB_EXPLICIT` 改名为公开的 `WEB_TRIGGER_WORDS`，`explicit_web_request` 与 `search_query` 共用；验证：`pytest tests/test_router.py -q` 全绿。
- [x] 1.2 `search_query` 按长度倒序剥离触发词、压缩空白，保留时效词并继续追加年月；剥空返回空串。验证：新增用例覆盖「联网查一下 agent」→「agent」、「联网查一下」→ 空串、「最新的 agent 版本」仍追加年月，`pytest tests/test_router.py -q` 通过。

## 2. 结果预过滤

- [x] 2.1 `bff/web_sources.py` 增加 `WEB_STOPWORDS`（复用 `WEB_TRIGGER_WORDS` + 高频虚词），词项提取前先按长度倒序删除停用词；验证：`tests/test_web_sources.py` 新增「只有虚词重叠」用例通过。
- [x] 2.2 词项集为空时 `filter_web_results` 直接返回 `[]`；验证：新增「无意义 query 返回空列表」用例通过，原有用例（正常保留、去重、top3）保持通过。

## 3. 剥空不搜索

- [x] 3.1 `bff/main.py` 在 `search_query` 结果为空时跳过搜索，设 `web_status="empty"`；验证：新增 ws 用例断言 FakeSearch 调用 0 次，且 reply 含「联网也没查到」。
- [x] 3.2 确认剥空分支不影响搜索失败文案：`web_status="failed"` 仍走「联网搜索暂时不可用」；验证：`pytest tests/test_web_acceptance.py tests/test_ws.py -q` 通过。

## 4. 集成验证

- [x] 4.1 全量测试与 spec 校验：`.venv/Scripts/python -m pytest -q` 0 failed，`openspec validate web-search-query-hygiene --strict` 通过。
- [x] 4.2 真实环境复验（需 `TAVILY_API_KEY`）：重启 8799 后重跑「联网查一下 zzqqxxjj9876543210 这个词是什么」与「联网查一下 qzxvplorb 这个不存在的词条是什么」，确认 `sources` 不含网页来源、文案为「联网也没查到」；把结果追加到 `docs/designs/web-search-smoke-20261124.md` 附录。（2026-11-24 复验：两条 `web_status=empty`、网页来源 0 条；因本地误判 `grounded=true`，兜底文案由模型自行表达，见报告附录）

## Workflow follow-up

- 归档后确认 `openspec/specs/web-search/spec.md` 同步了新的 query 规范化与停用词要求。
- 若 4.2 发现仍有无关键接，回到停用词表补充后再验收，不直接归档。
