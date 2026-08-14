"""
Praxic Agent —— 问题预处理模块（v0.2.0 五步管线）
核心原则：调查之前先理解问题本身。
五步逻辑保留，Step 1 后合并执行 Step 3/4/5；合并失败时自动退回分步管线。
正常路径只需 2 次 LLM 调用，避免过度分析。
"""
from __future__ import annotations

import asyncio
import json

import structlog

from ..api.schemas.models import PreprocessedQuestion
from ..config import PhaseConfig
from ..llm import get_llm as _get_default_llm
from .depth import Depth

log = structlog.get_logger(__name__)


def _depth_for_complexity(complexity: str) -> Depth:
    """预处理 step345 按任务复杂度映射初始深度档位。
    simple→SHALLOW，standard→STANDARD，complex→DEEP。"""
    c = (complexity or "standard").strip().lower()
    return {"simple": Depth.SHALLOW, "complex": Depth.DEEP}.get(c, Depth.STANDARD)

# ═══════════════════════════════════════════════════════════════════
# Step prompt 常量——每步一个短 prompt，聚焦单一任务
# ═══════════════════════════════════════════════════════════════════

_STEP1_TASK_NATURE_PROMPT = """判断以下用户问题的任务性质与复杂度。

## 任务性质分类

- code_generation：需要生成可运行代码、脚本、查询、配置文件。需求明确、有正确答案、可通过执行验证。典型："用 Python 求质数和""写一个 SQL JOIN 查询""帮我写个 shell 脚本"。
- fact_lookup：查询确定的事实、数据、日期、定义、状态。有公认的正确答案，可通过搜索确证。典型："Python 3.12 什么时候发布的""某公司 CEO 是谁""以太坊 gas 费现在多少"。
- causal_explanation：理解某事物为何发生、原因和结果之间的机制。需要调查事实、分析因果关系。典型："为什么开源项目难以吸引贡献者""某政策效果不及预期的原因"。
- comparison_decision：在多个选项中做选择，或对比不同方案的优劣。需要厘清标准、收集信息、权衡利弊。典型："微服务 vs 单体架构""我该不该换工作"。
- exploration_understanding：深入理解一个概念、现象、体系。需要多角度调查、识别本质、提炼规律。典型："什么是涌现""区块链共识机制的演化"。
- creative_design：产出新的设计、方案、计划、内容。需要理解约束、探索可能、迭代优化。典型："设计一个数据模型""写一份项目计划"。
- other：以上分类都不贴切，或跨多个类别难以归入单一类别。

输出 JSON：{"task_nature": "分类", "complexity": "simple|standard|complex", "needs_investigation": true|false, "reasoning": "一句话依据"}
只输出 JSON。
其中 needs_investigation：这个问题 LLM 能否仅凭自身知识直接准确回答？若不需搜索/查文件/跑代码/外部信息即可给出高质量答案，则为 false。寒暄和极简常识必为 false。

## 经验

- 大多数编程问题是 code_generation + simple。
- "你好""谢谢"等寒暄 needs_investigation=false。
- 不确定任务性质就选 other；不确定复杂度就选 standard。
- 不确定是否需要调查就选 true。"""


# ── Step 2：阶段必要性查表（确定性映射，无 LLM 调用，仅代表首次循环的强度）──

PHASE_NECESSITY_TABLE = {
    "code_generation": {
        "investigation": "light",    "contradiction": "skip",
        "rational": "skip",          "practice": "required",
        "reflection": "required",
    },
    "fact_lookup": {
        "investigation": "required", "contradiction": "required",
        "rational": "required",      "practice": "skip",
        "reflection": "required",
    },
    "causal_explanation": {
        "investigation": "required", "contradiction": "required",
        "rational": "required",      "practice": "required",
        "reflection": "required",
    },
    "comparison_decision": {
        "investigation": "required", "contradiction": "required",
        "rational": "required",      "practice": "light",
        "reflection": "required",
    },
    "exploration_understanding": {
        "investigation": "required", "contradiction": "required",
        "rational": "required",      "practice": "required",
        "reflection": "required",
    },
    "creative_design": {
        "investigation": "light",    "contradiction": "required",
        "rational": "required",      "practice": "required",
        "reflection": "required",
    },
    "other": {
        "investigation": "required", "contradiction": "required",
        "rational": "required",      "practice": "light",
        "reflection": "required",
    },
}


