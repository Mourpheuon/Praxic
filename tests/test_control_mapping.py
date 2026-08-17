"""
Targeted regression test for the control-signal bug:
  conversation_id -> session_id -> LoopController mapping must be LIVE during a
  run so the /control endpoint (get_controller_by_conv) can reach the running
  loop's controller; and must be released afterwards.

Proves end-to-end that a stop() issued mid-run (as the /control endpoint would)
actually propagates and terminates the loop early.

Reuses UniversalFake from test_full_loop_integration by exec-ing only its
setup prefix (everything before `async def main`) so we don't trigger that
module's bottom sys.exit.
"""
import io, os, sys, asyncio, traceback
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
_src_path = BASE / "tests" / "test_full_loop_integration.py"
_src = io.open(_src_path, encoding="utf-8").read()
_prefix = _src.split("\nasync def main")[0]
_ns: dict = {"__file__": str(_src_path)}
exec(compile(_prefix, str(_src_path), "exec"), _ns)      # sets up env + defines UniversalFake, _SUPERSET
UniversalFake = _ns["UniversalFake"]
settings = _ns["settings"]

from praxic.core.cognitive_loop import CognitiveLoop
from praxic.core.loop_controller import get_controller_by_conv


async def main() -> bool:
    settings.max_iterations = 1
    settings.practice_rounds = 1
    settings.web_search_enabled = False
    settings.web_fetch_enabled = False

    fake = UniversalFake()
    loop = CognitiveLoop(llm=fake)
    for attr in ("preprocessor", "investigation", "contradiction", "rational",
                 "practice", "reflection"):
        obj = getattr(loop, attr, None)
        if obj is not None and hasattr(obj, "llm"):
            obj.llm = fake

    CONV = "ctlmap_regression"
    state = {"resolved_ok": False, "stopped": False, "phases": []}

    # BEFORE the run there must be NO mapping (clean slate)
    pre = get_controller_by_conv(CONV)
    print(f"  before run: get_controller_by_conv -> {pre!r}")

    def on_phase(phase, summary, data=None):
        state["phases"].append(str(phase))
        if not state["stopped"]:
            # Simulate the /control endpoint: look up the live controller by conv_id
            c = get_controller_by_conv(CONV)
            if c is not None:
                state["resolved_ok"] = True
                c.stop()                     # user clicked 「终止」
                state["stopped"] = True
                print(f"  [on_phase={phase}] mapping LIVE -> issued stop()")

    r = await asyncio.wait_for(
        loop.run(question="用Python计算1到100所有质数的和",
                 context="需要可运行的Python代码",
                 mode="standard", on_phase=on_phase, conversation_id=CONV),
        timeout=40.0,
    )

    post = get_controller_by_conv(CONV)
    print(f"  phases seen: {state['phases']}")
    print(f"  after run: get_controller_by_conv -> {post!r}")

    checks = {
        "pre-run mapping empty":         pre is None,
        "mapping LIVE during run":       state["resolved_ok"] is True,
        "stop propagated (no reflection)": "reflection" not in state["phases"]
                                           and "CognitivePhaseName.REFLECTION" not in state["phases"],
        "mapping released after run":    post is None,
    }
    for name, ok in checks.items():
        print(f"    [{'PASS' if ok else 'FAIL'}] {name}")
    return all(checks.values())


if __name__ == "__main__":
    try:
        ok = asyncio.run(main())
        print(f"\nOVERALL: {'PASS' if ok else 'FAIL'}")
        sys.exit(0 if ok else 1)
    except Exception as e:
        print(f"\nEXCEPTION: {e}")
        traceback.print_exc()
        sys.exit(2)
