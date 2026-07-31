"""
Full-loop STANDARD-mode integration test with a universal FakeLLM.
Exercises the complete 6-phase dispatch INCLUDING practice + reflection +
skill distillation — the code paths that fast-mode skips and that the
45s sandbox cap prevents testing with the real API.
Runs instantly (no network).
"""
import asyncio, sys, os, json, tempfile, traceback
from pathlib import Path

os.environ['DEEPSEEK_API_KEY'] = 'x'
PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from praxic.llm.base import BaseLLM, LLMResponse
from praxic.config import settings

# minimal ui-settings so persona loader + phase models resolve
p = settings.data_dir / "ui-settings.json"
p.parent.mkdir(parents=True, exist_ok=True)
with open(p, "w") as f:
    json.dump({"agent_persona": "", "custom_knowledge": "",
               "phase_models": {}, "max_iterations": 1}, f)

# Universal superset JSON — every phase parser picks the fields it needs.
_SUPERSET = {
    "original_question": "用Python计算1到100所有质数的和",
    "expanded_question": "用Python编写脚本计算1到100之间所有质数的和，涉及数据分析与算法",
    "question_intent": "行动方案",
    "question_domains": ["编程", "算法", "数学"],
    "structured_sub_questions": ["如何判断一个数是质数", "如何求和"],
    "contradiction_in_question": "效率与正确性",
    "core_anxiety": "得到正确结果",
    # investigation
    "facts": [{"content": "质数是大于1且只能被1和自身整除的自然数", "credibility": 0.95}],
    "gaps": [],
    "summary": "编写并运行质数求和脚本",
    # contradiction
    "principal_contradiction": {
        "description": "算法效率 vs 结果正确性",
        "tension_poles": ["效率", "正确性"],
        "primary_aspect": "正确性",
        "transformation_condition": "运行验证",
    },
    "secondary_contradictions": [],
    # rational
    "essence": "用试除法判断质数并累加",
    "patterns": ["试除法"],
    "hypotheses": ["遍历2到sqrt(n)可判断质数"],
    # practice planner fields — direct tool calls make the practice stage execute
    "action_items": [
        {"description": "编写质数求和脚本", "priority": 1, "practice_feasibility": "direct"},
    ],
    "strategic_assessment": "直接编码验证",
    "tactical_plan": "写脚本并运行",
    # reflection — low reinvestigate + high convergence + a distilled skill
    "convergence_score": 0.85,
    "should_reinvestigate": False,
    "quality_assessment": "完成，结果正确",
    "lessons_learned": ["试除法足够处理小范围"],
    "final_answer": "1到100的质数之和为1060",
    "skill_draft_candidates": [{
        "suggested_name": "prime-sum",
        "suggested_description": "质数求和模板",
        "suggested_type": "execution",
        "suggested_active_phases": ["practice"],
        "trigger_pattern": "质数计算，数论",
        "core_operations": "试除法遍历并累加",
        "confidence": 0.8,
    }],
    # practice planner fields (used if superset reaches planner)
    "round_rationale": "运行质数脚本建立基线",
    "files_to_create": [{"path": "primes.py", "purpose": "计算1到100所有质数的和并打印"}],
    "commands_to_run": [{"cmd": "python primes.py", "reason": "运行质数脚本", "timeout_seconds": 15}],
    "expected_outcomes": ["输出质数之和 1060"],
    "done": True,
}

_PRIME_CODE = (
    "def is_prime(n):\n"
    "    if n < 2:\n        return False\n"
    "    for i in range(2, int(n**0.5)+1):\n"
    "        if n % i == 0:\n            return False\n"
    "    return True\n\n"
    "if __name__ == '__main__':\n"
    "    print('质数之和:', sum(x for x in range(1,101) if is_prime(x)))\n"
)


class UniversalFake(BaseLLM):
    def __init__(self):
        self.n = 0
        self.routes = []

    async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        self.n += 1
        sysp = system or ""
        user = messages[-1]["content"] if messages else ""
        # Route: code generation → raw Python
        if "代码生成专家" in sysp or "生成代码" in user:
            self.routes.append("code")
            return LLMResponse(content=_PRIME_CODE, model="fake")
        if "代码调试专家" in sysp:
            self.routes.append("fix")
            return LLMResponse(content=json.dumps({"fixed_content": _PRIME_CODE, "fix_summary": "ok"}), model="fake")
        # Everything else → superset JSON
        self.routes.append("json")
        return LLMResponse(content=json.dumps(_SUPERSET, ensure_ascii=False), model="fake")

    async def stream(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        yield ""


async def main():
    from praxic.core.cognitive_loop import CognitiveLoop

    settings.max_iterations = 1
    settings.practice_rounds = 1
    settings.web_search_enabled = False
    settings.web_fetch_enabled = False

    fake = UniversalFake()
    loop = CognitiveLoop(llm=fake)
    # Force every phase LLM to the fake
    for attr in ("preprocessor", "investigation", "contradiction", "rational",
                 "practice", "reflection", "perspectives"):
        obj = getattr(loop, attr, None)
        if obj is not None and hasattr(obj, "llm"):
            obj.llm = fake

    skills_before = len(loop.skill_manager._catalog)
    drafts_dir = loop.skill_manager.skills_dir / "drafts"

    phases_seen = []
    def on_phase(phase, summary, data=None):
        phases_seen.append(phase)
        print(f"  PHASE {phase}: {summary[:70]}")

    print("=== Running FULL loop in STANDARD mode (UniversalFake) ===")
    r = await asyncio.wait_for(
        loop.run(question="用Python计算1到100所有质数的和",
                 context="需要可运行的Python代码，自包含、有main、打印结果",
                 mode="standard", on_phase=on_phase, conversation_id="fulltest"),
        timeout=60.0,
    )

    print(f"\n[Results]")
    print(f"  phases seen: {phases_seen}")
    print(f"  LLM call routes: {loop.__dict__.get('_x','')}{fake.routes}")
    t = r.full_trace
    print(f"  practice reached: {t.practice is not None}")
    if t.practice:
        print(f"    practice mode: {t.practice.mode}, steps: {len(t.practice.steps_taken)}")
        print(f"    observed: {t.practice.observed_outcomes[:2]}")
    print(f"  reflection reached: {t.reflection is not None}")
    if t.reflection:
        print(f"    convergence: {t.reflection.convergence_score}")
        print(f"    skill_draft_candidates: {len(t.reflection.skill_draft_candidates)}")
    # Distillation: was a draft created?
    draft_created = drafts_dir.exists() and any(drafts_dir.iterdir())
    print(f"  skill draft auto-distilled: {draft_created}")
    if draft_created:
        print(f"    drafts: {[d.name for d in drafts_dir.iterdir()]}")
    print(f"  final summary: {str(r.summary)[:120]}")

    # cleanup any auto-created draft so we don't pollute the repo
    import shutil
    if drafts_dir.exists():
        shutil.rmtree(drafts_dir, ignore_errors=True)

    ok = (
        t.practice is not None
        and t.reflection is not None
        and "practice" in phases_seen
        and "reflection" in phases_seen
    )
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
