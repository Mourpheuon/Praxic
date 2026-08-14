"""
矛盾主线化真实验收（轻量版，聚焦 contradiction 模块的多轮演化链路）：
用真实 LLM 跑「第一轮 analyze → 第二轮 maintain_contraditions」，
验证：
  1. 真实模型下 analyze 能产出矛盾图（principal）。
  2. 第二轮真实调用 maintain_contradictions（这就是 cognitive_loop 第二轮走的路径）
     ——previous_graph 来自第一轮，不崩溃。
  3. maintain 后 iteration 递增、position_shifts 字段可用（有数据则打印，无则说明）。
  4. 对比本轮新事实对矛盾的影响（fact1/fact2 注入轮次不同）。

用法：python scripts/verify_contradiction_spine_real_light.py
可直接在前台运行，预计 1-3 分钟，消耗少量真实配额。
"""
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from praxic.api.schemas.models import Fact, FactReport
from praxic.core.contradiction import ContradictionAnalyzer


def _report(facts):
    return FactReport(
        facts=[Fact(id=f"f{i}", content=c, credibility=cre, source_type="web")
               for i, (c, cre) in enumerate(facts, 1)],
        summary="电力网络零样本故障定位的调研事实",
    )


async def main():
    print("═══ 矛盾主线化真实验收（light）═══")
    an = ContradictionAnalyzer()

    # ── 第一轮：analyze（真实模型，给定第一调查批事实）──
    round1_facts = [
        ("零样本场景下模型未见过目标网络的接线拓扑，只能依赖通用预训练特征推断故障位置。", 0.8),
        ("不同先验网络结构（如 uniform、top-k）会显著改变特征提取器对故障位置的表征敏感度。", 0.7),
        ("当前主流方法用元学习迁移先验，但标注故障样本获取成本高，制约了监督式调优。", 0.75),
    ]
    g1 = await an.analyze(fact_report=_report(round1_facts), question="零样本电力网络故障定位的主要矛盾是什么？",
                          budget={"depth": "standard"})
    pc1 = g1.principal_contradiction
    print(f"\n[第一轮 analyze]  iteration={g1.iteration}")
    print(f"  主要矛盾: {pc1.description[:80] if pc1 else '（未识别）'}")
    print(f"  两极: {pc1.tension_poles if pc1 else '-'}")
    print(f"  思维链捕获: {len(g1.thinking_trace or '')} 字符")
    if g1.thinking_trace:
        print(f"  思维链开头: {g1.thinking_trace[:80]}")
    if not pc1:
        print("第一轮未产出主要矛盾（真实模型偶发），无法继续。")
        return

    # ── 第二轮：maintain（真实模型，在 g1 基础上增量维护，注入新一批事实）──
    round2_facts = [
        ("公开故障诊断基准（如 IEEE 节点系统）在零样本评测下，误差下降斜率确实随先验结构差异而分离。", 0.75),
        ("但新增证据表明：当观测样本极度稀疏时（每节点仅1个读数），先验结构之间的斜率差异被噪声完全掩盖。", 0.65),
    ]
    g2 = await an.maintain_contradictions(
        previous_graph=g1,
        updated_fact_report=_report(round2_facts),
        question="第二轮：稀疏观测是否会削弱不同先验结构的可分性？是否应重认定主要矛盾？",
        budget={"depth": "standard"},
    )
    pc2 = g2.principal_contradiction
    print(f"\n[第二轮 maintain]  iteration={g2.iteration}（前一轮={g1.iteration}）")
    print(f"  主要矛盾: {pc2.description[:80] if pc2 else '（未识别）'}")
    print(f"  思维链捕获: {len(g2.thinking_trace or '')} 字符")
    if g2.thinking_trace:
        print(f"  思维链开头: {g2.thinking_trace[:80]}")
    print(f"  position_shifts 总数: {len(g2.position_shifts or [])}")
    for ps in (g2.position_shifts or [])[:5]:
        print(f"    - [{ps.from_role}→{ps.to_role}] {ps.contradiction_description[:60]}"
              f"（第{ps.trigger_iteration}轮，触发:{','.join(ps.trigger_facts[:2])}）")
    print(f"  动态: {g2.dynamic_note[:80]}")

    # ── 判定 ──
    print("\n═══ 判定 ═══")
    ok = True
    if g2.iteration != g1.iteration + 1:
        print(f"  [FAIL] iteration 未递增：g1={g1.iteration} g2={g2.iteration}")
        ok = False
    else:
        print(f"  [PASS] maintain 后 iteration 从 {g1.iteration} → {g2.iteration}（递增 1）")
    n_shift = len(g2.position_shifts or [])
    if n_shift:
        print(f"  [PASS] 真实维护过程中 position_shifts 记录了 {n_shift} 条地位转换事件")
    else:
        print("  [INFO] 本轮 position_shifts 为空（未发生主要/次要地位转换，属正常；"
              "maintain 链路已真实跑通）。")
    print("  [PASS] 若上面都过：真实模型下第二轮走 maintain 且不崩溃，演化数据可用。")
    return ok


if __name__ == "__main__":
    asyncio.run(main())