def _downgrade(level: str) -> str:
    """required → light, light → skip, skip → skip"""
    return "light" if level == "required" else "skip"


def _upgrade(level: str) -> str:
    """skip → light, light → required, required → required"""
    return "required" if level in ("light", "skip") else "required"


_STEP3_CONTRADICTION_IN_INTENT_PROMPT = """分析用户提问行为本身可能蕴含的矛盾。

## 注意：与正式矛盾分析阶段的区别

你分析的是**用户提问意图**中的矛盾——ta 说想要什么，和 ta 真正需要或担心的，之间有没有结构性差距。不要分析用户问题中的主题内容（那是后面矛盾分析阶段的工作）。例如：用户问"微服务 vs 单体怎么选"——预处理的矛盾不是微服务和单体之间的技术对立，而是用户问题背后的核心需求等方面与遇到的困难等之间的关系。

## 什么是矛盾

在辩证唯物主义中，矛盾指事物内部两个互相依赖、互相排斥的对立面之间的对立统一关系：
- 有两个明确的方面互相作用于同一事物
- 它们彼此依赖——每一方都因为对方的存在才有意义（例如"资本和劳动"：没有资本雇佣就没有雇佣劳动，没有劳动就没有资本增殖）
- 它们彼此排斥——每一方都试图克服或改变对方
- 它们的斗争推动事物发展和转化

## 提问行为中常见的矛盾形式

- "想要确定答案"和"问题本质蕴含不确定性"之间的矛盾
- "期望别人替ta决策"和"只有ta自己掌握全部情境"之间的矛盾
- "要深入理解"和"希望简单快速回答"之间的矛盾
- "想解决 X"但"把问题归因于 Y 而忽略了真正的根源 Z"之间的矛盾
- "期望通用最优方案"但"面临高度特化的约束条件"之间的矛盾

## 经验

- 如果用户的问题直接、明确、表面需求和深层需求一致——输出空字符串。不要硬造矛盾。
- 对简单代码生成、简单事实查询，几乎一定没有意图矛盾。
- 对真正的矛盾，写清对立的两极和它们之间的关系，100-200 字。

输出 JSON：{"contradiction_in_question": "矛盾描述或空字符串"}
只输出 JSON。"""


_STEP4_PREMISE_AUDIT_PROMPT = """审查用户问题中隐含的预设和框架。

## 预设审查

用户的问题几乎总是建立在一些被默认为真的前提上。逐一检查：
- 问题表述中把什么当成了既定事实？
- 有没有把个例当规律、把流行叙事当信史、把相关性当因果？
- 有没有以偏概全或幸存者偏差？

对每个可疑预设，用统一格式："预设：<主张> —— 存疑：<原因> —— 核实：<方向>"

## 框架审视

用户提问时圈定的对象和范围，是否遗漏了真正重要的主要矛盾？
- 用户把问题框成"A vs B"时，是否漏掉了 C 这个第三方？
- 用户聚焦在"怎么做"时，是否忽略了"为什么要做"这个前提？
- 用户的框架是否受到流行话语或思维惯性的局限？

## 规则

- 如果经审查确实无可疑预设且框架够用，对应数组留空——但必须是真正审查过之后再下此判断。
- 不确定的预设标注为"待核实"，不要替调查阶段下结论。

输出 JSON：
{
  "questionable_premises": ["预设：<主张> —— 存疑：<原因> —— 核实：<方向>"],
  "overlooked_factors": ["被忽略的力量/因素（附为何相关）"]
}
两个数组都可以为空。
只输出 JSON。"""


# Step 4 仅在以下任务性质下执行——纯代码生成/事实查询通常不含事实主张
_STEP4_SKIP_TASK_TYPES = {"code_generation", "fact_lookup"}


