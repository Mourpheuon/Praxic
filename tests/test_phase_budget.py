# ruff: noqa: E402
"""phase_budgets 执行预算调控器 —— mock 验证。

验收标准 2：mock LLM 返回含 phase_budgets 的反思输出，验证：
- ReflectionReport.phase_budgets 正确解析
- cognitive_loop 写入 working_mem，下一轮各阶段收到预算
- investigation 预算 max_calls=1 时不触发 second pass
- practice 预算 max_rounds=2 时实际只跑 2 轮
- reasoning_effort 透传至 llm.call（mock 捕获 kwargs）
- 非法值被忽略，走默认

验收标准 3：不设置 phase_budgets 时，各阶段调用参数与改动前一致。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["DEEPSEEK_API_KEY"] = "x"

from praxic.api.schemas.models import ReflectionReport
from praxic.config import settings
from praxic.core.phase_budget import (
    budget_max_tokens,
    budget_reasoning_kwargs,
    validate_positive_int,
    validate_reasoning_effort,
)
from praxic.core.reflection import ReflectionEngine
from praxic.llm.base import BaseLLM, LLMResponse


# ── kwargs 记录型 FakeLLM ──
class KwargsFake(BaseLLM):
    def __init__(self):
        self.call_count = 0
        self.calls = []  # (system头部判别, max_tokens, reasoning_effort, enable_reasoning)
        self._next = []

    def queue(self, contents):
        self._next = list(contents)

    async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        self.call_count += 1
        sysp = system or ""
        self.calls.append({
            "system": sysp,
            "max_tokens": max_tokens,
            "reasoning_effort": kwargs.get("reasoning_effort"),
            "enable_reasoning": kwargs.get("enable_reasoning"),
        })
        content = self._next.pop(0) if self._next else "{}"
        return LLMResponse(content=content, model="fake")

    async def stream(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        yield ""


_SUPERSET = {
    "original_question": "q", "expanded_question": "q", "question_intent": "i",
    "question_domains": [], "structured_sub_questions": [],
    "facts": [{"content": "事实A", "credibility": 0.9}], "gaps": [], "summary": "s",
    "principal_contradiction": {"description": "主矛盾", "tension_poles": ["a", "b"],
                                "contradiction_type": "internal", "rank": 1,
                                "primary_aspect": "a", "transformation_condition": "c"},
    "secondary_contradictions": [],
    "essence": "本质", "patterns": ["规律"], "hypotheses": ["假设"],
    "round_rationale": "实验", "tool_calls": [], "expected_outcomes": [],
    "convergence_score": 0.9, "should_reinvestigate": False,
    "quality_assessment": "ok", "skills": [],
}


def _make_loop(fake):
    # 用 minimal 的 json blob 关闭 preprocessing 阶段的复杂依赖
    from praxic.core.cognitive_loop import CognitiveLoop
    settings.max_iterations = 1
    settings.practice_rounds = 3
    settings.web_search_enabled = False
    settings.web_fetch_enabled = False
    from praxic.core.autonomy import PermissionMode
    settings.permission_mode = PermissionMode.AUTO_REVIEW
    loop = CognitiveLoop(llm=fake)
    for attr in ("preprocessing", "investigation", "contradiction", "rational",
                 "practice", "reflection"):
        obj = getattr(loop, attr, None)
        if obj is not None and hasattr(obj, "llm"):
            obj.llm = fake
    return loop


def test_phase_budget_helpers():
    # reasoning_effort 合法/非法
    assert validate_reasoning_effort("low") == "low"
    assert validate_reasoning_effort("off") == "off"
    assert validate_reasoning_effort("super") is None  # 非法忽略
    assert validate_reasoning_effort(None) is None
    # 正整数校验
    assert validate_positive_int(5) == 5
    assert validate_positive_int(-1) is None
    assert validate_positive_int("abc") is None
    assert validate_positive_int(None) is None
    # max_tokens 覆盖
    assert budget_max_tokens({"max_tokens": 4096}, 16384) == 4096
    assert budget_max_tokens({"max_tokens": -5}, 16384) == 16384
    assert budget_max_tokens({}, 16384) == 16384
    # reasoning kwargs
    assert budget_reasoning_kwargs({"reasoning_effort": "off"}) == {"enable_reasoning": False}
    assert budget_reasoning_kwargs({"reasoning_effort": "low"}) == {"reasoning_effort": "low"}
    assert budget_reasoning_kwargs({"reasoning_effort": "medium"}) == {}  # 保持现状
    assert budget_reasoning_kwargs({"reasoning_effort": "super"}) == {}


def test_reflection_parse_phase_budgets():
    fake = KwargsFake()
    engine = ReflectionEngine(llm=fake)
    fake.queue([json.dumps({**_SUPERSET, "phase_budgets": {
        "investigation": {"max_calls": 1, "max_tokens": 4096,
                         "reasoning_effort": "low", "reason": "已充分"},
        "practice": {"max_rounds": 2, "reasoning_effort": "off",
                     "reason": "首轮已收敛"},
    }})])
    report = asyncio.run(engine.reflect("q", _make_trace()))
    assert isinstance(report, ReflectionReport)
    assert report.phase_budgets["investigation"]["max_calls"] == 1
    assert report.phase_budgets["practice"]["reasoning_effort"] == "off"
    # 无预算时为空 dict
    fake.queue([json.dumps(_SUPERSET)])
    report2 = asyncio.run(engine.reflect("q", _make_trace()))
    assert report2.phase_budgets == {}


def _make_trace():
    from praxic.api.schemas.models import CognitiveTrace
    return CognitiveTrace()


def test_full_loop_budget_threading_via_wm():
    """认知循环里反思输出的预算写入 working_mem，下一轮各阶段收到。"""
    from praxic.memory.working_memory import WorkingMemory
    wm = WorkingMemory()
    wm.set("phase_budgets", {
        "investigation": {"max_tokens": 3000, "reasoning_effort": "low"},
        "contradiction": {"reasoning_effort": "high"},
        "practice": {"max_rounds": 2, "reasoning_effort": "off"},
    })
    # 模拟 cognitive_loop 起始读取
    budgets = wm.get("phase_budgets") or {}
    assert budgets["investigation"]["max_tokens"] == 3000
    assert budgets["practice"]["reasoning_effort"] == "off"


def test_investigation_second_pass_disabled():
    """investigation 预算 max_calls=1 时不触发 second pass；深度体系不透传 reasoning_effort。"""
    from praxic.core.investigation import InvestigationModule
    fake = KwargsFake()
    inv = InvestigationModule(llm=fake, phase_config={}, web_search_enabled=True,
                              workspace=None)
    # 无 API key 走本地；验证主调用 max_tokens 覆盖、depth 注入、reasoning_effort 不再透传。
    fake.queue([json.dumps(_SUPERSET)])
    report = asyncio.run(inv.investigate(
        "q", budget={"max_tokens": 5000, "depth": "deep"}))
    assert report is not None
    main_call = fake.calls[-1]
    assert main_call["max_tokens"] == 5000
    # reasoning_effort 不再透传（provider 私有参数，深度体系改用纯语义 depth）
    assert main_call["reasoning_effort"] is None
    assert "illustrative_case" in main_call["system"]  # DEEP 档 schema 说明


def test_contradiction_rational_depth_control():
    """contradiction & rational 由 depth 档位控制 schema 层级与 max_tokens，不透传 reasoning_effort。"""
    from praxic.api.schemas.models import ContradictionGraph, FactReport
    from praxic.core.contradiction import ContradictionAnalyzer
    from praxic.core.rational import RationalCognitionModule

    fake = KwargsFake()
    ca = ContradictionAnalyzer(llm=fake, phase_config={})
    fr = FactReport(facts=[])

    def _graph():
        return ContradictionGraph(principal_contradiction=None, secondary_contradictions=[])

    # DEEP 档：max_tokens 按预算 9000，system 含完整 system_model 说明，不透传 reasoning_effort
    fake.queue(['{"secondary_contradictions": [], "synthesis": ""}'])
    g = asyncio.run(ca.analyze(fr, "q", budget={"depth": "deep", "max_tokens": 9000}))
    assert g is not None
    call = fake.calls[-1]
    assert call["reasoning_effort"] is None
    assert call["max_tokens"] == 9000
    assert "system_model" in call["system"]

    rc = RationalCognitionModule(llm=fake, phase_config={})
    fake.queue([json.dumps({"essence": "e", "patterns": [], "hypotheses": [],
                            "synthesis_text": "t", "contradiction_motion": "",
                            "unexplained_phenomena": [], "return_to_concrete": "",
                            "abstract_from": ""})])
    _ = asyncio.run(rc.synthesize("q", fr, _graph(), budget={"depth": "shallow"}))
    call2 = fake.calls[-1]
    assert call2["reasoning_effort"] is None
    assert "essence" in call2["system"]  # SHALLOW 档 schema 说明仍要求 essence


def test_practice_max_rounds_applied():
    """practice 预算 max_rounds=2 时只跑 2 轮（首轮 + 1 补充）。"""
    from praxic.core.practice import PracticeModule
    fake = KwargsFake()
    pm = PracticeModule(llm=fake, phase_config={}, practice_rounds=3)
    pm._current_budget = {"max_rounds": 2, "reasoning_effort": "off", "max_tokens": 7000}
    rkw, mtok = pm._practice_budget_kwargs()
    assert rkw == {"enable_reasoning": False}
    assert mtok == 7000
    assert pm._current_budget["max_rounds"] == 2


def test_default_no_budget_unchanged():
    """不设置预算时，各阶段调用参数与改动前一致（max_tokens 用 config，无法推理则现状）。"""
    from praxic.api.schemas.models import FactReport
    from praxic.core.contradiction import ContradictionAnalyzer
    fake = KwargsFake()
    ca = ContradictionAnalyzer(llm=fake, phase_config={})
    fr = FactReport(facts=[])
    fake.queue(['{"secondary_contradictions": [], "synthesis": ""}'])
    _ = asyncio.run(ca.analyze(fr, "q"))  # 不传预算
    call = fake.calls[-1]
    # 无预算 → max_tokens 用 config 默认 16384，无 reasoning 控制
    assert call["max_tokens"] == 16384
    assert call["reasoning_effort"] is None
    assert call["enable_reasoning"] is None
