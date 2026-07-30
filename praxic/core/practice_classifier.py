"""
Praxic Agent —— 实践模式分类器
在进入实践阶段之前，根据问题本质决定走执行路径还是边界路径。

核心哲学：实践是改造客观世界的物质性活动。
- 执行模式（execution）：代码运行产生可观测结果 → 真实的实践
- 边界模式（boundary）：对于智能体无法实施实践的问题，
  诚实地提供知性分析 + 告诉用户在现实中需要做什么
"""
from __future__ import annotations
from typing import Optional
import structlog

from ..api.schemas.models import DecisionReport, RationalSynthesis

log = structlog.get_logger(__name__)

# 确定性规则：如果 action_item 包含以下词，说明它无法被代码化
_NON_CODE_SIGNALS = [
    "沟通", "讨论", "会议", "访谈", "培训", "说服", "协调",
    "招聘", "面试", "谈判", "撰写文档", "发布公告",
    "建立关系", "培养", "改进文化", "提高意识",
    "制定策略", "确立方向", "设计原则", "建立共识",
    "观察", "跟踪用户", "收集反馈", "调研", "试点",
]

# 问题本身包含以下词，偏向边界模式
_BOUNDARY_QUESTION_SIGNALS = [
    "为什么", "原因", "如何吸引", "如何建立", "如何改善",
    "团队", "社区", "文化", "组织", "管理", "领导",
    "用户为什么", "贡献者", "开发者", "员工", "合作",
    "战略", "方向", "愿景", "价值观",
]

# 问题级别信号：这些问题本质上是信息检索/综合分析，不是代码执行
_ANALYSIS_REPORT_SIGNALS = [
    "架构", "结构", "介绍", "报告", "总结", "概括",
    "体系", "制度", "体制", "流程", "职能", "部门",
    "现状", "概述", "梳理", "整理", "汇总", "盘点",
    "历史", "发展历程", "演变", "政策", "法规",
    "是什么样的", "如何运作", "怎样组成", "包括哪些",
    "关系", "区别", "特点", "特征", "分类",
    "高管", "领导", "负责人", "成员", "人物",
    "地区", "领域", "行业", "分布", "背景",
]

# 决策级别信号：如果 action_items 主要是分析/报告/整理性质
_ANALYSIS_ACTION_SIGNALS = [
    "分析", "整理", "总结", "报告", "撰写", "梳理",
    "归纳", "汇总", "概述", "介绍", "描述", "阐述",
    "说明", "展示", "呈现", "绘制图表", "可视化",
]


def classify_practice_mode(
    question: str,
    decision_report: DecisionReport,
    rational_synthesis: Optional[RationalSynthesis] = None,
) -> str:
    action_descriptions = [a.description for a in decision_report.action_items]

    # 规则0（最高优先级）：问题本质是信息检索/综合分析，不需代码验证
    q_signal_count = sum(1 for sig in _ANALYSIS_REPORT_SIGNALS if sig in question)
    if q_signal_count >= 2:
        log.info("practice_classifier.boundary",
                 reason="question_analysis_report",
                 signal_count=q_signal_count)
        return "boundary"

    # 规则0b：决策中的 action_items 主要是分析/报告性质
    if action_descriptions:
        analysis_count = sum(
            1 for desc in action_descriptions
            if any(sig in desc for sig in _ANALYSIS_ACTION_SIGNALS)
        )
        if analysis_count >= len(action_descriptions) * 0.6:
            log.info("practice_classifier.boundary",
                     reason="mostly_analysis_actions",
                     ratio=f"{analysis_count}/{len(action_descriptions)}")
            return "boundary"

    # 规则1：如果所有 action_item 都可以代码化 → execution
    all_codeable = all(
        not any(sig in desc for sig in _NON_CODE_SIGNALS)
        for desc in action_descriptions
    )
    if all_codeable and action_descriptions:
        log.info("practice_classifier.execution", reason="all_actions_codeable")
        return "execution"

    # 规则2：如果问题本身有社会/组织/战略信号 → boundary
    if any(sig in question for sig in _BOUNDARY_QUESTION_SIGNALS):
        log.info("practice_classifier.boundary", reason="question_social_signal")
        return "boundary"

    # 规则3：如果超过一半的 action_item 不可代码化 → boundary
    non_codeable_count = sum(
        1 for desc in action_descriptions
        if any(sig in desc for sig in _NON_CODE_SIGNALS)
    )
    if action_descriptions and non_codeable_count / len(action_descriptions) > 0.5:
        log.info("practice_classifier.boundary", reason="majority_non_codeable")
        return "boundary"

    # 默认：execution
    log.info("practice_classifier.execution", reason="default")
    return "execution"
