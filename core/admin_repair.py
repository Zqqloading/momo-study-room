"""管理后台的修复计划：只生成命令与前置条件，不执行。

材料、概念、题库三条内容路径；生成题与会话是历史记录，不给“直接改”的计划。
所有路径都显式带 ``--db``：CLI 不读 .env，默认会写 ``data/app.db``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .version import code_version


def _db(path: str | Path) -> str:
    return Path(path).as_posix()


def _backup_db(path: str | Path) -> str:
    db = Path(path)
    backup = db.with_name(
        f"{db.stem}.backup-$(date +%Y%m%d-%H%M%S){db.suffix}"
    )
    return f'cp "{_db(db)}" "{_db(backup)}"'


def _step(
    title: str,
    why: str,
    *,
    command: str | None = None,
    path: str | None = None,
    precondition: str | None = None,
    skip_if: str | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "command": command,
        "path": path,
        "why": why,
        "precondition": precondition,
        "skip_if": skip_if,
    }


def _common_preconditions(db_path: str | Path) -> list[str]:
    return [
        "先停 BFF，或确认没有正在写入；所有命令都在项目根目录执行。",
        f"CLI 不读 .env，每条命令都显式 --db {_db(db_path)}；否则默认写 data/app.db。",
        f"当前代码版本：{code_version() or '未知'}。",
        "reindex 需要 embedding provider；不可用时用 --fts-only，向量检索会降级。",
        "extract 会调 LLM，耗时且可能产生费用；confirm 会交互询问并写 concepts.yaml。",
    ]


def repair_material(
    material: Mapping[str, Any], *, db_path: str | Path
) -> dict[str, Any]:
    mid = str(material["id"])
    path = str(material["path"])
    version = int(material.get("version") or 1)
    db = _db(db_path)
    chunks = f"data/candidates/{mid}.chunks.json"
    candidates = f"data/candidates/{mid}.candidates.json"
    return {
        "type": "material",
        "title": f"修复材料：{material.get('title') or mid}",
        "preconditions": _common_preconditions(db_path),
        "steps": [
            _step(
                "备份数据库",
                "ingest 会 bump 版本并写新块，reindex 会改派生索引；先备份。",
                command=_backup_db(db_path),
                precondition="无；先停 BFF 或确认没有正在写入。",
            ),
            _step(
                "编辑材料文件",
                "材料是内容真相源；改完保存，不要改文件名。",
                path=path,
                precondition="数据库已备份。",
            ),
            _step(
                "重新入库",
                f"同 path 内容变化会 bump 版本：v{version} → v{version + 1}，旧块保留。",
                command=(
                    f'python -m core.ingest "{path}" --db "{db}" '
                    f'--emit-chunks --out "{chunks}"'
                ),
                precondition="材料文件已保存；--db 指向目标库。",
            ),
            _step(
                "重建索引",
                "FTS 与向量只索引当前版本；不跑 reindex，新块不会参与检索。",
                command=f'python -m core.reindex --db "{db}"',
                precondition="ingest 成功；embedding provider 可用（或改 --fts-only）。",
                skip_if="embedding provider 不可用时改 --fts-only，但向量检索会降级。",
            ),
            _step(
                "重新抽取概念",
                "材料改动可能带来新概念或新出处；extract 产 candidates.json。",
                command=(
                    f'python -m core.extract "{chunks}" --db "{db}" '
                    f'--out "{candidates}"'
                ),
                precondition="ingest 已产出 chunks.json。",
                skip_if="只改错别字、措辞或排版，概念集合与出处都不变时跳过。",
            ),
            _step(
                "确认概念",
                "confirm 更新 concepts.yaml 与 concept_sources；检索用的是这里的出处。",
                command=f'python -m core.confirm "{candidates}" --db "{db}"',
                precondition="candidates.json 已生成，且人工确认过候选。",
                skip_if="与上一步相同；跳过时概念与出处保持旧值。",
            ),
            _step(
                "重启 BFF",
                "让 concepts.yaml 与新的运行时状态生效。",
                command="python -m uvicorn bff.main:app --port 8000",
                precondition="concepts.yaml 已确认；没有正在运行的任务。",
                skip_if="如果本地用 --reload，且改动只涉及数据文件，可能已自动生效。",
            ),
        ],
        "notes": [
            "只改材料正文、且概念与出处不变时，可以只跑 ingest + reindex。",
            "concept_sources 不会因为改 YAML 自动更新；它只由 confirm 写。",
            "旧版本块保留但不再被检索；历史会话引用旧块的记录仍可查。",
        ],
    }


def repair_concept(
    concept: Mapping[str, Any],
    *,
    db_path: str | Path,
    content_dir: str | Path,
    sources: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    cid = str(concept["id"])
    yaml_path = Path(content_dir).as_posix() + "/concepts.yaml"
    material_sources: dict[str, str] = {}
    for source in sources:
        material_id = source.get("material_id")
        material_path = source.get("material_path")
        if material_id and material_path:
            material_sources.setdefault(str(material_id), str(material_path))
    steps = [
        _step(
            "备份数据库与 concepts.yaml",
            "改 YAML 进 git，但运行时状态在库里；两边都备份再动。",
            command=(
                f'{_backup_db(db_path)} && '
                f'cp "{yaml_path}" "{yaml_path}.backup-$(date +%Y%m%d-%H%M%S)"'
            ),
            precondition="无；先停 BFF 或确认没有正在写入。",
        ),
        _step(
            "编辑 concepts.yaml",
            f"只改概念 {cid} 的 name/plain_def/aliases/prerequisites/source/difficulty。",
            path=yaml_path,
            precondition="数据库与 concepts.yaml 已备份。",
        ),
        _step(
            "重启 BFF",
            "重载 YAML；sync_runtime 只处理增删与 orphan，不更新已有概念的元数据。",
            command="python -m uvicorn bff.main:app --port 8000",
            precondition="concepts.yaml 已保存。",
        ),
    ]
    for material_id, material_path in sorted(material_sources.items()):
        chunks = f"data/candidates/{material_id}.chunks.json"
        candidates = f"data/candidates/{material_id}.candidates.json"
        steps.append(
            _step(
                f"出处映射变了才重跑材料管线：{material_id}",
                "concept_sources 只由 confirm 更新；YAML 里的 source 不会自动改检索出处。",
                command=(
                    f'python -m core.ingest "{material_path}" --db "{_db(db_path)}" '
                    f'--emit-chunks --out "{chunks}"'
                    f' && python -m core.extract "{chunks}" --db "{_db(db_path)}" '
                    f'--out "{candidates}"'
                    f' && python -m core.confirm "{candidates}" --db "{_db(db_path)}"'
                    f' && python -m core.reindex --db "{_db(db_path)}"'
                ),
                precondition="source 映射已变；材料文件存在；数据库已备份。",
                skip_if="只改定义/名称/前置，不动 source 时跳过；检索仍指向旧块。",
            )
        )
    if not material_sources:
        steps.append(
            _step(
                "出处映射变了才重跑材料管线",
                "concept_sources 只由 confirm 更新；YAML 里的 source 不会自动改检索出处。",
                path="先到材料详情，按材料修复计划执行",
                precondition="source 映射已变；材料文件存在。",
                skip_if="只改定义/名称/前置，不动 source 时跳过；检索仍指向旧块。",
            )
        )
    steps.append(
        _step(
            "核对 concept_sources",
            "确认当前版本的块仍然是主出处；旧块会被标成历史。",
            path="管理后台 → 概念详情 → 出处",
            precondition="BFF 已重启。",
        )
    )
    return {
        "type": "concept",
        "title": f"修复概念：{concept.get('name') or cid}",
        "preconditions": _common_preconditions(db_path),
        "steps": steps,
        "notes": [
            "改 concept id 等于删旧建新：旧概念会 orphaned，mastery 从 0 开始。",
            "改 prerequisites 后重启会校验图；成环或前置不存在会直接报错。",
            "只改 YAML 不会改 concept_sources；检索出处以 confirm 写入的为准。",
        ],
    }


def repair_bank_question(
    question: Mapping[str, Any], *, db_path: str | Path, content_dir: str | Path
) -> dict[str, Any]:
    qid = str(question["id"])
    seeds = Path(content_dir).as_posix() + "/seeds/question_bank.json"
    return {
        "type": "bank_question",
        "title": f"修复题库题：{qid}",
        "preconditions": _common_preconditions(db_path),
        "steps": [
            _step(
                "备份 seeds",
                "题库真相源是 JSON，不在数据库里。",
                command=(
                    f'cp "{seeds}" '
                    f'"{seeds}.backup-$(date +%Y%m%d-%H%M%S)"'
                ),
                precondition="无；先停 BFF 或确认没有正在写入。",
            ),
            _step(
                "编辑题目",
                "按 id 改 question_text/rubric/answer_key/source_url/source_excerpt；id 不要改。",
                path=seeds,
                precondition="seeds 已备份。",
            ),
            _step(
                "重启 BFF",
                "启动时全量镜像导入 seeds：新增、更新、删除都会生效。",
                command="python -m uvicorn bff.main:app --port 8000",
                precondition="seeds 已保存。",
            ),
        ],
        "notes": [
            "历史 session_questions 不受影响；它们保存的是当时的题干与出处。",
            "改 concept_id 前先确认 concepts.yaml 里有该概念。",
            "kind 只能是 recall / discriminate / apply；id 不能重复。",
        ],
    }


def repair_generated_question(question: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "generated_question",
        "title": f"生成题 #{question.get('id')}：历史记录，不可直接改",
        "preconditions": [],
        "steps": [],
        "notes": [
            "生成题在出题时已落库，是会话审计记录；后台不提供改题。",
            "如果题目质量差，改对应材料/概念后，未来场次会重新生成。",
            "如果分数或答案有问题，先查 source_chunk_id 指向的材料段。",
        ],
    }


def repair_session() -> dict[str, Any]:
    return {
        "type": "session",
        "title": "历史会话：不可修改",
        "preconditions": [],
        "steps": [],
        "notes": [
            "会话、答题、评分是审计记录，后台不提供改分或改答案。",
            "要重练同一个概念，从主界面开始新的学习单元。",
        ],
    }
