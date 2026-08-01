"""
Praxic Agent —— 语义审核器（AUTO_REVIEW 权限模式的第二道审核）。

硬规则（路径边界、沙箱安全、可逆性）通过后直接放行；
硬规则未通过的越界/外部操作，交给本审核器用 LLM 判断是否放行。

审核输入：工具名、行动类型、参数（脱敏截断）、拒绝原因。
审核输出：JSON {"approved": bool, "reason": str}。

注入位置：PermissionPolicy.reviewer（async 回调，签名见 registry.call）。
"""

from __future__ import annotations

import json
from typing import Optional

import structlog

from .autonomy import PermissionMode

log = structlog.get_logger(__name__)

_REVIEW_PROMPT = """\
你是 Praxic 的语义审核器。系统正处于「自动审核」权限模式：变更操作先由硬规则检查，
未通过的越界/外部操作交给你判断是否放行。

## 审核原则
1. 判断这次操作的风险等级与合理性，而不是判断它"是否正确"。
2. 放行条件：操作目标明确、影响可控、属于当前任务合理范围内的外部副作用。
3. 拒绝条件：目标不明、命令危险（破坏性、不可逆）、涉及未声明的外部系统、或理由不充分。
4. 无法判断时倾向拒绝（安全优先），把决定权交回用户。
5. 只输出 JSON，不要多余文字。

## 输入
工具：{tool}
行动类型：{action_kind}
参数：{params}
硬规则拒绝原因：{reason}

## 输出格式（严格 JSON）
{{
  "approved": true,
  "reason": "一句话说明放行或拒绝的理由"
}}
"""


def build_reviewer(llm, max_tokens: int = 256):
    """构造语义审核器回调，绑定到指定 LLM。"""

    async def reviewer(tool_name: str, action_kind, params: dict, reason: str) -> bool:
        try:
            safe_params = {
                str(k): str(v)[:200] for k, v in dict(params).items()
                if not any(s in str(k).lower() for s in ("secret", "token", "password", "key", "authorization", "credential"))
            }
            prompt = _REVIEW_PROMPT.replace("{tool}", tool_name)
            prompt = prompt.replace("{action_kind}", getattr(action_kind, "value", str(action_kind)))
            prompt = prompt.replace("{params}", json.dumps(safe_params, ensure_ascii=False)[:2000])
            prompt = prompt.replace("{reason}", str(reason)[:500])
            resp = await llm.call(
                messages=[{"role": "user", "content": "审核这次操作是否放行。"}],
                system=prompt,
                temperature=0.0,
                max_tokens=max_tokens,
            )
            raw = resp.content.strip()
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1 and end > start:
                raw = raw[start:end + 1]
            data = json.loads(raw)
            approved = bool(data.get("approved", False))
            log.info(
                "reviewer.decision",
                tool=tool_name, approved=approved,
                reason=str(data.get("reason", ""))[:200],
            )
            return approved
        except Exception as exc:
            log.warning("reviewer.error", tool=tool_name, error=str(exc))
            return False

    return reviewer
