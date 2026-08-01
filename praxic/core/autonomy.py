"""
自主性控制 —— 每阶段推理行为约束（与权限判定解耦，独立能力）。

注意：本模块只负责"模型推理时的行为指导"与"调查跳搜策略"，
不参与权限判定。权限由 tools/permissions.py 的 PermissionMode 负责。

- AutonomyLevel：行为自主档位（低自主 → 高自主）
- get_autonomy_instruction：按阶段注入推理行为约束
- should_skip_external_search：调查阶段跳搜策略
"""

from __future__ import annotations
from enum import IntEnum
from typing import Optional


class AutonomyLevel(IntEnum):
    READ_ONLY = 0   # 只输出信息，不做自主判断
    SANDBOXED = 1   # 低自主：以外部信息为主，自主判断为辅
    STANDARD = 2    # 标准自主：外部信息与自主判断并重
    ELEVATED = 3    # 高自主：以自主判断为主，外部信息用于验证


class PermissionMode(IntEnum):
    """四档权限模式（与行为自主 AutonomyLevel 解耦，独立职能）。

    - READ_ONLY    只读：不改变世界，只观察与推理
    - ASK          询问：变更操作先问用户
    - AUTO_REVIEW  自动审核：变更先经系统审核，通过才执行，不通过转询问
    - FULL         完全权限：变更自动放行
    """

    READ_ONLY = 0
    ASK = 1
    AUTO_REVIEW = 2
    FULL = 3


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
    elif phase == "practice":
        instructions = {
            AutonomyLevel.READ_ONLY: (
                base + "仅基于前序事实设计可检验的实践行动，不擅自改变外部世界。"
            ),
            AutonomyLevel.SANDBOXED: (
                base + "以事实和理性认识为依据形成检验方案，并标注每项行动的证据标准。"
            ),
            AutonomyLevel.STANDARD: (
                base
                + "在事实和矛盾结构基础上独立设计实践方案。先提出可证伪论断，"
                + "再选择最小、可回读的工具行动来检验它们。"
            ),
            AutonomyLevel.ELEVATED: (
                base
                + "以你的独立判断设计实践检验。外部信息用于验证而非替代你的判断；"
                + "当工具结果与前序认识矛盾时，保留矛盾并调整下一轮实验。"
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
