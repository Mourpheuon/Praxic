"""
自主性控制 —— 根据 AutonomyLevel 精细化控制各阶段的推理行为。
独立自主原则的核心：系统必须有独立判断，不能让外部信息替代自身推理。
"""

from __future__ import annotations
from enum import IntEnum
from typing import Optional


class AutonomyLevel(IntEnum):
    READ_ONLY = 0   # 只输出信息，不做自主判断
    SANDBOXED = 1   # 低自主：以外部信息为主，自主判断为辅
    STANDARD = 2    # 标准自主：外部信息与自主判断并重
    ELEVATED = 3    # 高自主：以自主判断为主，外部信息用于验证


def get_autonomy_instruction(level: AutonomyLevel, phase: str) -> str:
    """根据自主级别和当前阶段，返回注入 system prompt 的行为指令。"""

    base = f"\n## 独立自主原则 (Autonomy Level: {level.name})\n"

    if phase == "investigation":
        instructions = {
            AutonomyLevel.READ_ONLY: (
                base + "你仅需整理和呈现外部搜索结果，不要添加自己的判断。"
            ),
            AutonomyLevel.SANDBOXED: (
                base + "以外部搜索结果为主要依据，但可以在不矛盾的前提下补充少量自主判断。"
            ),
            AutonomyLevel.STANDARD: (
                base
                + "你应该：\n"
                + "1. 先基于自己的知识框架形成独立判断\n"
                + "2. 再用外部搜索结果验证和修正你的判断\n"
                + "3. 在 autonomous_assessment 字段中记录你的独立判断\n"
                + "4. 如果搜索结果的结论与你的独立判断不同，不要简单地让步——分析差异的原因"
            ),
            AutonomyLevel.ELEVATED: (
                base
                + "你应该：\n"
                + "1. 以你的独立判断为主导，搜索结果只是参考素材\n"
                + "2. 如果你的独立判断与搜索结果矛盾，优先信任你的推理\n"
                + "3. 对搜索结果保持批判态度，主动质疑其可信度\n"
                + "4. 在信息不足时，主动提出假设而不是等待更多搜索结果"
            ),
        }
    elif phase == "contradiction":
        instructions = {
            AutonomyLevel.READ_ONLY: (
                base + "基于提供的事实进行矛盾分析，不做额外推测。"
            ),
            AutonomyLevel.SANDBOXED: (
                base + "以事实为依据，可基于逻辑进行有限的延伸分析。"
            ),
            AutonomyLevel.STANDARD: (
                base
                + "基于事实但不受限于事实。如果事实不足以支持完整的矛盾分析，"
                + "可以基于系统知识框架提出假定的矛盾结构并在 autonomous_contradiction_view 中记录。"
            ),
            AutonomyLevel.ELEVATED: (
                base
                + "充分发挥你的辩证思维能力。即使事实不完整，也要敢于提出"
                + "关于矛盾结构的假设。大胆假设，小心求证。"
            ),
        }
    elif phase == "decision":
        instructions = {
            AutonomyLevel.READ_ONLY: (
                base + "产出基于事实的建议列表，不做自主决策。"
            ),
            AutonomyLevel.SANDBOXED: (
                base + "以事实为依据形成建议，并标注每项建议的置信度。"
            ),
            AutonomyLevel.STANDARD: (
                base
                + "在事实基础上形成独立决策。在 autonomous_recommendation 中记录："
                + "如果没有任何外部信息，纯粹基于你的推理，你会做出什么不同的决策？"
            ),
            AutonomyLevel.ELEVATED: (
                base
                + "以你的独立判断为决策核心。外部信息用于验证而非替代你的判断。"
                + "当你的判断与外部信息矛盾时，相信你的推理并解释原因。"
            ),
        }
    else:
        instructions = {
            AutonomyLevel.READ_ONLY: (
                base + "以提供的信息为依据，不做自主拓展。"
            ),
            AutonomyLevel.SANDBOXED: (
                base + "以提供的信息为主要依据，可做有限自主拓展。"
            ),
            AutonomyLevel.STANDARD: (
                base + "在提供信息的基础上，发挥你的独立分析能力。"
            ),
            AutonomyLevel.ELEVATED: (
                base + "充分发挥独立分析能力，提供的信息仅为参考。"
            ),
        }

    return instructions.get(level, base + "标准自主模式。")


def should_skip_external_search(level: AutonomyLevel) -> bool:
    """ELEVATED 级别下，如果系统已有足够的知识，可以跳过外部搜索。"""
    return level >= AutonomyLevel.ELEVATED
