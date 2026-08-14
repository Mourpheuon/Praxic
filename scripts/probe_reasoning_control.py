"""探针：验证 DeepSeek v4-pro 是否真正响应 reasoning_effort / enable_reasoning 控制。

直接调 openai SDK，拿原始响应里的 reasoning_content 长度，最可靠。
对比四种调用方式在同一问题下的行为：
  A. 无控制（基线）
  B. reasoning_effort="low"
  C. reasoning_effort="high"
  D. enable_reasoning=False（extra_body）
  E. max_tokens=64（小预算，验证 finish_reason=length 时 content 是否被 reasoning 挤空）

观测：reasoning_content 长度、content 长度、finish_reason、耗时。
"""
import asyncio, time, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from praxic.config import settings
from openai import AsyncOpenAI

QUESTION = "分析：零样本电力网络故障定位中，误差下降斜率能否区分不同先验结构？请给出简短推理。"


async def probe(label: str, extra: dict | None = None, max_tokens: int = 2048):
    client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url, timeout=120.0)
    params = {
        "model": settings.default_model,
        "messages": [{"role": "user", "content": QUESTION}],
        "temperature": 0.4,
        "max_tokens": max_tokens,
    }
    if extra:
        params.update(extra)
    t0 = time.time()
    try:
        resp = await client.chat.completions.create(**params)
        elapsed = time.time() - t0
        msg = resp.choices[0].message
        reasoning = getattr(msg, "reasoning_content", None) or ""
        content = msg.content or ""
        print(f"[{label}] dur={elapsed:.1f}s reasoning_len={len(reasoning)} "
              f"content_len={len(content)} finish={resp.choices[0].finish_reason} "
              f"out_tokens={resp.usage.completion_tokens if resp.usage else '?'}")
        return {
            "label": label, "dur": round(elapsed, 1),
            "reasoning_len": len(reasoning), "content_len": len(content),
            "finish": resp.choices[0].finish_reason,
            "out_tokens": resp.usage.completion_tokens if resp.usage else 0,
        }
    except Exception as e:
        print(f"[{label}] ERROR: {type(e).__name__}: {str(e)[:300]}")
        return {"label": label, "error": str(e)[:200]}


async def main():
    print(f"provider={settings.llm_provider} model={settings.default_model}\n")
    results = []
    results.append(await probe("A 无控制"))
    results.append(await probe("B low", {"reasoning_effort": "low"}))
    results.append(await probe("C high", {"reasoning_effort": "high"}))
    results.append(await probe("D enable_reasoning=False", {"extra_body": {"enable_reasoning": False}}))
    results.append(await probe("E max_tokens=64", {}, max_tokens=64))

    print("\n=== 对比（vs 基线 A）===")
    base = results[0]
    for r in results[1:]:
        if "error" in r:
            print(f"{r['label']}: ERROR {r['error']}")
            continue
        print(f"{r['label']}: reasoning_len={r['reasoning_len']} (基线{base['reasoning_len']}) "
              f"| content_len={r['content_len']} (基线{base['content_len']}) "
              f"| finish={r['finish']} | dur={r['dur']}s")

    print("\n=== 判定 ===")
    for r in results[1:]:
        if "error" in r:
            continue
        if r["reasoning_len"] >= base["reasoning_len"] * 0.8 and base["reasoning_len"] > 0:
            verdict = "参数无效：reasoning 长度几乎不变"
        elif base["reasoning_len"] > 0 and r["reasoning_len"] < base["reasoning_len"] * 0.3:
            verdict = "参数生效：reasoning 显著减少"
        else:
            verdict = "无法判定（基线 reasoning 为 0 或数据异常）"
        print(f"{r['label']}: {verdict}")


if __name__ == "__main__":
    asyncio.run(main())
