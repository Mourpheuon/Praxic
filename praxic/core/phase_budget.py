"""Praxic —— 阶段执行预算的解析与校验。

供各阶段模块（investigation/contradiction/rational/practice）在应用
反思产出的 phase_budgets 时统一使用，保证默认行为不变与非法值忽略。
"""
from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)

_REASONING_EFFORTS = ("off", "low", "medium", "high")


def validate_reasoning_effort(raw, default: str | None = None):
    """校验 reasoning_effort；非法值返回 default（None 表示不设置、走现状）。"""
    if raw is None or raw == "":
        return default
    s = str(raw).strip().lower()
    if s in _REASONING_EFFORTS:
        return s
    log.warning("phase_budget.invalid_reasoning_effort", value=raw)
    return default


def validate_positive_int(raw, default=None):
    """校验正整数；非法（None/非整数/<=0）返回 default。"""
    if raw is None:
        return default
    try:
        v = int(raw)
    except (TypeError, ValueError):
        log.warning("phase_budget.invalid_int", value=raw)
        return default
    if v <= 0:
        log.warning("phase_budget.non_positive_int", value=raw)
        return default
    return v


def budget_depth(budget: dict | None, default=None) -> "Depth | None":
    """从预算解析 depth 档位；未设置或非法时返回 default（None 表示未指定）。"""
    from .depth import Depth, parse_depth
    budget = budget or {}
    raw = budget.get("depth")
    if raw is None or raw == "":
        return default
    return parse_depth(raw, default=default if default is not None else Depth.STANDARD)


def budget_max_tokens(budget: dict | None, current: int) -> int:
    """应用预算中的 max_tokens；未设置时按 depth 查 DEPTH_CONFIG；都无则保持 current。"""
    budget = budget or {}
    v = validate_positive_int(budget.get("max_tokens"))
    if v is not None:
        return v
    # 预算未显式给 max_tokens 时，使用 depth 档位默认预算
    depth = budget_depth(budget)
    if depth is not None:
        from .depth import DEPTH_CONFIG
        cfg = DEPTH_CONFIG.get(depth)
        if cfg is not None:
            return int(cfg["max_tokens"])
    return current


def budget_reasoning_kwargs(budget: dict | None) -> dict:
    """[DEPRECATED] 从预算的 reasoning_effort 生成传给 llm.call 的推理控制 kwargs。

    reasoning_effort 已标记为 deprecated：深度体系改用纯语义的 depth 档位（见 budget_depth），
    不再依赖 provider 私有推理参数。此函数保留仅为兼容旧的 phase_budgets 字段读取。
    返回 dict，可能为空（未设置或为 medium 时保持现状）。off 映射为 enable_reasoning=False。
    """
    budget = budget or {}
    effort = validate_reasoning_effort(budget.get("reasoning_effort"))
    if effort is None:
        return {}
    if effort == "off":
        return {"enable_reasoning": False}
    if effort == "low":
        return {"reasoning_effort": "low"}
    if effort == "high":
        return {"reasoning_effort": "high"}
    # medium 视为默认，不传，避免对不支持 provider 的降级噪音
    return {}
