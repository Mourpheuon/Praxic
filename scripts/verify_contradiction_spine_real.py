"""
矛盾主线化改造真实验收（专属脚本，手工运行，依赖真实 LLM）：
验证多轮迭代下，第二轮矛盾分析走 maintain_contradictions 而非 analyze，
并观察 position_shifts / iteration 演化数据。

用法：
    python scripts/verify_contradiction_spine_real.py [--question T] [--max-iter N]

需要真实 API Key（config.toml/.env），会消耗配额、耗时数分钟。
不打印 API Key，不修改源码。
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from praxic.core.cognitive_loop import CognitiveLoop


class ContradictionSpy:
    """包裹真实矛盾分析器，记录每次调用是 analyze 还是 maintain 及其输入特征。"""

    def __init__(self, real):
        self._real = real
        self.analyze_calls = []
        self.maintain_calls = []
        self.results = []

    async def analyze(self, **kw):
        self.analyze_calls.append({"iteration_hint": kw.get("question", "")})
        g = await self._real.analyze(**kw)
        self.results.append({"method": "analyze", "iteration": g.iteration})
        return g

    async def maintain_contradictions(self, **kw):
        prev = kw.get("previous_graph")
        self.maintain_calls.append({
            "prev_iteration": prev.iteration if prev else None,
            "budget": kw.get("budget"),
        })
        g = await self._real.maintain_contradictions(**kw)
        self.results.append({
            "method": "maintain",
            "iteration": g.iteration,
            "n_position_shifts": len(g.position_shifts or []),
        })
        return g


async def run_one(question: str, max_iter: int, mode: str = "standard"):
    loop = CognitiveLoop(web_search_enabled=False)
    spy = ContradictionSpy(loop.contradiction)
    loop.contradiction = spy
    loop.max_iterations = max_iter

    t0 = time.time()
    resp = await loop.run(question=question, mode=mode)
    elapsed = time.time() - t0

    trace = resp.full_trace
    print("\n========== 真实验收结果 ==========")
    print(f"问题: {question[:60]}")
    print(f"模式: {mode}  迭代次数: {trace.metadata.iterations}  耗时: {elapsed:.1f}s")

    print("\n--- 矛盾分析阶段方法调用序列 ---")
    print(f"  analyze 调用次数: {len(spy.analyze_calls)}")
    print(f"  maintain 调用次数: {len(spy.maintain_calls)}")
    for i, r in enumerate(spy.results, 1):
        extra = ""
        if r["method"] == "maintain":
            extra = f"，position_shifts={r['n_position_shifts']}"
        print(f"  第{i}次矛盾分析 -> {r['method']}（iteration={r['iteration']}{extra}）")

    # 第二次矛盾分析是否走 maintain
    m_index = [i for i, r in enumerate(spy.results) if r["method"] == "maintain"]
    print("\n--- 判定 ---")
    if m_index:
        # 检查第一个 maintain 的 prev_iteration
        first_m = spy.maintain_calls[0] if spy.maintain_calls else {}
        prev_iter = first_m.get("prev_iteration")
        print(f"  [PASS] 第二轮矛盾分析走了 maintain_contraditions（在第{m_index[0]+1}次矛盾分析，"
              f"previous_graph.iteration={prev_iter}）")
        latest = spy.results[-1]
        if latest["method"] == "maintain" and latest.get("n_position_shifts", 0) > 0:
            print(f"  [PASS] position_shifts 有数据：{latest['n_position_shifts']} 条地位转换事件被记录")
        else:
            print("  [INFO] position_shifts 本轮无数据（未发生地位转换属正常；演化数据本身已接通）")
    else:
        print("  [FAIL] 未观察到 maintain 调用（多轮迭代未触发第二轮矛盾分析？）")

    # 矛盾图最终状态
    gc = trace.contradictions
    if gc:
        pc = gc.principal_contradiction
        print("\n--- 最终矛盾图状态 ---")
        print(f"  iteration: {gc.iteration}")
        print(f"  principal: {pc.description[:60] if pc else 'None'}")
        print(f"  position_shifts 总数: {len(gc.position_shifts or [])}")
        for ps in (gc.position_shifts or [])[:5]:
            print(f"    - [{ps.from_role}→{ps.to_role}] {ps.contradiction_description[:50]}"
                  f"（第{ps.trigger_iteration}轮，触发:{','.join(ps.trigger_facts[:2])}）")
    return spy


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", type=str,
                    default="用模拟实验检验：零样本电力网络故障定位场景中，误差下降斜率能否区分不同先验结构？")
    ap.add_argument("--max-iter", type=int, default=2, help="最大迭代次数（默认 2）")
    ap.add_argument("--mode", type=str, default="standard", help="运行模式 fast/standard/deep（默认 standard）")
    args = ap.parse_args()
    await run_one(args.question, args.max_iter, args.mode)


if __name__ == "__main__":
    asyncio.run(main())
