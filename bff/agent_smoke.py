"""真实 agent harness 冒烟：不进入 pytest 默认路径。

用法：
  python -m bff.agent_smoke --probe   # DeepSeek / MiMo 各 1 次工具调用
  python -m bff.agent_smoke --judge   # 10 条判断力样本（真实工具 + 模型）
  python -m bff.agent_smoke           # 两项都跑

会调用真实付费 API；只在用户明确同意后运行。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.agent_loop import AgentLoop
from core.agent_steps import build_free_talk_brief
from core.agent_tools import SEARCH_MATERIALS_SPEC
from core.clock import SystemClock
from core.concepts import load_concepts
from core.db import connect
from core.ports import AgentMessage
from core.store import Store

from .agent_llm import OpenAIAgentClient
from .agent_tools import build_agent_tools
from .config import Endpoint, Settings, load_settings
from .providers.registry import build_providers

PROBE_PROMPT = "先调用工具查一下 Agent Loop 的资料，不要直接回答。"

JUDGE_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": 1,
        "text": "材料里的 Agent Loop 是什么？",
        "expect": "local",
        "why": "概念问题，应先查本地或概念表",
    },
    {
        "id": 2,
        "text": "工具调用和 function calling 有什么区别？",
        "expect": "local",
        "why": "概念区分，应查本地",
    },
    {
        "id": 3,
        "text": "今天 agent 领域有什么最新发布？",
        "expect": "web",
        "why": "时效问题，应查网页",
    },
    {
        "id": 4,
        "text": "联网查一下 2026 年 agent 框架对比",
        "expect": "web",
        "why": "用户显式要求联网",
    },
    {
        "id": 5,
        "text": "不用查资料，直接说说 agent 和 workflow 的区别。",
        "expect": "none",
        "why": "用户明确说不用查",
    },
    {
        "id": 6,
        "text": "你好，今天有点累。",
        "expect": "none",
        "why": "闲聊，不该查",
    },
    {
        "id": 7,
        "text": "解释一下 ReAct 这个说法。",
        "expect": "local",
        "why": "学习问题，应先查本地",
    },
    {
        "id": 8,
        "text": "2026 年 11 月有什么新的 AI 模型发布？",
        "expect": "web",
        "why": "时效问题，应查网页",
    },
    {
        "id": 9,
        "text": "先说结论，不要查：Agent Loop 为什么需要停止条件？",
        "expect": "none",
        "why": "用户明确不要查",
    },
    {
        "id": 10,
        "text": "换个说法再查：智能体循环和 agent loop 是一回事吗？",
        "expect": "local",
        "why": "同义说法，应能换词查本地",
    },
)


def _endpoint(settings: Settings) -> Endpoint:
    return Endpoint(
        label="DeepSeek Agent",
        base_url=settings.agent_base_url or settings.scorer.base_url,
        api_key=settings.agent_api_key or settings.scorer.api_key,
        model=settings.agent_model or settings.scorer.model or "deepseek-chat",
    )


async def _probe_one(label: str, endpoint: Endpoint) -> dict[str, Any]:
    started = time.perf_counter()
    client = OpenAIAgentClient(
        base_url=endpoint.base_url,
        api_key=endpoint.api_key,
        model=endpoint.model,
        timeout=20.0,
        max_retries=0,
    )
    try:
        response = await client.complete(
            [AgentMessage(role="user", content=PROBE_PROMPT)],
            tools=(SEARCH_MATERIALS_SPEC,),
        )
    finally:
        await client.aclose()
    elapsed = int((time.perf_counter() - started) * 1000)
    return {
        "provider": label,
        "model": endpoint.model,
        "latency_ms": elapsed,
        "tool_calls": [
            {"name": call.name, "arguments": call.arguments}
            for call in response.tool_calls
        ],
        "content": response.content[:200],
        "ok": bool(response.tool_calls),
    }


async def _run_probe(settings: Settings) -> list[dict[str, Any]]:
    results = []
    deepseek = _endpoint(settings)
    results.append(await _probe_one("DeepSeek", deepseek))
    mimo = Endpoint(
        label="MiMo Agent",
        base_url=settings.llm.base_url,
        api_key=settings.llm.api_key,
        model=settings.llm.model,
    )
    if mimo.base_url and mimo.api_key:
        results.append(await _probe_one("MiMo", mimo))
    return results


def _judge_ok(case: Mapping[str, Any], result) -> bool:
    expect = case["expect"]
    if result.fallback_reason == "model_error" or not result.content.strip():
        return False
    names = {item.tool for item in result.tool_results}
    if expect == "none":
        return result.tool_calls == 0
    if expect == "web":
        return result.web_calls >= 1
    if expect == "local":
        return (
            bool(names & {"search_materials", "read_concept"})
            and result.web_calls == 0
        )
    return True


async def _run_judge(settings: Settings) -> dict[str, Any]:
    store = Store(connect(settings.db_path))
    concepts = load_concepts(settings.content_dir / "concepts.yaml")
    clock = SystemClock()
    providers = build_providers(settings)
    endpoint = _endpoint(settings)
    client = OpenAIAgentClient(
        base_url=endpoint.base_url,
        api_key=endpoint.api_key,
        model=endpoint.model,
        timeout=20.0,
        max_retries=0,
    )
    loop = AgentLoop(
        client,
        build_agent_tools(
            store=store,
            embedder=providers.embedder,
            search=providers.search,
            concepts=concepts,
            min_cosine=settings.retrieval_min_cosine,
            search_timeout_seconds=settings.search_timeout_seconds,
            today=clock.today,
        ),
    )
    results = []
    try:
        for case in JUDGE_CASES:
            brief = build_free_talk_brief(today=clock.today())
            result = await loop.run(brief, case["text"])
            results.append(
                {
                    "id": case["id"],
                    "text": case["text"],
                    "expect": case["expect"],
                    "why": case["why"],
                    "ok": _judge_ok(case, result),
                    "tool_calls": result.tool_calls,
                    "web_calls": result.web_calls,
                    "tools": [item.tool for item in result.tool_results],
                    "budget_exhausted": result.budget_exhausted,
                    "fallback_reason": result.fallback_reason,
                    "content": result.content[:400],
                    "sources": len(result.sources),
                }
            )
    finally:
        await client.aclose()
        store.close()
        await providers.aclose()
    passed = sum(1 for item in results if item["ok"])
    return {
        "passed": passed,
        "total": len(results),
        "threshold": 8,
        "ok": passed >= 8,
        "cases": results,
    }


def _write_reports(
    out_dir: Path,
    probe: Sequence[dict[str, Any]] | None,
    judge: dict[str, Any] | None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "agent-harness-smoke.json"
    existing: dict[str, Any] = {}
    if json_path.exists():
        try:
            existing = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    probe_items = list(probe) if probe is not None else existing.get("probe", [])
    judge_item = judge if judge is not None else existing.get("judge")
    payload = {"probe": probe_items, "judge": judge_item}
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = ["# Agent Harness 真实冒烟（2026-11-25）", ""]
    if probe_items:
        lines.extend(
            [
                "## 1.8 适配器探针",
                "",
                "| provider | model | latency_ms | tool_calls | ok |",
                "|---|---|---|---|---|",
            ]
        )
        for item in probe_items:
            names = ", ".join(call["name"] for call in item["tool_calls"]) or "—"
            lines.append(
                f"| {item['provider']} | {item['model']} | {item['latency_ms']} | {names} | {item['ok']} |"
            )
        lines.append("")
    if judge_item:
        lines.extend(
            [
                "## 3.8 判断力冒烟",
                "",
                f"通过：{judge_item['passed']}/{judge_item['total']}（门槛 {judge_item['threshold']}）",
                "",
                "| # | 期望 | 实际工具 | web | ok | 输入 |",
                "|---|---|---|---|---|---|",
            ]
        )
        for item in judge_item["cases"]:
            lines.append(
                f"| {item['id']} | {item['expect']} | {', '.join(item['tools']) or '—'} | "
                f"{item['web_calls']} | {item['ok']} | {item['text']} |"
            )
        lines.append("")
        lines.append("工具失败与预算耗尽由 `tests/test_agent_loop.py` 的脚本化用例覆盖；")
        lines.append("本冒烟只验证真实模型在正常工具面下的判断。")
    (out_dir / "agent-harness-smoke.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent harness 真实冒烟")
    parser.add_argument("--probe", action="store_true", help="只跑适配器探针")
    parser.add_argument("--judge", action="store_true", help="只跑判断力冒烟")
    parser.add_argument(
        "--out",
        default="docs/designs/review-20261125",
        help="报告输出目录",
    )
    args = parser.parse_args(argv)
    run_probe = args.probe or not args.judge
    run_judge = args.judge or not args.probe

    settings = load_settings()
    probe_result = asyncio.run(_run_probe(settings)) if run_probe else None
    judge_result = asyncio.run(_run_judge(settings)) if run_judge else None
    _write_reports(Path(args.out), probe_result, judge_result)

    if probe_result is not None:
        print(json.dumps({"probe": probe_result}, ensure_ascii=False, indent=2))
    if judge_result is not None:
        print(
            json.dumps(
                {
                    "judge": {
                        "passed": judge_result["passed"],
                        "total": judge_result["total"],
                        "ok": judge_result["ok"],
                        "cases": judge_result["cases"],
                    }
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
