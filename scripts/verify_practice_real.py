"""
真实验收脚本（手工运行，依赖真实外部资源）：
用 config.toml 配置的真实 LLM（DeepSeek）跑实践阶段，
统计规划成功率、失败模式、代码运行成功率、方向字段完整性。

用法：
    python scripts/verify_practice_real.py [--rounds 2] [--quiet]

注意：需要真实 API Key（config.toml/.env），会消耗配额，耗时数分钟到数十分钟。
不打印任何 API Key，不修改源码。
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

from praxic.config import settings
from praxic.llm.base import BaseLLM, LLMResponse
from praxic.core.cognitive_loop import CognitiveLoop

PLAN_MARKERS = ("## 总体方向锚点", "epistemic_role", "directional_claim")
CODE_MARKERS = ("为文件", "生成代码")
ANALYSIS_MARKERS = ("综合", "知性")


class RecordingLLM(BaseLLM):
    """包装真实 LLM，记录每次调用的特征，不改变行为。"""

    def __init__(self, inner: BaseLLM):
        self.inner = inner
        self.calls: list[dict] = []

    async def call(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        user = messages[-1]["content"] if messages else ""
        t0 = time.time()
        resp = await self.inner.call(
            messages=messages, system=system, temperature=temperature,
            max_tokens=max_tokens, **kwargs,
        )
        elapsed = time.time() - t0
        sys_text = system or ""
        kind = "other"
        if "总体方向锚点" in sys_text and "tool_calls" in sys_text:
            kind = "plan_r1"
        elif "本轮规划策略" in sys_text:
            kind = "plan_rn"
        elif any(m in user for m in CODE_MARKERS) or "为文件" in user:
            kind = "codegen"
        elif "综合" in user or "分析" in user:
            kind = "analysis"
        elif "phase_budgets" in sys_text:
            kind = "reflection"
        self.calls.append({
            "kind": kind,
            "duration_s": round(elapsed, 1),
            "resp_len": len(resp.content or ""),
            "retry_feedback": "上一次规划被拒绝" in user,
            "resp_head": (resp.content or "")[:120].replace("\n", " "),
            "resp_full": resp.content or "",
        })
        return resp

    async def stream(self, messages, system=None, temperature=0.5, max_tokens=4096, **kwargs):
        async for chunk in self.inner.stream(
            messages=messages, system=system, temperature=temperature,
            max_tokens=max_tokens, **kwargs,
        ):
            yield chunk


QUESTIONS = [
    "用模拟实验检验：零样本电力网络故障定位场景中，误差下降斜率能否区分不同先验结构？",
    "用程序验证：哥德巴赫猜想在 4 到 1000 的偶数范围内是否成立，并报告不成立的例外。",
    "统计 workspace 目录下所有 Python 文件的总行数，并列出最大的 3 个文件。",
]


def summarize_question(idx: int, q: str, loop: CognitiveLoop, rec: RecordingLLM, elapsed: float) -> dict:
    row = {"q": idx + 1, "question": q[:30], "elapsed_s": round(elapsed, 1)}
    trace = loop.trace if getattr(loop, "trace", None) else None
    pr = trace.practice if trace else None

    # 实践报告基础状态
    if pr is None:
        row.update({"mode": "none", "ceiling": "-", "rounds": 0, "executed": False})
    else:
        row.update({
            "mode": pr.mode,
            "ceiling": pr.confidence_ceiling,
            "rounds": len(pr.rounds),
            "executed": pr.mode == "executed",
        })

    # 规划重试与代码生成统计（从 LLM 调用记录）
    plan_calls = [c for c in rec.calls if c["kind"].startswith("plan")]
    codegen_calls = [c for c in rec.calls if c["kind"] == "codegen"]
    row["plan_calls"] = len(plan_calls)
    row["plan_retries"] = sum(1 for c in plan_calls if c["retry_feedback"])
    row["codegen_calls"] = len(codegen_calls)
    row["llm_calls"] = len(rec.calls)

    # 工具调用成功/失败统计
    tool_oks = 0
    tool_fails = 0
    if pr:
        for r in pr.rounds:
            for tc in r.tool_calls:
                status = tc.get("result", {}).get("status", "")
                if status == "success" or tc.get("result", {}).get("ok"):
                    tool_oks += 1
                else:
                    tool_fails += 1
    row["tool_ok"] = tool_oks
    row["tool_fail"] = tool_fails

    # 实践摘要
    row["summary"] = (pr.practice_summary[:120] if pr and pr.practice_summary else "-")
    return row


async def run_one(q: str, practice_rounds: int) -> tuple:
    inner = __import__("praxic.llm", fromlist=["get_llm"]).get_llm()
    rec = RecordingLLM(inner)
    loop = CognitiveLoop(llm=rec, web_search_enabled=False)
    # 减少轮次，控制耗时；强制 single iteration
    loop.practice.practice_rounds = practice_rounds
    loop.max_iterations = 1
    t0 = time.time()
    resp = await loop.run(question=q, mode="standard")
    elapsed = time.time() - t0
    loop.trace = resp.full_trace
    return loop, rec, elapsed


def check_phase_budgets(rec: RecordingLLM) -> dict:
    """从反思阶段原始输出中提取 phase_budgets，供人工检查。"""
    reflections = [c for c in rec.calls if c["kind"] == "reflection"]
    if not reflections:
        return {"found": False, "reason": "未捕获反思阶段调用"}
    raw = reflections[-1]["resp_full"]
    # 剥 code fence
    s = raw.strip()
    while s.startswith("```"):
        idx = s.find("\n")
        s = s[idx + 1:] if idx >= 0 else ""
    if s.endswith("```"):
        s = s[:-3]
    s = s.strip().rstrip("`")
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        # 截取第一个 { 到最后一个 }
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(s[start:end + 1])
            except json.JSONDecodeError:
                return {"found": False, "reason": "反思输出非 JSON", "raw": raw[:800]}
        else:
            return {"found": False, "reason": "反思输出非 JSON", "raw": raw[:800]}
    budgets = data.get("phase_budgets", {}) if isinstance(data, dict) else {}
    return {
        "found": True,
        "budgets": budgets,
        "should_reinvestigate": data.get("should_reinvestigate") if isinstance(data, dict) else None,
        "convergence": data.get("convergence_score") if isinstance(data, dict) else None,
        "raw": raw[:1500],
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2, help="实践阶段最大轮数（默认 2）")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总表")
    args = ap.parse_args()

    print(f"真实 LLM 验收 | provider={settings.llm_provider} model={settings.default_model} "
          f"rounds={args.rounds}\n")

    rows = []
    for i, q in enumerate(QUESTIONS):
        if not args.quiet:
            print(f"── 问题 {i + 1}: {q}")
        try:
            loop, rec, elapsed = await run_one(q, args.rounds)
            row = summarize_question(i, q, loop, rec, elapsed)
            rows.append(row)
            if not args.quiet:
                for k in ("mode", "ceiling", "rounds", "plan_calls", "plan_retries",
                          "codegen_calls", "tool_ok", "tool_fail", "elapsed_s"):
                    print(f"    {k}={row.get(k)}")
                print(f"    摘要: {row['summary']}")
                for c in rec.calls:
                    if c["kind"].startswith("plan") or c["kind"] == "codegen":
                        flag = " [retry]" if c["retry_feedback"] else ""
                        print(f"      {c['kind']}{flag} dur={c['duration_s']}s len={c['resp_len']} "
                              f"head={c['resp_head'][:60]!r}")
            # ── phase_budgets 人工检查（验收标准 5）──
            pb = check_phase_budgets(rec)
            print(f"\n    [反思 phase_budgets] found={pb.get('found')} "
                  f"reinvestigate={pb.get('should_reinvestigate')} "
                  f"convergence={pb.get('convergence')}")
            if pb.get("found") and pb.get("budgets"):
                for phase, b in pb["budgets"].items():
                    print(f"      {phase}: {json.dumps(b, ensure_ascii=False)}")
            elif pb.get("reason"):
                print(f"      ({pb['reason']})")
        except Exception as e:
            print(f"    问题 {i + 1} 执行异常: {type(e).__name__}: {str(e)[:200]}")
            rows.append({"q": i + 1, "error": str(e)[:100]})

    print("\n═══ 汇总 ═══")
    print(f"{'Q':<3}{'mode':<16}{'ceiling':<8}{'rounds':<7}{'planCalls':<10}"
          f"{'retries':<8}{'codegen':<8}{'toolOK':<7}{'toolFAIL':<9}{'llmCalls':<9}{'sec':<6}")
    for r in rows:
        if "error" in r:
            print(f"{r['q']:<3}{'ERROR':<16}{r['error']}")
            continue
        print(f"{r['q']:<3}{r.get('mode','-'):<16}{r.get('ceiling','-'):<8}{r.get('rounds','-'):<7}"
              f"{r.get('plan_calls','-'):<10}{r.get('plan_retries','-'):<8}{r.get('codegen_calls','-'):<8}"
              f"{r.get('tool_ok','-'):<7}{r.get('tool_fail','-'):<9}{r.get('llm_calls','-'):<9}"
              f"{r.get('elapsed_s','-'):<6}")

    # 关键指标
    executed = [r for r in rows if r.get("executed")]
    print(f"\n实践执行成功(executed): {len(executed)}/{len(rows)}")
    total_plan = sum(r.get("plan_calls", 0) for r in rows)
    total_retry = sum(r.get("plan_retries", 0) for r in rows)
    if total_plan:
        print(f"规划调用: {total_plan} 次, 其中重试: {total_retry} 次 "
              f"({round(total_retry / total_plan * 100, 1)}%)")
    tool_ok = sum(r.get("tool_ok", 0) for r in rows)
    tool_fail = sum(r.get("tool_fail", 0) for r in rows)
    print(f"工具调用: 成功 {tool_ok}, 失败 {tool_fail}")


if __name__ == "__main__":
    asyncio.run(main())
