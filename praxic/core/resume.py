"""Praxic Agent —— 认知循环断点续跑（resume）核心逻辑

设计目标（见 docs/cognitive-loop-resume-design.md）：
  循环被打断（中断/失败/连接断开）后，"继续"应复用已产出的思维过程，
  从断点之后继续，而不完整重跑已完成的部分。

断点真相源（按实时性降级）：
  1. 内存 replay（`_registry[conv_id].replay`，最新、含工具调用序列）
  2. episodic phase_logs（持久化，跨进程/重启可用）
  3. 完整重跑（现状兜底）

断点粒度：
  - phase 级：落在某阶段完成之后的下一阶段
  - tool 级：落在某工具调用成功之后的同阶段下一步（investigation 主场景）

本模块只做"断点定位 + 阶段产物重建"，不触碰各阶段编排；
编排接入见 cognitive_loop.run / stream_run 的 `resume_from` 逻辑。
"""

from __future__ import annotations

import json
from typing import Any, Optional

import structlog

from ..api.schemas.models import (
    PreprocessedQuestion,
    FactReport,
    ContradictionGraph,
    RationalSynthesis,
    PracticeReport,
    ReflectionReport,
)

log = structlog.get_logger(__name__)

# 主循环阶段顺序（与 cognitive_loop 保持一致）
PHASE_NAMES = [
    "preprocessing",
    "investigation",
    "contradiction",
    "rational",
    "practice",
    "reflection",
]

# 阶段名 -> 其在 trace 上对应的字段名（用于重建 CognitiveTrace）
TRACE_FIELD: dict[str, str] = {
    "investigation": "investigation",
    "contradiction": "contradictions",
    "rational": "rational_synthesis",
    "practice": "practice",
    "reflection": "reflection",
}

# 阶段产物 -> pydantic 模型（用于把 dict 反序列化成模型实例）
_PRODUCT_MODEL: dict[str, type] = {
    "preprocessing": PreprocessedQuestion,
    "investigation": FactReport,
    "contradiction": ContradictionGraph,
    "rational": RationalSynthesis,
    "practice": PracticeReport,
    "reflection": ReflectionReport,
}

# 阶段产物需要从 working_mem 侧注入的键（preprocessing 产物 → run 前置注入）
_WORKING_MEM_INJECT: dict[str, list[str]] = {
    "preprocessing": [
        "preprocessed_question", "original_question", "expanded_question",
        "question_intent", "question_domains", "contradiction_in_question",
        "core_anxiety", "questionable_premises", "overlooked_factors",
        "structured_sub_questions",
    ],
}

_PREPROCESS_ATTRS = {
    "preprocessed_question": "preprocessed_question",
    "original_question": "original_question",
    "expanded_question": "expanded_question",
    "question_intent": "question_intent",
    "question_domains": "question_domains",
    "contradiction_in_question": "contradiction_in_question",
    "core_anxiety": "core_anxiety",
    "questionable_premises": "questionable_premises",
    "overlooked_factors": "overlooked_factors",
    "structured_sub_questions": "structured_sub_questions",
}


def parse_resume_from(raw: str) -> Optional[dict]:
    """解析 resume_from 参数的规范形式。

    支持：
      ""                    → None（完整重跑）
      "auto" / "continue"  → {"kind": "auto"}（依据事件自动定位断点）
      "phase:<name>"        → 阶段级续跑
      "tool:<phase>:<tool>" → 工具调用级续跑（investigation 主场景）
      "<tool>:<idx>"        → 兼容简写（investigation 内部，如 "web_search:3"）

    返回 {"kind": "phase"|"tool"|"auto", ...}；
    非法/不可识别输入在调用方回退完整重跑前，先尝试按 auto 处理。
    """
    if not raw:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    if s in ("auto", "continue", "resume", "续跑", "继续"):
        return {"kind": "auto"}
    parts = s.split(":")
    if len(parts) >= 3 and parts[0] == "tool":
        phase, tool = parts[1].strip(), ":".join(parts[2:]).strip()
        return {"kind": "tool", "phase": phase, "tool": tool}
    if len(parts) >= 2 and parts[0] == "phase":
        phase = parts[1].strip()
        if phase in PHASE_NAMES[1:]:
            return {"kind": "phase", "phase": phase}
        return None
    # 其余未知形式不猜成工具，交由自动定位
    return {"kind": "auto"}


