"""Steering functionality test."""
import io, sys, asyncio, os
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
_source_path = os.path.join(_project_root, 'tests', 'test_full_loop_integration.py')
_src = io.open(_source_path, encoding="utf-8").read()
_ns = {"__file__": _source_path}
exec(compile(_src.split("\nasync def main")[0], _source_path, "exec"), _ns)
UF = _ns["UniversalFake"]; settings = _ns["settings"]
settings.max_iterations = 1; settings.practice_rounds = 1
settings.web_search_enabled = False; settings.web_fetch_enabled = False
from praxic.core.cognitive_loop import CognitiveLoop
from praxic.core.loop_controller import get_controller_by_conv

hits = []
class SF(UF):
    async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, **kw):
        if system and "[用户引导]" in system: hits.append(1)
        return await super().call(messages, system=system, temperature=temperature, max_tokens=max_tokens, **kw)

async def main():
    results = {}
    # 1. targeted steer
    hits.clear(); fake = SF(); loop = CognitiveLoop(llm=fake)
    for a in ("preprocessor","preprocessing","investigation","contradiction","rational","practice","reflection","perspectives"):
        o = getattr(loop,a,None)
        if o and hasattr(o,"llm"): o.llm = fake
    CONV="st1"; done=False
    def op1(p,s,d=None):
        nonlocal done
        if not done and "preprocessing" in str(p).lower():
            c=get_controller_by_conv(CONV)
            if c: c.steer("请特别关注性能优化", target_phase="practice"); done=True
    await asyncio.wait_for(loop.run(question="用Python计算1到100所有质数的和", mode="standard", on_phase=op1, conversation_id=CONV), timeout=40.0)
    results["targeted"] = len(hits) > 0
    print(f"  [targeted] steer in LLM: {results['targeted']} (hits={len(hits)})")

    # 2. broadcast steer
    hits.clear(); fake2 = SF(); loop2 = CognitiveLoop(llm=fake2)
    for a in ("preprocessor","preprocessing","investigation","contradiction","rational","practice","reflection","perspectives"):
        o=getattr(loop2,a,None)
        if o and hasattr(o,"llm"): o.llm = fake2
    CONV="st2"; done=False
    def op2(p,s,d=None):
        nonlocal done
        if not done and "preprocessing" in str(p).lower():
            c=get_controller_by_conv(CONV)
            if c: c.steer("广播消息：请注重可读性"); done=True
    await asyncio.wait_for(loop2.run(question="用Python计算1到100所有质数的和", mode="standard", on_phase=op2, conversation_id=CONV), timeout=40.0)
    results["broadcast"] = len(hits) > 0
    print(f"  [broadcast] steer in LLM: {results['broadcast']} (hits={len(hits)})")

    # 3. interrupt + resume
    hits.clear(); fake3 = SF(); loop3 = CognitiveLoop(llm=fake3)
    for a in ("preprocessor","preprocessing","investigation","contradiction","rational","practice","reflection","perspectives"):
        o=getattr(loop3,a,None)
        if o and hasattr(o,"llm"): o.llm = fake3
    CONV="st3"; state={"int":False,"res":False}
    def op3(p,s,d=None):
        c=get_controller_by_conv(CONV)
        if c and not state["int"] and "investigation" in str(p).lower():
            c.interrupt(); state["int"]=True
            async def _rs():
                await asyncio.sleep(0.3)
                c2=get_controller_by_conv(CONV)
                if c2: c2.resume(steer="请继续，关注边界"); state["res"]=True
            asyncio.get_running_loop().create_task(_rs())
    await asyncio.wait_for(loop3.run(question="用Python计算1到100所有质数的和", mode="standard", on_phase=op3, conversation_id=CONV), timeout=40.0)
    results["interrupt"] = state["int"] and state["res"]
    print(f"  [interrupt] int={state['int']} res={state['res']}")

    all_ok = all(results.values())
    print(f"\n{'='*30}")
    for k,v in results.items(): print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    print(f"\nOVERALL: {'PASS' if all_ok else 'FAIL'}")
    return all_ok


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
