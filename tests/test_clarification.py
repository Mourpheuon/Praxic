"""
Regression test for agent-initiated clarification (IMMEDIATE variant):
PREPROCESSING phase emits clarifying_questions -> right after preprocessing,
before investigation, the loop blocks (on_clarification fired) -> user answer
submitted via controller -> answer injected into effective_question so the very
next phase (investigation) already sees it -> loop continues to completion.

Reuses UniversalFake from test_full_loop_integration (exec its setup prefix).
"""
import io, os, sys, asyncio, traceback
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
_source_path = BASE / "tests" / "test_full_loop_integration.py"
_src = io.open(_source_path, encoding="utf-8").read()
_ns = {"__file__": str(_source_path)}
exec(compile(_src.split("\nasync def main")[0], str(_source_path), "exec"), _ns)
UniversalFake = _ns["UniversalFake"]
settings = _ns["settings"]
_SUPERSET = _ns["_SUPERSET"]

# make the PREPROCESSING phase emit clarifying questions (UniversalFake returns
# this superset for every phase; preprocessing parses clarifying_questions from it)
_SUPERSET["clarifying_questions"] = ["你更看重成本还是速度？", "目标运行环境是哪一个？"]

ANSWER = "CLARIFY_ANSWER_PROBE_9x7 我更看重速度，环境是 Linux 服务器"

from praxic.core.cognitive_loop import CognitiveLoop
from praxic.core.loop_controller import get_controller_by_conv

captured = []   # every user-message content sent to the LLM


class RecordingFake(UniversalFake):
    async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, **kw):
        if messages:
            captured.append(messages[-1].get("content", ""))
        return await super().call(messages, system=system, temperature=temperature, max_tokens=max_tokens, **kw)


async def main() -> bool:
    settings.max_iterations = 1
    settings.practice_rounds = 1
    settings.web_search_enabled = False
    settings.web_fetch_enabled = False

    fake = RecordingFake()
    loop = CognitiveLoop(llm=fake)
    for attr in ("preprocessor", "preprocessing", "investigation", "contradiction",
                 "rational", "practice", "reflection", "perspectives"):
        obj = getattr(loop, attr, None)
        if obj is not None and hasattr(obj, "llm"):
            obj.llm = fake

    CONV = "clartest"
    state = {"questions": None, "answered": False, "phases": [], "clar_at_capture": None}

    def on_phase(phase, summary, data=None):
        state["phases"].append(str(phase))

    def on_clar(questions):
        state["questions"] = list(questions or [])
        state["clar_at_capture"] = len(captured)  # how many LLM calls happened BEFORE the ask
        # schedule the user's answer on the event loop (loop is about to block awaiting it)
        def _answer():
            c = get_controller_by_conv(CONV)
            if c is not None:
                c.submit_clarification(ANSWER)
                state["answered"] = True
        asyncio.get_running_loop().call_soon(_answer)

    r = await asyncio.wait_for(
        loop.run(question="用Python计算1到100所有质数的和",
                 context="需要可运行的Python代码",
                 mode="standard", on_phase=on_phase, conversation_id=CONV,
                 on_clarification=on_clar),
        timeout=45.0,
    )

    ok = True
    def check(name, cond):
        nonlocal ok; ok = ok and cond
        print(("  [PASS] " if cond else "  [FAIL] ") + name)

    clar_idx = state["clar_at_capture"] or 0
    after = captured[clar_idx:]

    check("on_clarification 被触发且带问题", bool(state["questions"]) and len(state["questions"]) >= 1)
    check("问题来自预处理阶段(2条)", state["questions"] == ["你更看重成本还是速度？", "目标运行环境是哪一个？"])
    check("答案已通过 controller 提交", state["answered"] is True)
    check("发问发生在尝试阶段(4步管线,预处理刚结束,投研之前)", clar_idx >= 1 and clar_idx <= 5)
    check("答案被注入紧随其后的阶段(投研起即可见)", any(ANSWER in c for c in after))
    check("答案贯穿多个后续阶段", sum(ANSWER in c for c in captured) >= 2)
    check("实践阶段确实到达(未被阻塞卡死)", "practice" in state["phases"])
    check("循环正常完成", r is not None and bool(r.summary))
    print(f"\n  phases: {state['phases']}")
    print(f"  clar_at_capture (LLM calls before ask): {clar_idx}")
    print(f"  captured contents containing answer: {sum(ANSWER in c for c in captured)} / {len(captured)}")
    return ok


if __name__ == "__main__":
    try:
        ok = asyncio.run(main())
        print("\nOVERALL:", "PASS" if ok else "FAIL")
        sys.exit(0 if ok else 1)
    except Exception as e:
        print("\nEXCEPTION:", e)
        traceback.print_exc()
        sys.exit(2)
