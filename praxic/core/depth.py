"""Praxic —— 推理深度档位的纯语义定义。

背景：Praxic 的"推理控制"曾依赖 provider 私有参数（reasoning_effort / thinking budget /
enable_reasoning），这些参数在 OpenAI / DeepSeek / Claude 上的语义完全分裂且不一定生效。
本模块定义一套**模型无关**的深度体系：

    depth（SHALLOW / STANDARD / DEEP）→ 三要素，全部模型无关：
      1. max_tokens 预算
      2. 推理指令（prompt 文本）
      3. 输出 schema 层级（required / standard_extended / deep_extended）

深度档位由预处理查表决定第一轮，反思阶段通过 phase_budgets 调控后续轮次。
适配层（各家推理私有参数映射）不进入档位定义层——那是 provider 级的事，放各 llm adapter。
"""
from __future__ import annotations

from enum import Enum

import structlog

log = structlog.get_logger(__name__)


class Depth(Enum):
    SHALLOW = "shallow"
    STANDARD = "standard"
    DEEP = "deep"


# 三要素映射（模型无关的纯语义）
DEPTH_CONFIG = {
    Depth.SHALLOW: {
        "max_tokens": 1024,
        "instruction": "直接给出结论，不展示推理过程。",
        "schema_level": "required",
    },
    Depth.STANDARD: {
        "max_tokens": 4096,
        "instruction": "简要推理后给出结论，推理与结论都精炼。",
        "schema_level": "standard_extended",
    },
    Depth.DEEP: {
        "max_tokens": 16384,
        "instruction": "进行完整推理，展示关键推理链、依据和每步原因。",
        "schema_level": "deep_extended",
    },
}

# 各阶段固定（非查表）深度约定
# 第一阶段（step1）固定 SHALLOW；查询生成固定 SHALLOW；结构化规划无需推理链固定 SHALLOW。
_DEPTH_SET = {Depth.SHALLOW, Depth.STANDARD, Depth.DEEP}


def parse_depth(raw, default=Depth.STANDARD) -> Depth:
    """解析深度值；非法值返回 default。"""
    if isinstance(raw, Depth):
        if raw in _DEPTH_SET:
            return raw
        return default
    try:
        parsed = Depth(str(raw).strip().lower())
    except (ValueError, AttributeError):
        log.warning("depth.invalid", value=raw)
        return default
    if parsed in _DEPTH_SET:
        return parsed
    return default


def depth_schema_text(depth: Depth, schema: dict) -> str:
    """按深度注入输出 schema 层。schema 形如
    {"required": {...}, "standard_extended": {...}, "deep_extended": {...}}
    返回当前深度应输出的字段说明拼接文本。SHALLOW 无 standard/deep 层，DEEP 全含。
    """
    depth = parse_depth(depth)
    levels = ["required"]
    if depth in (Depth.STANDARD, Depth.DEEP):
        levels.append("standard_extended")
    if depth == Depth.DEEP:
        levels.append("deep_extended")
    return "\n".join(schema[level] for level in levels if level in schema)


# ═══════════════════════════════════════════════════════════════════
# Phase D1：第一轮初始深度表
#
# 原则：
#   - code_generation / fact_lookup：investigation/contradiction/rational → SHALLOW（或 skip），
#     practice → STANDARD
#   - causal_explanation / exploration_understanding：investigation → STANDARD，
#     contradiction/rational → DEEP，practice → STANDARD
#   - comparison_decision / creative_design：STANDARD 为主
#   - simple 复杂度整体降一档，complex 升一档
#
# 每个 task_nature × complexity → {phase: Depth}。
# 缺少某阶段时默认 STANDARD（cognitive_loop 消费处兜底）。
# ═══════════════════════════════════════════════════════════════════

