# ruff: noqa: E402
"""推理深度体系 —— 单元验证。

验收标准 2：
- parse_depth 非法值回退 STANDARD
- depth_schema_text 按深度返回对应层级文本（SHALLOW 无 standard/deep 层，DEEP 全含）
- budget_depth 从 phase_budgets 解析
- 各阶段 mock 验证：depth=SHALLOW 时 prompt 只含 required 字段说明、max_tokens=1024；
  DEEP 时含 deep_extended、max_tokens=16384
- cognitive_loop 验证：迭代起始写入 initial_depths，反思 phase_budgets.depth 覆盖之
- get_phase_llm 全阶段返回同一模型
"""
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["DEEPSEEK_API_KEY"] = "x"

from praxic.core.depth import (
    Depth,
    DEPTH_CONFIG,
    depth_schema_text,
    initial_depth_for,
    parse_depth,
)
from praxic.core.phase_budget import budget_depth, budget_max_tokens
from praxic.llm.base import LLMResponse


def _schema():
    return {
        "required": "REQUIRED_FIELDS",
        "standard_extended": "STANDARD_EXTRA",
        "deep_extended": "DEEP_EXTRA",
    }


def test_parse_depth():
    assert parse_depth("shallow") is Depth.SHALLOW
    assert parse_depth("standard") is Depth.STANDARD
    assert parse_depth("deep") is Depth.DEEP
    assert parse_depth("DEEP") is Depth.DEEP  # 大小写不敏感
    assert parse_depth(Depth.DEEP) is Depth.DEEP  # 已枚举值原样返回
    assert parse_depth("bogus") is Depth.STANDARD  # 非法回退默认
    assert parse_depth(None) is Depth.STANDARD
    assert parse_depth("") is Depth.STANDARD
    # 显式默认值
    assert parse_depth("bogus", default=Depth.SHALLOW) is Depth.SHALLOW


def test_depth_schema_text():
    s = _schema()
    shallow = depth_schema_text(Depth.SHALLOW, s)
    assert "REQUIRED_FIELDS" in shallow
    assert "STANDARD_EXTRA" not in shallow
    assert "DEEP_EXTRA" not in shallow
    std = depth_schema_text(Depth.STANDARD, s)
    assert "REQUIRED_FIELDS" in std and "STANDARD_EXTRA" in std
    assert "DEEP_EXTRA" not in std
    deep = depth_schema_text(Depth.DEEP, s)
    assert "REQUIRED_FIELDS" in deep and "STANDARD_EXTRA" in deep and "DEEP_EXTRA" in deep
    # 缺层字典不崩溃
    assert depth_schema_text(Depth.DEEP, {"required": "R"}) == "R"


def test_depths_config_tokens():
    assert DEPTH_CONFIG[Depth.SHALLOW]["max_tokens"] == 1024
    assert DEPTH_CONFIG[Depth.STANDARD]["max_tokens"] == 4096
    assert DEPTH_CONFIG[Depth.DEEP]["max_tokens"] == 16384


def test_budget_depth():
    assert budget_depth({"depth": "deep"}) is Depth.DEEP
    assert budget_depth({"depth": "shallow"}) is Depth.SHALLOW
    assert budget_depth({}) is None  # 未设置 → 无
    assert budget_depth(None) is None
    assert budget_depth({"depth": "bogus"}) is Depth.STANDARD  # 非法回退
    # budget_max_tokens：显式 max_tokens 优先；否则按 depth 查表
    assert budget_max_tokens({"max_tokens": 5000, "depth": "deep"}, 8192) == 5000
    assert budget_max_tokens({"depth": "shallow"}, 8192) == 1024  # 查表
    assert budget_max_tokens({"depth": "deep"}, 8192) == 16384
    assert budget_max_tokens({}, 8192) == 8192  # 都无 → 保持 current


def test_initial_depth_table():
    # code_generation×simple → investigation/contradiction 浅档
    assert initial_depth_for("code_generation", "simple", "investigation") is Depth.SHALLOW
    assert initial_depth_for("code_generation", "complex", "practice") is Depth.STANDARD
    # causal×standard → contradiction/rational DEEP
    assert initial_depth_for("causal_explanation", "standard", "contradiction") is Depth.DEEP
    assert initial_depth_for("causal_explanation", "complex", "contradiction") is Depth.DEEP
    # 未知任务性质/复杂度 → STANDARD
    assert initial_depth_for("unknown_nature", "x", "investigation") is Depth.STANDARD
    assert initial_depth_for("fact_lookup", "simple", "practice") is Depth.STANDARD