def last_successful_event(events: list[dict]) -> Optional[dict]:
    """在事件序列中找最后一个成功完成的事件（续跑起点）。

    遍历 events，跳过纯运行指示事件，找到最后一个"阶段产物已产出"
    （preprocessing/investigation/... 的 phase 事件）或"工具已成功返回"
    （tool_call 事件，status in success/已完成）。返回该事件；无则 None。
    """
    last: Optional[dict] = None
    for ev in events:
        if not isinstance(ev, dict):
            continue
        ev_type = ev.get("event_type") or ev.get("type") or ""
        phase = ev.get("phase") or ""
        data = ev.get("data") or {}
        if ev_type == "tool_call":
            rec = data.get("record") or {}
            result = rec.get("result") or {}
            status = str(result.get("status", "") or rec.get("status", "") or "").lower()
            if status in ("success", "已完成", "done", "completed") or not status:
                last = ev
            continue
        # phase 事件：产物已产出即视为成功完成该阶段
        if phase and ev_type in ("phase", ""):
            last = ev
    return last


def locate_resume_point(events: list[dict]) -> Optional[dict]:
    """依据事件序列定位续跑点。

    返回：
      {"product_phase": "investigation"}        → 已产出的最后阶段，从其后续跑
      {"product_phase": "investigation",
       "tool": "web_fetch"}                     → 最后成功的是 investigation 内工具，
                                                 从该工具之后（同阶段内）续跑
      None                                      → 无可用断点（需完整重跑）
    """
    if not events:
        return None
    last = last_successful_event(events)
    if last is None:
        return None
    ev_type = last.get("event_type") or last.get("type") or ""
    if ev_type == "tool_call":
        rec = last.get("data") or {}
        data = rec.get("record") or rec if isinstance(rec, dict) else {}
        tool = data.get("tool") or ""
        phase = last.get("phase") or "investigation"
        return {"product_phase": phase, "tool": tool}
    phase = last.get("phase") or "preprocessing"
    return {"product_phase": phase}


def _coerce_product(phase: str, data: Any):
    """把某阶段的产物（dict 或已建模实例）归一化为 pydantic 模型。"""
    model = _PRODUCT_MODEL.get(phase)
    if model is None:
        return data
    if isinstance(data, model):
        return data
    try:
        if isinstance(data, dict):
            return model(**data)
        return data
    except Exception as e:
        log.warning("resume.product_coerce_failed", phase=phase, error=str(e))
        return data


def reconstruct_products(events: list[dict]) -> dict[str, Any]:
    """从事件序列重建各阶段产物。返回 {phase: model}。

    events 可以是：
      - replay 原始事件（data 为已建模 pydantic 实例）
      - episodic phase_logs（data 为 JSON dict）
    兼容两种形态。
    """
    products: dict[str, Any] = {}
    for ev in events:
        if not isinstance(ev, dict):
            continue
        ev_type = ev.get("event_type") or ev.get("type") or ""
        phase = ev.get("phase") or ""
        if ev_type == "tool_call":
            continue
        if phase not in _PRODUCT_MODEL:
            continue
        data = ev.get("data")
        if data is None:
            continue
        # phase_logs 形态：data 可能在 value 下包裹
        if isinstance(data, dict) and "event_type" in data and "value" in data and data.get("value") is not None:
            data = data.get("value")
        prod = _coerce_product(phase, data)
        if prod is not None and not _is_empty_product(phase, prod):
            products[phase] = prod
    return products


def _is_empty_product(phase: str, prod: Any) -> bool:
    """判断某阶段产物是否为空（无有效内容，不用于重建）。"""
    if prod is None:
        return True
    # pydantic 模型则按关键字段判断
    if isinstance(prod, PreprocessedQuestion):
        return not prod.original_question and not prod.expanded_question
    if isinstance(prod, FactReport):
        return not prod.facts and not prod.summary
    if isinstance(prod, ContradictionGraph):
        return not prod.principal_contradiction and not prod.secondary_contradictions
    if isinstance(prod, RationalSynthesis):
        return not prod.essence and not prod.synthesis_text
    if isinstance(prod, PracticeReport):
        return not prod.steps_taken and not prod.practice_summary
    if isinstance(prod, ReflectionReport):
        return not prod.quality_assessment
    return False


def preprocess_keys_from_product(prod: Any) -> dict:
    """从 preprocessing 产物提取 run() 早期需要注入 working_mem 的键值。"""
    opts = [
        "preprocessed_question", "original_question", "expanded_question",
        "question_intent", "question_domains", "contradiction_in_question",
        "core_anxiety", "questionable_premises", "overlooked_factors",
        "structured_sub_questions", "wants_detailed_report", "task_nature",
        "task_complexity",
    ]
    out: dict = {}
    for attr in opts:
        try:
            val = getattr(prod, attr, None)
        except Exception:
            val = None
        out[attr] = val
    out["preprocessed_question"] = prod
    return out


def phases_before(target_phase: str) -> list[str]:
    """返回 target_phase 之前的全部阶段名（含 preprocessing 前置）。"""
    try:
        idx = PHASE_NAMES.index(target_phase)
    except ValueError:
        return []
    return PHASE_NAMES[:idx]