_STEP5_STRUCTURE_PROMPT = """基于已经完成的任务性质判断、意图矛盾分析和预设审查，对用户问题进行结构化扩展。

## 任务

### 意图揣度
用户表面上问的是什么，本质上想知道的可能是什么？
分类：因果解释 / 行动方案 / 判断验证 / 探索理解 / 其他 + 一句判断依据

### 深层关切
用户说出口的焦虑和没说出口的关切。不臆测，基于问题本身推断，50-150 字。

### 领域关联
列出 3-4 个与问题直接相关的知识领域或维度。

### 结构化子问题
拆分为 2-4 个具体子问题。
- 如果存在可疑预设，至少有一个子问题指向"该预设是否成立"
- 如果存在被忽略因素，至少有一个子问题纳入它们
- 对简单任务，子问题可以只有 1-2 个

### 扩展问题
将原始问题重写为完整、清晰、可操作的结构化表述。
- 补充缺失的限定条件（时间、空间、范围）
- 可疑预设降格为"待核实的论断"，不写成事实
- 复杂问题 200-400 字，简单问题 50-150 字

### 是否必须先问用户
有没有只有用户本人才能提供、缺了就没法回答的信息？
- 对代码生成/事实查询，几乎一定不需要反问
- 对复杂决策或设计，如果关键约束缺失，可以问最多 1-3 条
- 绝不把能通过搜索查到的东西列为反问

### 是否需要详实报告
- 仅当用户明确要求"详细/深入/完整报告"时才设为 true；否则为 false

输出 JSON：
{
  "question_intent": "行动方案 —— 用户要的是具体可行的 Python 代码实现",
  "core_anxiety": "深层关切 50-150 字",
  "question_domains": ["领域1", "领域2", "领域3"],
  "structured_sub_questions": ["子问题1", "子问题2"],
  "expanded_question": "扩展后的问题文本",
  "clarifying_questions": [],
  "wants_detailed_report": false
}
只输出 JSON。"""


_STEP345_COMBINED_PROMPT = """一次完成用户问题的意图矛盾分析、预设审查和结构化扩展。

用户消息会给出任务性质、复杂度，以及“执行意图矛盾分析”“执行预设审查”两个开关。开关为 false 时，对应字段必须输出空字符串或空数组，不要强行分析。

## 意图矛盾分析

只分析用户提问行为本身：表面想要的答案与真正需要、担心或掌握的信息之间，是否存在互相依赖又互相牵制的结构性差距。不要分析问题主题内部的技术对立。问题直接明确时留空；真正存在时写清对立两极及其关系，100-200 字。

## 预设审查与框架审视

检查问题把哪些论断当成既定事实，是否存在以偏概全、把相关性当因果、把流行叙事当事实等情况。每条可疑预设使用“预设：<主张> —— 存疑：<原因> —— 核实：<方向>”格式。不确定时标注待核实。再检查用户框架是否遗漏了重要的第三方、约束或更基础的问题。确实没有时数组留空。

## 结构化扩展

- question_intent：分类为因果解释 / 行动方案 / 判断验证 / 探索理解 / 其他，并附一句依据。
- core_anxiety：基于问题本身推断深层关切，50-150 字，不臆测。
- question_domains：列出 3-4 个直接相关的知识领域或维度。
- structured_sub_questions：拆为 2-4 个具体子问题；存在可疑预设或遗漏因素时必须覆盖它们。简单任务可为 1-2 个。
- expanded_question：补充必要限定，将可疑预设降格为待核实论断。复杂问题 200-400 字，简单问题 50-150 字。
- clarifying_questions：只有用户本人能提供且缺少后无法回答的信息，最多 1-3 条；能搜索或验证的信息不要反问。
- wants_detailed_report：仅当用户明确要求详细、深入或完整报告时为 true。

输出 JSON，字段必须完整：
{
  "contradiction_in_question": "矛盾描述或空字符串",
  "questionable_premises": [],
  "overlooked_factors": [],
  "question_intent": "分类 —— 一句依据",
  "core_anxiety": "深层关切",
  "question_domains": [],
  "structured_sub_questions": [],
  "expanded_question": "扩展后的问题",
  "clarifying_questions": [],
  "wants_detailed_report": false
}
只输出 JSON。"""