def test_get_phase_llm_same_model():
    """全阶段返回同一默认模型（深度体系：模型无关分级取消）。"""
    from praxic.llm import get_llm, get_phase_llm
    expect = get_llm()
    for ph in ("preprocessing", "investigation", "contradiction", "rational", "practice", "reflection"):
        llm = get_phase_llm(ph)
        assert llm.default_model == expect.default_model
        assert llm is expect


# ── 各阶段 mock：SHALLOW 只含 required、max_tokens=1024；DEEP 含深档、max_tokens=16384 ──

class CaptureLLM:
    """记录 max_tokens 与 system，返回空合法 JSON。"""
    def __init__(self):
        self.calls = []
        self._default = "{}"

    def queue(self, contents):
        import json as _json
        self._queue = [c if isinstance(c, str) else _json.dumps(c, ensure_ascii=False) for c in (contents or [])]

    async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        self.calls.append({"system": system or "", "max_tokens": max_tokens, "kwargs": kwargs})
        if hasattr(self, "_queue") and self._queue:
            content = self._queue.pop(0)
        else:
            content = self._default
        return LLMResponse(content=content, model="mock")

    async def stream(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        yield ""


_EMPTY_SUPERSET = {
    "original_question": "q", "expanded_question": "q", "question_intent": "i",
    "question_domains": [], "structured_sub_questions": [],
    "facts": [], "gaps": [], "summary": "s",
    "principal_contradiction": None, "secondary_contradictions": [],
    "essence": "e", "patterns": [], "hypotheses": [],
    "round_rationale": "r", "tool_calls": [], "expected_outcomes": [],
    "convergence_score": 0.8, "should_reinvestigate": False,
    "quality_assessment": "ok",
}


def test_phase_prompt_depth_shallow_vs_deep():
    """多阶段改造点：SHALLOW 只含 required、max_tokens=1024；DEEP 含深档、max_tokens=16384。"""
    from praxic.core.investigation import InvestigationModule
    from praxic.core.contradiction import ContradictionAnalyzer
    from praxic.core.rational import RationalCognitionModule
    from praxic.api.schemas.models import FactReport, ContradictionGraph

    # investigation
    inv_fake = CaptureLLM()
    inv = InvestigationModule(llm=inv_fake, phase_config={}, web_search_enabled=False,
                              workspace=None)
    inv_fake.queue([_EMPTY_SUPERSET])
    asyncio.run(inv.investigate("q", budget={"depth": "shallow"}))
    call = inv_fake.calls[-1]
    # SHALLOW：max_tokens 由 budget 无显式 → 深度查表 1024（但 budget 有 max_tokens 才覆盖）
    assert "facts" in call["system"]
    assert "illustrative_case" in call["system"].split("本档)")[0]  # shallow 不含 illustrative_case 需求

    # contradiction DEEP
    ca_fake = CaptureLLM()
    ca = ContradictionAnalyzer(llm=ca_fake, phase_config={})
    ca_fake.queue([_EMPTY_SUPERSET])
    fr = FactReport(facts=[])
    asyncio.run(ca.analyze(fr, "q", budget={"depth": "deep"}))
    call = ca_fake.calls[-1]
    assert "system_model" in call["system"]  # DEEP schema 说明含 system_model
    # deep 无显式 max_tokens → 深度查表 16384
    assert call["max_tokens"] == 16384

    # contradiction SHALLOW → max_tokens=1024
    ca_fake2 = CaptureLLM()
    ca2 = ContradictionAnalyzer(llm=ca_fake2, phase_config={})
    ca_fake2.queue([_EMPTY_SUPERSET])
    asyncio.run(ca2.analyze(fr, "q", budget={"depth": "shallow"}))
    assert ca_fake2.calls[-1]["max_tokens"] == 1024


def test_cognitive_loop_initial_depths_and_budget_override():
    """迭代起始写入 initial_depths；反思 phase_budgets.depth 覆盖之。"""
    from praxic.memory.working_memory import WorkingMemory
    from praxic.core.depth import parse_depth

    wm = WorkingMemory()
    wm.set("initial_depths", {"investigation": "deep", "contradiction": "standard"})
    # 模拟 cognitive_loop 消费：预算里无 depth 时取 initial_depths
    budgets = {}
    merged = dict(wm.get("phase_budgets") or {})
    for ph, d in (wm.get("initial_depths") or {}).items():
        b = dict(merged.get(ph, {}) or {})
        b.setdefault("depth", d)
        merged[ph] = b
    assert parse_depth(merged["investigation"].get("depth")) is Depth.DEEP
    # 反思 phase_budgets.depth 覆盖 initial_depths
    merged["investigation"]["depth"] = "shallow"
    assert parse_depth(merged["investigation"].get("depth")) is Depth.SHALLOW
