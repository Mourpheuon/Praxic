"""Practice-phase multi-step toolchain integration test.

真实任务链：解压数据包 → 查询数据 → 编辑脚本 → 压缩产物。
同时验证 L2 产物台账跨轮注入到下一轮规划提示词。
"""
import asyncio
import json
import zipfile
from pathlib import Path

import pytest

from praxic.api.schemas.models import (
    CognitiveTrace,
    ContradictionGraph,
    Fact,
    FactReport,
    RationalSynthesis,
)
from praxic.config import settings
from praxic.core.autonomy import PermissionMode
from praxic.core.practice import PracticeModule
from praxic.llm.base import BaseLLM, LLMResponse
from praxic.memory.working_memory import WorkingMemory
from praxic.tools.filesystem import WorkspaceToolkit

# 沙箱内变更自动放行，验证工具链与台账而非权限交互
settings.permission_mode = PermissionMode.AUTO_REVIEW


class ChainLLM(BaseLLM):
    """真实任务链 mock：按轮次返回工具规划，代码生成返回可运行脚本。"""

    def __init__(self):
        self.sys_prompts: list[str] = []
        self.round = 0

    async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        self.sys_prompts.append(system or "")
        user = messages[-1]["content"] if messages else ""
        if "为文件" in user or "生成代码" in user:
            return LLMResponse(
                content=(
                    "import json\n"
                    "import sys; sys.stdout.reconfigure(encoding='utf-8')\n"
                    "print(json.dumps({'status':'ok','data':{'count':3},'summary':'ok'}, ensure_ascii=False))\n"
                ),
                model="fake",
            )
        if "综合分析" in user or "知性评估" in user:
            return LLMResponse(
                content=json.dumps({
                    "verdict": "confirmed",
                    "analysis": "工具链可完整执行",
                    "claim_assessments": [],
                }, ensure_ascii=False),
                model="fake",
            )
        self.round += 1
        if self.round == 1:
            plan = {
                "round_rationale": "解压数据包并查询结构",
                "epistemic_role": "exploration",
                "directional_claim": "数据包可解压且含 CSV（来自假设）",
                "deviation_rationale": "",
                "tool_calls": [
                    {"tool": "archive_extract", "params": {"path": "data.zip", "target_dir": "raw"}},
                    {"tool": "data_query", "params": {"path": "raw/data.csv", "action": "overview"}},
                ],
                "expected_outcomes": ["数据解压并了解结构"],
                "done": False,
            }
        else:
            # 第 2 轮：依赖第 1 轮产物路径（台账应已注入 raw/data.csv）
            plan = {
                "round_rationale": "处理数据并压缩产物",
                "epistemic_role": "verification",
                "directional_claim": "数据可处理并打包（来自第1轮验证）",
                "deviation_rationale": "",
                "tool_calls": [
                    {"tool": "python_exec", "params": {"code_ref": "分析 raw/data.csv", "timeout_seconds": 30}},
                    {"tool": "archive_create", "params": {"paths": ["raw"], "archive_path": "result.zip"}},
                ],
                "expected_outcomes": ["产物已打包"],
                "done": True,
            }
        return LLMResponse(content=json.dumps(plan, ensure_ascii=False), model="fake")

    async def stream(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        yield ""


@pytest.fixture
def chain_ws(tmp_path):
    with zipfile.ZipFile(tmp_path / "data.zip", "w") as zf:
        zf.writestr("raw/data.csv", "city,value\n北京,10\n上海,20\n广州,30\n")
    return tmp_path


def _make_trace() -> CognitiveTrace:
    trace = CognitiveTrace()
    trace.investigation = FactReport(facts=[Fact(content="存在数据包", credibility=0.9)], gaps=[])
    trace.rational_synthesis = RationalSynthesis(
        essence="数据需解压清洗", hypotheses=["数据包含 CSV"]
    )
    trace.contradictions = ContradictionGraph()
    return trace


@pytest.mark.asyncio
async def test_multistep_toolchain_executes(chain_ws):
    ws = WorkspaceToolkit(workspace_dir=chain_ws)
    fake = ChainLLM()
    mod = PracticeModule(llm=fake, workspace=ws, practice_rounds=2, max_retries=3)
    report = await mod.practice(
        question="解压并分析数据包", trace=_make_trace(), wm=WorkingMemory(session_id="chain")
    )
    assert report is not None
    tools = [tc.get("tool") for tc in (report.tool_call_records or [])]
    assert "archive_extract" in tools
    assert "data_query" in tools
    assert "python_exec" in tools
    assert "archive_create" in tools
    # 产物落盘
    assert (chain_ws / "raw" / "data.csv").exists()
    assert (chain_ws / "result.zip").exists()


@pytest.mark.asyncio
async def test_artifact_ledger_reaches_round2(chain_ws):
    ws = WorkspaceToolkit(workspace_dir=chain_ws)
    fake = ChainLLM()
    mod = PracticeModule(llm=fake, workspace=ws, practice_rounds=2, max_retries=3)
    await mod.practice(
        question="解压并分析数据包", trace=_make_trace(), wm=WorkingMemory(session_id="chain2")
    )
    r2 = [s for s in fake.sys_prompts if "第 2 轮" in s]
    assert r2, "round-2 prompt not found"
    prompt = r2[0]
    assert "可用产物" in prompt
    assert "raw/data.csv" in prompt
    assert "{artifacts_text}" not in prompt
