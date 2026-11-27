"""v0 领域模型：概念运行时状态、会话记录、会话结算结果。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ports import QuestionScore

# 掌握度标签只用于展示，不参与 mastery 计算，也不写库。
MASTERY_LABELS: dict[int, str] = {
    0: "未掌握",
    1: "初识",
    2: "有印象",
    3: "基本掌握",
    4: "熟练",
    5: "精通",
}


def mastery_label(mastery: int) -> str:
    return MASTERY_LABELS.get(mastery, str(mastery))


@dataclass(frozen=True, slots=True)
class ConceptAssessment:
    """某概念最近一次有评分的作答聚合；用于进度选题与薄弱口径。"""

    concept_id: str
    date: str
    session_id: str
    avg_score: float
    min_score: float
    scored: int


@dataclass(frozen=True, slots=True)
class Focus:
    """本场主概念的展示信息；不写库。"""

    concept_id: str
    name: str
    reason_kind: str


@dataclass(frozen=True, slots=True)
class ProposalPrerequisite:
    id: str
    name: str
    mastery: int
    satisfied: bool


@dataclass(frozen=True, slots=True)
class ProposalConcept:
    id: str
    name: str
    plain_def: str
    difficulty: int
    mastery: int
    mastery_label: str
    last_seen: str | None
    review_due_at: str | None
    overdue_days: int
    last_score: float | None
    prerequisites: tuple[ProposalPrerequisite, ...] = ()
    reason: str = ""
    reason_kind: str = ""


@dataclass(frozen=True, slots=True)
class ProposalSlot:
    slot: int
    question_type: str
    label: str
    role: str
    concept_id: str


@dataclass(frozen=True, slots=True)
class UnitProposal:
    """今日单元提议：只读预览，不落库。"""

    available: bool
    date: str
    reason: str | None = None
    kind: str | None = None
    estimate_minutes: int = 20
    question_count: int = 0
    deferred_reviews: int = 0
    main: ProposalConcept | None = None
    review: ProposalConcept | None = None
    same_concept: bool = False
    slots: tuple[ProposalSlot, ...] = ()


@dataclass(frozen=True, slots=True)
class ConceptUnitResult:
    """一场会话里单个概念的展示摘要；不参与 mastery 计算。"""

    concept_id: str
    name: str
    roles: tuple[str, ...]
    new_score: float | None
    review_score: float | None
    mastery_before: int
    mastery_before_label: str
    mastery_after: int
    mastery_after_label: str
    mastery_updated: bool
    review_due_at: str | None


@dataclass(frozen=True, slots=True)
class ConceptState:
    id: str
    mastery: int = 0
    status: str = "active"
    prior_status: str | None = None
    last_seen: str | None = None
    review_started_at: str | None = None
    review_due_at: str | None = None


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """写入 sessions 表的完整一行。"""

    session_id: str
    date: str
    kind: str  # daily | review
    status: str  # completed | partial | unscored
    started_at: str
    created_at: str
    concept_id: str | None = None
    minutes: int | None = None
    asr_text: str | None = None
    explained_text: str | None = None
    input_mode: str = "voice"
    asr_confidence: float | None = None
    session_score: float | None = None


@dataclass(frozen=True, slots=True)
class SessionResult:
    """会话结算要写入的派生状态。"""

    session_id: str
    status: str
    session_score: float | None
    scores: tuple[QuestionScore, ...] = ()
    mastery_updates: dict[str, int] = field(default_factory=dict)
    concept_id: str | None = None
    review_due_at: str | None = None
    review_started_at: str | None = None
    # 每个概念的 (review_due_at, review_started_at)；同场多道复习题时用它，
    # 优先于上面的单概念字段。值为 (None, None) 表示清空。
    due_updates: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HotItem:
    """未核实热项：可检索、会过期、不进入主知识库。"""

    id: int
    source_kind: str
    text: str
    content_hash: str
    captured_at: str
    last_seen: str
    seen_count: int = 1
    title: str | None = None
    source_url: str | None = None
    expires_at: str | None = None
    status: str = "hot"
    material_id: str | None = None
    verified: bool = False
    age_days: int = 0