INITIAL_DEPTH_TABLE: dict[str, dict[str, dict[str, Depth]]] = {
    "code_generation": {
        "simple": {
            "investigation": Depth.SHALLOW,
            "contradiction": Depth.SHALLOW,
            "rational": Depth.SHALLOW,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
        "standard": {
            "investigation": Depth.SHALLOW,
            "contradiction": Depth.SHALLOW,
            "rational": Depth.SHALLOW,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
        "complex": {
            "investigation": Depth.STANDARD,
            "contradiction": Depth.SHALLOW,
            "rational": Depth.SHALLOW,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
    },
    "fact_lookup": {
        "simple": {
            "investigation": Depth.SHALLOW,
            "contradiction": Depth.SHALLOW,
            "rational": Depth.SHALLOW,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
        "standard": {
            "investigation": Depth.SHALLOW,
            "contradiction": Depth.SHALLOW,
            "rational": Depth.SHALLOW,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
        "complex": {
            "investigation": Depth.SHALLOW,
            "contradiction": Depth.SHALLOW,
            "rational": Depth.STANDARD,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
    },
    "causal_explanation": {
        "simple": {
            "investigation": Depth.STANDARD,
            "contradiction": Depth.STANDARD,
            "rational": Depth.STANDARD,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
        "standard": {
            "investigation": Depth.STANDARD,
            "contradiction": Depth.DEEP,
            "rational": Depth.DEEP,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
        "complex": {
            "investigation": Depth.DEEP,
            "contradiction": Depth.DEEP,
            "rational": Depth.DEEP,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
    },
    "comparison_decision": {
        "simple": {
            "investigation": Depth.STANDARD,
            "contradiction": Depth.STANDARD,
            "rational": Depth.STANDARD,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
        "standard": {
            "investigation": Depth.STANDARD,
            "contradiction": Depth.STANDARD,
            "rational": Depth.STANDARD,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
        "complex": {
            "investigation": Depth.STANDARD,
            "contradiction": Depth.DEEP,
            "rational": Depth.STANDARD,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
    },
    "exploration_understanding": {
        "simple": {
            "investigation": Depth.STANDARD,
            "contradiction": Depth.STANDARD,
            "rational": Depth.STANDARD,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
        "standard": {
            "investigation": Depth.STANDARD,
            "contradiction": Depth.DEEP,
            "rational": Depth.DEEP,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
        "complex": {
            "investigation": Depth.DEEP,
            "contradiction": Depth.DEEP,
            "rational": Depth.DEEP,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
    },
    "creative_design": {
        "simple": {
            "investigation": Depth.SHALLOW,
            "contradiction": Depth.STANDARD,
            "rational": Depth.STANDARD,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
        "standard": {
            "investigation": Depth.STANDARD,
            "contradiction": Depth.STANDARD,
            "rational": Depth.STANDARD,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
        "complex": {
            "investigation": Depth.STANDARD,
            "contradiction": Depth.STANDARD,
            "rational": Depth.DEEP,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
    },
    "other": {
        "simple": {
            "investigation": Depth.SHALLOW,
            "contradiction": Depth.SHALLOW,
            "rational": Depth.STANDARD,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
        "standard": {
            "investigation": Depth.STANDARD,
            "contradiction": Depth.STANDARD,
            "rational": Depth.STANDARD,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
        "complex": {
            "investigation": Depth.STANDARD,
            "contradiction": Depth.DEEP,
            "rational": Depth.DEEP,
            "practice": Depth.STANDARD,
            "reflection": Depth.STANDARD,
        },
    },
}


def initial_depth_for(task_nature: str, complexity: str, phase: str) -> Depth:
    """查第一轮初始深度表；缺条目时返回 STANDARD。"""
    nature = task_nature or "other"
    if nature not in INITIAL_DEPTH_TABLE:
        nature = "other"
    comp = complexity or "standard"
    if comp not in INITIAL_DEPTH_TABLE[nature]:
        comp = "standard"
    phase_depth = INITIAL_DEPTH_TABLE[nature][comp].get(phase)
    if phase_depth is None:
        return Depth.STANDARD
    return phase_depth
