# 修复记录（Round 3 → 冻结）

评审输入：`round3.md`（19/25 通过，6 项 PARTIAL，4 个新阻塞）
修复日期：2026-11-21

| id | 严重度 | 状态 | 改了什么 |
|---|---|---|---|
| N2-01 | BLOCKING | FIXED | “复习结果”定义为该概念当次 `question_role=review` 的题均值；0 条复习题不改 due；新增 `review_started_at` 作为 14 天循环锚点；同场既复讲又复习时复习结果优先决定 due，日常分数只在没有复习题时用于入队。 |
| N2-02 | BLOCKING | FIXED | 目标节点数只统计 `active` + `known`；`skipped`/`orphaned` 从分母扣除；确认页显示“跳过/已掌握后目标变为 N”；`known` 直接算完成。 |
| N2-03 | BLOCKING | FIXED | 五题配比改为按“早期题（复习 + 误解，最多 2 道）”分配，补 0 早期、1 复习、1 误解、2 复习、1 复习+1 误解五种组合，全部合计 5 行；误解占一个早期名额。 |
| N2-04 | BLOCKING | FIXED | `clean_streak` 只在 `status=active` 时检查，跳过提取/检出会话；提升与重开时清零；candidate 不能直接 resolved。 |
| N-05 | BLOCKING | FIXED | 复习屏条件改为“有到期复习或未解误解触发”。 |
| 次要 1 | MINOR | FIXED | 同上，屏幕 0 条件同步。 |
| 次要 2 | MINOR | FIXED | 阶段标签去掉“第 1-2 周 / 第 2 个月”等与 2-3 小时/周冲突的日历；改为阶段 1-4；三个月覆盖范围改为“d0+v0，3 小时/周时覆盖 v1 下限”。 |
| 次要 3 | MINOR | FIXED | 阶段说明中的周工时改为“按待定区当前占位”，不再硬写数字。 |
| 次要 4 | MINOR | FIXED | 材料删除改为同步时对比 materials 表与文件系统；文件消失记 `prior_status` 并置 `orphaned`，回来恢复；运行时字段列表补 `prior_status`、`review_started_at`。 |
| 次要 5 | MINOR | FIXED | 3 分钟讲解验证改为从日常讲解录音里抽 1 个概念，不需要额外时段。 |
| 次要 6 | MINOR | FIXED | 90 天账改为“72 次完成 − 约 10 次综合场 ≈ 62 次日常；每第 4 次复讲约 15 次，不够 1.5 次/概念时额外日常改为复讲”。 |
| 次要 7 | MINOR | FIXED | 明确 `question_role=new` 指新题不指新概念；复讲场和诊断题也用 `new`。 |
| 次要 8 | MINOR | FIXED | 评分 JSON 增加 `certain` 布尔，支撑“确定检出”与 candidate 区分。 |
| 次要 9 | MINOR | FIXED | `kind=review` 讲解场：`explained_text` 非空记 `status=completed`，`session_score` 为空。 |
| 次要 10 | MINOR | FIXED | v2 阶段补“概念扩到待定区目标节点数”。 |

## 未修 / 明确延后

- R3 的 4 个阻塞与 N-05 已修，但**没有第四轮独立复审**；这是冻结时唯一已知的验证缺口。
- 待定区各项（四个 API 接口、embedding 模型、材料/节点数量、每周工时、口型精度）仍未定。
- Open Questions 的评分校准、短答延迟、讲解转写 60 秒、ASR 80% 仍需实测。
- 这些不是遗漏，是冻结时明确保留的未决项。
