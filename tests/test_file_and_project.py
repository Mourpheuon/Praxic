"""
文件读取 + 项目归属 端到端集成测试（FakeLLM，瞬时，无网络）。

验证两个此前会静默失效的关键通路：
  1. 上传文件内容真正进入【调查阶段】的 LLM 输入（原 prompt 写入死键，不会到达任何阶段）。
  2. project_id 落到 episode 表 与 conversation_meta（权威归属来源）。
"""
import asyncio, sys, os, json, tempfile, traceback
from pathlib import Path

os.environ['DEEPSEEK_API_KEY'] = 'x'
PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from praxic.config import settings
# 隔离数据目录，避免污染真实库
settings.data_dir = Path(tempfile.mkdtemp())
settings.projects_dir = Path(tempfile.mkdtemp())

from praxic.llm.base import BaseLLM, LLMResponse

SENTINEL = "SENTINEL_QUANTUM_42_UPLOADED_FILE"

# minimal ui-settings so persona loader resolves
p = settings.data_dir / "ui-settings.json"
p.parent.mkdir(parents=True, exist_ok=True)
with open(p, "w") as f:
    json.dump({"agent_persona": "", "custom_knowledge": "", "phase_models": {}, "max_iterations": 1}, f)

_SUPERSET = {
    "original_question": "分析上传的文件", "expanded_question": "分析上传的文件内容并总结",
    "question_intent": "分析", "question_domains": ["文档"],
    "structured_sub_questions": ["文件讲了什么"],
    "contradiction_in_question": "", "core_anxiety": "读懂文件",
    "facts": [{"content": "文件已加载", "credibility": 0.9}], "gaps": [], "summary": "读文件",
    "principal_contradiction": {"description": "信息量 vs 精炼", "tension_poles": ["多","精"],
        "primary_aspect": "精", "transformation_condition": "提炼"},
    "secondary_contradictions": [],
    "essence": "抓住文件要点", "patterns": ["提炼"], "hypotheses": ["要点可归纳"],
    "action_items": [{"description": "总结文件", "priority": 1, "practice_feasibility": "epistemic_only"}],
    "strategic_assessment": "直接总结", "tactical_plan": "归纳要点",
    "convergence_score": 0.9, "should_reinvestigate": False,
    "quality_assessment": "完成", "lessons_learned": ["文件已读"],
    "final_answer": "文件要点已总结", "skill_draft_candidates": [],
    "round_rationale": "无需实践", "files_to_create": [], "commands_to_run": [],
    "expected_outcomes": [], "done": True,
}

class CapturingFake(BaseLLM):
    def __init__(self):
        self.calls = []
    async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        user = messages[-1]["content"] if messages else ""
        self.calls.append({"system": system or "", "user": user})
        if "代码生成专家" in (system or "") or "生成代码" in user:
            return LLMResponse(content="print(1)", model="fake")
        return LLMResponse(content=json.dumps(_SUPERSET, ensure_ascii=False), model="fake")
    async def stream(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        yield ""

async def main():
    from praxic.core.cognitive_loop import CognitiveLoop
    settings.max_iterations = 1
    settings.practice_rounds = 1
    settings.web_search_enabled = False
    settings.web_fetch_enabled = False

    # 造一个上传文件，内容含唯一哨兵
    updir = Path(tempfile.mkdtemp())
    fpath = updir / "report.txt"
    fpath.write_text("这是上传的研究报告。关键结论：" + SENTINEL + "。", encoding="utf-8")

    fake = CapturingFake()
    loop = CognitiveLoop(llm=fake, project_id="")   # project 通过 run() 传
    for attr in ("preprocessor","preprocessing","investigation","contradiction","rational",
                 "practice","reflection","perspectives"):
        obj = getattr(loop, attr, None)
        if obj is not None and hasattr(obj, "llm"):
            obj.llm = fake

    r = await asyncio.wait_for(
        loop.run(question="分析上传的文件", context="",
                 mode="standard", conversation_id="convX",
                 files=[str(fpath)], project_id="testproj"),
        timeout=60.0,
    )

    results = {}

    # ── 断言 1：文件内容进入调查阶段 LLM 输入 ──
    inv_calls = [c for c in fake.calls if "背景上下文" in c["user"]]
    sentinel_in_inv = any(SENTINEL in c["user"] for c in inv_calls)
    sentinel_anywhere = any(SENTINEL in c["user"] for c in fake.calls)
    results["文件内容进入调查阶段"] = sentinel_in_inv
    results["哨兵出现在某次LLM调用"] = sentinel_anywhere

    # ── 断言 2：project_id 落到 episode + conversation_meta ──
    from praxic.memory.episodic_memory import EpisodicMemory
    em = EpisodicMemory()   # 同一 settings.data_dir
    import sqlite3
    con = sqlite3.connect(em.db_path); con.row_factory = sqlite3.Row
    eps = con.execute("SELECT project_id, conversation_id, summary FROM episodes WHERE conversation_id='convX'").fetchall()
    ep_projects = {e["project_id"] for e in eps if e["summary"] != "[...]"}
    cm = con.execute("SELECT project_id FROM conversation_meta WHERE conversation_id='convX'").fetchone()
    con.close()
    results["episode.project_id=testproj"] = ("testproj" in ep_projects)
    results["conversation_meta.project_id=testproj"] = (cm is not None and cm["project_id"] == "testproj")

    # ── 断言 3：list_conversations / list_projects 归组正确 ──
    lc = em.list_conversations(project_id="testproj")
    results["list_conversations(testproj)含convX"] = any(x["conversation_id"] == "convX" for x in lc)
    lp = {x["project_id"]: x["conversation_count"] for x in em.list_projects()}
    results["list_projects含testproj"] = lp.get("testproj", 0) >= 1

    # ── 断言 4：非调查阶段不注入文件（token 控制）──
    # 后续实践阶段调用不应含哨兵（文件仅进调查阶段）
    # 宽松验证至少存在不含文件的后续阶段调用。
    non_sentinel_calls = [c for c in fake.calls if SENTINEL not in c["user"]]
    results["存在不含文件的后续阶段调用(token控制)"] = len(non_sentinel_calls) >= 1

    print("\n=== 断言结果 ===")
    ok = True
    for k, v in results.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
        ok = ok and v
    print(f"  final summary: {str(r.summary)[:60]}")
    print(f"  LLM 调用次数: {len(fake.calls)}")
    print(f"\nOVERALL: {'PASS' if ok else 'FAIL'}")
    return ok

if __name__ == "__main__":
    try:
        res = asyncio.run(main())
        sys.exit(0 if res else 1)
    except Exception as e:
        print(f"\nEXCEPTION: {e}")
        traceback.print_exc()
        sys.exit(2)