class QuestionPreprocessing:
    """问题预处理模块 —— 调查之前先理解问题

    五步逻辑管线：任务性质→阶段必要性→意图矛盾→预设审查→结构化扩展。
    正常路径合并后三步，失败时回退到 Step 3/4 并行的分步实现。
    """

    def __init__(self, llm=None, phase_config=None):
        self.llm = llm or _get_default_llm()
        self.config = phase_config or PhaseConfig()

    # ═══════════════════════════════════════════════════════════════
    # 公共入口
    # ═══════════════════════════════════════════════════════════════

    async def preprocess(self, question: str, conversation_history: str = "",
                         current_datetime: str = "") -> PreprocessedQuestion:
        log.info("question_preprocessing.start", question=question[:100])

        # 当前时间作为前缀注入——让 Step1 知道"今天几号""现在几点"可直接回答，
        # 不必判为需要调查。current_datetime 非空时并入对话历史上下文。
        _ctx_prefix = conversation_history
        if current_datetime:
            _dt_line = f"[当前时间：{current_datetime}]"
            _ctx_prefix = (_dt_line + "\n" + conversation_history) if conversation_history else _dt_line

        # ── Step 1：任务性质 + 复杂度 + needs_investigation ──
        # 由 LLM 判断是否需要调查——寒暄、简单常识、简单计算等均应由此截获，
        # 交给回答阶段直接处理，不硬编码任何输入类型。
        step1 = await self._step_task_nature(question, _ctx_prefix)
        task_nature = step1.get("task_nature", "other")
        complexity = step1.get("complexity", "standard")

        # ── Step 2：阶段必要性（确定性查表 + 复杂度微调）──
        necessity = dict(PHASE_NECESSITY_TABLE.get(
            task_nature, PHASE_NECESSITY_TABLE["other"]
        ))
        if complexity == "simple":
            necessity = {k: _downgrade(v) for k, v in necessity.items()}
        elif complexity == "complex":
            necessity = {k: _upgrade(v) for k, v in necessity.items()}

        # ── No investigation needed → skip everything, answer directly ──
        if not step1.get("needs_investigation", True):
            necessity = {k: "skip" for k in necessity}
            complexity = "simple"

        # ── Step 3/4：计算执行开关；合并失败时两者可并行执行 ──
        do_step3 = complexity != "simple"
        do_step4 = not (
            task_nature in _STEP4_SKIP_TASK_TYPES and complexity == "simple"
        )

        combined = await self._step_analysis_and_structure(
            question,
            task_nature,
            complexity,
            do_step3,
            do_step4,
            _ctx_prefix,
        )
        if combined is not None:
            contradiction_in_question = (
                combined.get("contradiction_in_question", "") if do_step3 else ""
            )
            questionable_premises = (
                combined.get("questionable_premises", []) or [] if do_step4 else []
            )
            overlooked_factors = (
                combined.get("overlooked_factors", []) or [] if do_step4 else []
            )
            step5 = combined
        else:
            # 合并调用失败时降级到 B1：Step 3/4 并行，随后执行 Step 5。
            if do_step3 and do_step4:
                step3_task = asyncio.create_task(
                    self._step_contradiction_in_intent(
                        question, task_nature, _ctx_prefix
                    )
                )
                step4_task = asyncio.create_task(
                    self._step_premise_audit(question, task_nature, _ctx_prefix)
                )
                step3, step4 = await asyncio.gather(step3_task, step4_task)
            elif do_step3:
                step3 = await self._step_contradiction_in_intent(
                    question, task_nature, _ctx_prefix
                )
                step4 = {"questionable_premises": [], "overlooked_factors": []}
            elif do_step4:
                step3 = {"contradiction_in_question": ""}
                step4 = await self._step_premise_audit(
                    question, task_nature, _ctx_prefix
                )
            else:
                step3 = {"contradiction_in_question": ""}
                step4 = {"questionable_premises": [], "overlooked_factors": []}

            contradiction_in_question = step3.get("contradiction_in_question", "")
            questionable_premises = step4.get("questionable_premises", []) or []
            overlooked_factors = step4.get("overlooked_factors", []) or []
            step5 = await self._step_structure(
                question,
                task_nature,
                complexity,
                contradiction_in_question,
                questionable_premises,
                overlooked_factors,
                _ctx_prefix,
            )

        result = PreprocessedQuestion(
            original_question=question,
            expanded_question=step5.get("expanded_question", question),
            question_intent=step5.get("question_intent", ""),
            question_domains=step5.get("question_domains", []),
            contradiction_in_question=contradiction_in_question,
            core_anxiety=step5.get("core_anxiety", ""),
            questionable_premises=questionable_premises,
            overlooked_factors=overlooked_factors,
            wants_detailed_report=bool(step5.get("wants_detailed_report", False)),
            structured_sub_questions=step5.get("structured_sub_questions", []),
            clarifying_questions=step5.get("clarifying_questions", []),
            task_nature=task_nature,
            task_complexity=complexity,
            needs_investigation=step1.get("needs_investigation", True),
            investigation_necessity=necessity["investigation"],
            contradiction_necessity=necessity["contradiction"],
            rational_necessity=necessity["rational"],
            practice_necessity=necessity["practice"],
            reflection_necessity=necessity["reflection"],
        )
        log.info("question_preprocessing.done",
                 task_nature=task_nature, complexity=complexity,
                 intent=result.question_intent[:50],
                 skips=[p for p, n in necessity.items() if n == "skip"])
        return result

    # ═══════════════════════════════════════════════════════════════
    # 各 Step 方法
    # ═══════════════════════════════════════════════════════════════

    async def _step_task_nature(self, question: str, conversation_history: str = "") -> dict:
        content = f"用户问题：{question}"
        if conversation_history:
            content = f"对话历史：\n{conversation_history}\n\n---\n\n{content}"
        # fallback：LLM 失败时，极短问题（<20字符，通常是寒暄/简单问句）保守判为无需调查，
        # 避免因 API 超时/解析失败把寒暄拖入 investigation 卡住。
        # 这是 LLM 失败兜底，不是主逻辑硬编码——正常 LLM 调用仍完全由模型判断。
        _short_q = len(question.strip()) < 20
        _fallback = {
            "task_nature": "other",
            "complexity": "simple" if _short_q else "standard",
            "needs_investigation": not _short_q,
            "reasoning": "解析失败-兜底",
        }
        result = await self._call_step(
            _STEP1_TASK_NATURE_PROMPT,
            content,
            "task_nature",
            _fallback,
            temperature=0.3, max_tokens=256,
            depth=Depth.SHALLOW,
        )
        log.debug("question_preprocessing.step1_result",
                  question=question[:60],
                  needs_investigation=result.get("needs_investigation"),
                  task_nature=result.get("task_nature"),
                  reasoning=result.get("reasoning", "")[:80])
        return result

    async def _step_contradiction_in_intent(self, question: str, task_nature: str, conversation_history: str = "") -> dict:
        content = f"用户问题：{question}\n任务性质：{task_nature}"
        if conversation_history:
            content = f"对话历史：\n{conversation_history}\n\n---\n\n{content}"
        return await self._call_step(
            _STEP3_CONTRADICTION_IN_INTENT_PROMPT,
            content,
            "contradiction",
            {"contradiction_in_question": ""},
            temperature=0.4, max_tokens=256,
            depth=Depth.SHALLOW,
        )

    async def _step_premise_audit(self, question: str, task_nature: str, conversation_history: str = "") -> dict:
        content = f"用户问题：{question}\n任务性质：{task_nature}"
        if conversation_history:
            content = f"对话历史：\n{conversation_history}\n\n---\n\n{content}"
        return await self._call_step(
            _STEP4_PREMISE_AUDIT_PROMPT,
            content,
            "premise_audit",
            {"questionable_premises": [], "overlooked_factors": []},
            temperature=0.4, max_tokens=512,
            depth=Depth.SHALLOW,
        )

    async def _step_structure(
        self, question: str, task_nature: str, complexity: str,
        contradiction: str, premises: list[str], overlooked: list[str],
        conversation_history: str = "",
    ) -> dict:
        ctx_parts = [
            f"用户原始问题：{question}",
            f"任务性质：{task_nature}",
            f"复杂度：{complexity}",
        ]
        if contradiction:
            ctx_parts.append(f"意图矛盾（之前步骤的分析结果）：{contradiction}")
        if premises:
            ctx_parts.append(f"可疑预设（之前步骤的审查结果）：{'；'.join(premises)}")
        if overlooked:
            ctx_parts.append(f"被忽略因素（之前步骤的审视结果）：{'；'.join(overlooked)}")

        content = "\n".join(ctx_parts)
        if conversation_history:
            content = f"对话历史：\n{conversation_history}\n\n---\n\n{content}"

        return await self._call_step(
            _STEP5_STRUCTURE_PROMPT,
            content,
            "structure",
            {
                "question_intent": "",
                "core_anxiety": "",
                "question_domains": [],
                "structured_sub_questions": [],
                "expanded_question": question,
                "clarifying_questions": [],
                "wants_detailed_report": False,
            },
            temperature=0.5, max_tokens=1024,
            depth=_depth_for_complexity(complexity),  # type: ignore[arg-type]
        )

    async def _step_analysis_and_structure(
        self,
        question: str,
        task_nature: str,
        complexity: str,
        do_step3: bool,
        do_step4: bool,
        conversation_history: str = "",
    ) -> dict | None:
        """Run the merged fast path; return None to activate the B1 fallback."""
        content = "\n".join(
            [
                f"用户原始问题：{question}",
                f"任务性质：{task_nature}",
                f"复杂度：{complexity}",
                f"执行意图矛盾分析：{'true' if do_step3 else 'false'}",
                f"执行预设审查：{'true' if do_step4 else 'false'}",
            ]
        )
        if conversation_history:
            content = f"对话历史：\n{conversation_history}\n\n---\n\n{content}"

        default_result = {
            "_combined_failed": True,
            "contradiction_in_question": "",
            "questionable_premises": [],
            "overlooked_factors": [],
            "question_intent": "",
            "core_anxiety": "",
            "question_domains": [],
            "structured_sub_questions": [],
            "expanded_question": question,
            "clarifying_questions": [],
            "wants_detailed_report": False,
        }
        # 按复杂度注入输出字段分层说明（schema_level）
        depth = _depth_for_complexity(complexity)
        _scope = {
            Depth.SHALLOW: (
                "## 输出字段范围\n"
                "本次仅需输出 question_intent 与 expanded_question 两个字段，"
                "其余字段（contradiction_in_question / questionable_premises / "
                "overlooked_factors / core_anxiety / question_domains / "
                "structured_sub_questions / clarifying_questions / wants_detailed_report）"
                "输出默认空值即可。"
            ),
            Depth.STANDARD: (
                "## 输出字段范围\n"
                "输出全部字段，字段需完整。"
            ),
            Depth.DEEP: (
                "## 输出字段范围\n"
                "输出全部字段且每个字段都要充实：contradiction_in_question、"
                "questionable_premises、overlooked_factors 需详因，"
                "expanded_question 需尽可能详尽以支撑后续详实分析。"
            ),
        }.get(depth, "")
        if _scope:
            content = content + "\n\n" + _scope

        result = await self._call_step(
            _STEP345_COMBINED_PROMPT,
            content,
            "analysis_structure",
            default_result,
            temperature=0.4,
            max_tokens=1536,
            depth=depth,
        )
        # C3：按当前深度校验必填字段层。
        # SHALLOW 只强制 question_intent/expanded_question（其余字段缺省合法，下游 .get 有默认）；
        # STANDARD/DEEP 要求全部字段。
        _shallow = depth == Depth.SHALLOW
        _required_fields = (
            {"question_intent", "expanded_question"}
            if _shallow
            else (set(default_result) - {"_combined_failed"})
        )
        list_fields = {
            "questionable_premises",
            "overlooked_factors",
            "question_domains",
            "structured_sub_questions",
            "clarifying_questions",
        }
        string_fields = {
            "contradiction_in_question",
            "question_intent",
            "core_anxiety",
            "expanded_question",
        }
        invalid_fields: list[str] = []
        if isinstance(result, dict):
            for name in list_fields:
                if name not in result:
                    continue
                val = result.get(name)
                if not isinstance(val, list) or not all(isinstance(item, str) for item in val):
                    invalid_fields.append(name)
            for name in string_fields:
                if name in result and not isinstance(result.get(name), str):
                    invalid_fields.append(name)
            if "wants_detailed_report" in result and not isinstance(result.get("wants_detailed_report"), bool):
                invalid_fields.append("wants_detailed_report")

        if (
            not isinstance(result, dict)
            or result.get("_combined_failed")
            or not _required_fields.issubset(result)
            or invalid_fields
        ):
            missing = sorted(_required_fields - set(result)) if isinstance(result, dict) else []
            log.warning(
                "question_preprocessing.analysis_structure.invalid_schema",
                missing=missing,
                invalid=sorted(invalid_fields),
            )
            return None
        return result

    # ═══════════════════════════════════════════════════════════════
    # 通用工具方法
    # ═══════════════════════════════════════════════════════════════

    async def _call_step(
        self, system_prompt: str, user_content: str, step_name: str,
        default_result: dict, temperature: float = 0.3, max_tokens: int = 512,
        depth=None,
    ) -> dict:
        """通用的单步 LLM 调用 + JSON 解析。失败时返回 default_result。

        depth 指定时：max_tokens 取 DEPTH_CONFIG[depth] 的三要素预算（若不显式更高），
        并在 system_prompt 后追加对应推理指令。不再透传 provider 私有 reasoning_effort。
        """
        try:
            from .depth import DEPTH_CONFIG, parse_depth
            _mt = max_tokens
            _sys = system_prompt
            if depth is not None:
                _d = parse_depth(depth)
                _cfg = DEPTH_CONFIG.get(_d, {})
                # 显式传入的 max_tokens 优先；否则按深度档位预算
                if max_tokens is None:
                    _mt = int(_cfg.get("max_tokens", 512))
                _instr = _cfg.get("instruction")
                if _instr:
                    _sys = system_prompt + "\n\n## 推理深度\n" + _instr
            response = await self.llm.call(
                messages=[{"role": "user", "content": user_content}],
                system=_sys,
                temperature=temperature,
                max_tokens=_mt,
            )
            return self._parse_json_safe(response.content, step_name, default_result)
        except Exception as e:
            log.warning(f"question_preprocessing.{step_name}.call_error", error=str(e))
            return default_result

    def _parse_json_safe(self, raw: str, step_name: str, default_result: dict) -> dict:
        """解析 LLM 返回的 JSON。带 Markdown fence 剥离和截断修复。"""
        raw = raw.strip()
        # 剥离 Markdown 代码块
        if raw.startswith("```"):
            idx = raw.find("\n")
            if idx >= 0:
                raw = raw[idx + 1:]
            if raw.endswith("```"):
                raw = raw[:-3]
        raw = raw.strip().rstrip("`")

        # 直接解析
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # 截断修复：尝试补全不完整的 JSON
        if not raw.endswith("}"):
            for suffix in ["}", "]}", '"}"]', '"}}', '}]}']:
                try:
                    return json.loads(raw + suffix)
                except json.JSONDecodeError:
                    continue

        log.warning(f"question_preprocessing.{step_name}.parse_error", raw=raw[:200])
        return default_result
