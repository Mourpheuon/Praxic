"""
Praxic Agent —— 调查研究模块（增强版）
核心原则：没有调查就没有发言权。
支持：联网搜索（Tavily）、文件读取（workspace）、多轮信息收集。
改进一：解剖麻雀 —— 识别典型案例进行纵深分析。
"""
from __future__ import annotations

import json
from typing import Optional, Tuple

import structlog

from ..api.schemas.models import Fact, FactReport, InformationGap, IllustrativeCase
from ..config import PhaseConfig, load_phase_prompt, settings
from ..llm.base import BaseLLM
from ..llm import get_llm as _get_default_llm
from ..tools.filesystem import WorkspaceToolkit
from ..tools.web_search import WebSearchTool, MultiSearchTool
from ..tools.web_fetch import WebFetchTool
from ..tools.local_retriever import LocalRetriever

log = structlog.get_logger(__name__)

_CREDIBILITY_MAP = {
    "高": 0.9, "high": 0.9,
    "中": 0.5, "中等": 0.5, "medium": 0.5,
    "低": 0.2, "low": 0.2,
}

def _safe_credibility(raw) -> float:
    if raw is None:
        return 0.5
    if isinstance(raw, (int, float)):
        return max(0.0, min(1.0, float(raw)))
    s = str(raw).strip().lower()
    if s in _CREDIBILITY_MAP:
        return _CREDIBILITY_MAP[s]
    try:
        return max(0.0, min(1.0, float(s)))
    except ValueError:
        pass
    for k, v in _CREDIBILITY_MAP.items():
        if k in s:
            return v
    return 0.5

_INVESTIGATION_PROMPT = """
你正在研究用户提出的问题，当前正处于【调查研究】阶段。
核心信条：没有调查就没有发言权。

## 你的任务
基于下方给出的"外部收集信息"（可能来自网络搜索、文件读取等）以及用户提出的结构化问题，
完成以下工作：

1. 从所有信息中提取和整理"已知事实"
2. 评估每个事实的可信度（0.0~1.0 的数字，越大越可信）
3. 识别仍然存在的信息缺口——还需要知道什么
4. 为每个缺口建议具体的搜索词或文件路径
5. 提供一段调查摘要，概述关键发现和剩余缺口

## 第一要务：核实用户口述的事实与因果
用户的问题、背景、所给资料、所举例子里，往往夹带着被当作"事实"的主张。
若下方"背景上下文"列出了"待核实的预设"，这些就是本轮调查的重点核查对象。
- 对每一条用户主张，证伪与证实并重：先问"它是真的吗"，而不是默认它成立再往下推导
- 核实方法：优先多信息源交叉比对（不同来源/渠道能否相互印证，还是彼此矛盾），辅以逻辑分析（内部是否自洽、因果是否成立、有无以偏概全或样本偏差）；单一来源不足以定论
- 用户口述或上传的资料同样要核对，不能因为出自用户就当作可信来源——其 credibility 不应默认高于中等（≤0.5），除非有独立证据支持
- 若某条预设与可靠事实相悖，明确指出，并作为一条 credibility 较高的"纠偏事实"写入 facts（source_type 视依据记为 internal 或 web）
- 若既无法证实也无法证伪，写入 gaps，标明还需要什么证据
把"用户的主张"和"客观事实"分开——这正是"没有调查就没有发言权"的题中之义。

## 同等重要：不要只查用户点名的对象
用户常把问题框成有限的几方，但背景上下文若列出"被用户框架遗漏、需一并考察的力量/因素"，
你必须主动为这些力量收集事实与证据、评估其真实作用，而不是只围绕用户点名的对象打转——
真正的动力往往在用户没提到的地方。若现有信息不足以判断某方力量的作用，把"需要调查该力量的作用"作为 high 优先级写入 gaps。

## 第二步：解剖麻雀

从上面提取的事实中，识别一个能够浓缩全局矛盾的"麻雀"——
一个典型现象、事件、或案例，它虽然是个别的，但在这个个别中集中体现了整体的矛盾和运动。

选择标准：
- 这个案例是否承载了问题的核心矛盾？
- 这个案例是否足够"五脏俱全"——包含问题的各个主要方面？
- 分析这个案例，是否能让我们不再需要分析同类的所有案例？

对你选中的典型做纵深分析：
1. 描述案例本身
2. 论证为什么它是典型的——它如何浓缩了这个问题中的普遍矛盾？
3. 深入分析这个案例——它揭示了什么在表面上不可见的本质关系？
4. 从这个案例中，可以总结出什么具有更广泛适用性的认识？
5. 这个案例中暴露了哪些矛盾？

注意：用户问题已经过预处理和结构化扩展，包含子问题分解、矛盾分析，以及一份"待核实的预设"清单。
你无需重复预处理已做的意图揣度与结构化拆分；但结构化不等于已证实——清单中的每条预设都必须核实真伪，切勿默认其成立。

## 输出格式（严格 JSON，不要添加任何 Markdown 代码块标记）
{
  "facts": [
    {
      "id": "f1",
      "content": "事实陈述",
      "source_type": "web|file|internal|user_input",
      "credibility": 0.85,
      "related_to": []
    }
  ],
  "gaps": [
    {
      "description": "缺口描述",
      "importance": "high|medium|low",
      "suggested_query": "建议搜索词（用于下一轮网络搜索）"
    }
  ],
  "summary": "调查摘要，先概述外部信息收集情况，再总结关键发现和剩余缺口，200字以内",
  "illustrative_case": {
    "name": "案例名称",
    "description": "案例描述，200字以内",
    "why_typical": "为什么这个案例是典型的？它如何浓缩全局矛盾？200字",
    "deep_analysis": "纵深分析：这个案例揭示了什么本质关系？300-500字",
    "contradictions_revealed": ["案例中暴露的矛盾1", "矛盾2"],
    "key_facts": ["f3", "f7"],
    "lessons_generalizable": "从这个案例中可以推广的认识"
  }
}

请只输出 JSON 对象，不要任何其他文字。
"""

_SEARCH_QUERY_PROMPT = """
你正在为调查研究阶段制定搜索策略。请根据用户问题和当前已知上下文，生成最有效的搜索查询。

规则：
- 生成 3 个搜索查询
- 每个查询应该聚焦一个特定角度，避免重复
- 优先搜索事实性、可验证的信息
- 查询用中文或英文，选择更可能搜到准确结果的语言
- 若问题涉及最新动态，加上"2025"或"2026"等年份限定
- 若背景中提到"被用户框架遗漏的力量/因素"或"待核实的预设"，至少用一个查询去覆盖它们，不要只搜索用户点名的对象

输出格式（严格 JSON，只输出 JSON）：
{{
  "queries": ["查询1", "查询2", ...]
}}
"""


class InvestigationModule:
    """调查研究模块 —— 没有调查就没有发言权"""

    def __init__(
        self,
        llm: Optional[BaseLLM] = None,
        phase_config: Optional[PhaseConfig] = None,
        web_search_enabled: Optional[bool] = None,
        workspace: Optional[WorkspaceToolkit] = None,
    ):
        self.llm = llm or _get_default_llm()
        self.config = phase_config or PhaseConfig()
        self.workspace = workspace

        _web_enabled = (
            web_search_enabled if web_search_enabled is not None
            else settings.web_search_enabled
        )

        self._web_search: Optional[WebSearchTool] = None
        self._multi_search: Optional[MultiSearchTool] = None
        if settings.tavily_api_key and _web_enabled:
            self._web_search = WebSearchTool(
                api_key=settings.tavily_api_key,
                max_results=settings.web_search_max_results,
            )
            self._multi_search = MultiSearchTool(self._web_search)
            log.info("investigation.web_search_enabled",
                     max_results=settings.web_search_max_results)
        else:
            log.info("investigation.web_search_disabled",
                     reason="no_api_key" if not settings.tavily_api_key
                     else "disabled_by_config")

        self._web_fetch: Optional[WebFetchTool] = (
            WebFetchTool() if (_web_enabled and settings.web_fetch_enabled) else None
        )
        self._local_retriever: Optional[LocalRetriever] = LocalRetriever(settings.workspace_dir)

        if self.workspace:
            log.info("investigation.workspace_enabled",
                     path=str(self.workspace.workspace))

    @property
    def can_search_web(self) -> bool:
        return self._web_search is not None and self._web_search.enabled

    async def investigate(
        self,
        question: str,
        additional_context: str = "",
        tools_results: str = "",
        on_progress: callable = None,
        steering_checkpoint: callable = None,
    ) -> FactReport:
        def _notify(tool: str, summary: str, result: dict | None = None) -> None:
            if not on_progress:
                return
            payload = {
                "event_type": "tool_call",
                "tool": tool,
                "record": {
                    "tool": tool,
                    "result": result or {"status": "running", "content": summary},
                },
            }
            try:
                on_progress(tool, summary, payload)
            except Exception:
                log.warning("investigation.progress_callback_error", exc_info=True)

        async def _checkpoint(tool: str) -> str:
            if not steering_checkpoint:
                return ""
            try:
                return str(await steering_checkpoint(tool) or "")
            except Exception:
                log.warning("investigation.steering_checkpoint_error", tool=tool, exc_info=True)
                return ""

        log.info("investigation.start", question=question[:80],
                 has_search=self.can_search_web,
                 has_context=bool(additional_context))

        all_external_info = ""

        if tools_results:
            all_external_info += f"\n## 已有工具结果\n{tools_results}"

        # 本地文件检索（替代旧的 _read_workspace_files）
        if self.workspace and self._local_retriever:
            if settings.local_retrieval_mode != "off":
                file_contents = await self._local_retriever.retrieve(question)
                if file_contents:
                    all_external_info += f"\n## 工作区文件内容\n{file_contents}"
            else:
                file_contents = await self._read_workspace_files(question)
                if file_contents:
                    all_external_info += f"\n## 工作区文件内容\n{file_contents}"

        # 网络搜索 + 网页全文抓取
        if self.can_search_web:
            _notify("web_search", "WEB_SEARCH · 进行中")
            search_results_text, search_results = await self._do_web_search(question, additional_context, "")
            _notify(
                "web_search",
                "WEB_SEARCH · 已完成",
                {
                    "status": "success" if search_results_text else "error",
                    "content": search_results_text[:500] if search_results_text else "未获得搜索结果",
                    "n_results": len(search_results),
                },
            )
            steering = await _checkpoint("web_search")
            if steering:
                additional_context += "\n" + steering
            if search_results_text:
                all_external_info += f"\n## 网络搜索结果\n{search_results_text}"
            if self._web_fetch and search_results:
                url_score_pairs = []
                seen_urls = set()
                for sr in search_results:
                    if not sr.ok or not sr.data:
                        continue
                    for item in sr.data.get("results", []):
                        url = item.get("url", "")
                        score = float(item.get("score", 0))
                        if score >= settings.web_fetch_min_score and url and url not in seen_urls:
                            url_score_pairs.append((url, score))
                            seen_urls.add(url)
                if url_score_pairs:
                    _notify("web_fetch", "WEB_FETCH · 进行中", {"status": "running", "n_urls": len(url_score_pairs)})
                    fetched = await self._web_fetch.fetch_urls(url_score_pairs)
                    _notify(
                        "web_fetch",
                        "WEB_FETCH · 已完成",
                        {
                            "status": "success" if fetched else "error",
                            "n_urls": len(url_score_pairs),
                            "n_fetched": len(fetched),
                        },
                    )
                    steering = await _checkpoint("web_fetch")
                    if steering:
                        additional_context += "\n" + steering
                    full_text = WebFetchTool.format_for_llm(fetched)
                    if full_text:
                        all_external_info += f"\n## 网页全文\n{full_text}"

        system = load_phase_prompt("investigation", _INVESTIGATION_PROMPT)
        try:
            from .autonomy import get_autonomy_instruction, should_skip_external_search
            sys_instr = get_autonomy_instruction(settings.autonomy_level, "investigation")
            system = system + "\n" + sys_instr
            if should_skip_external_search(settings.autonomy_level) and not all_external_info:
                log.info("investigation.autonomous_mode", "跳过外部搜索（ELEVATED 模式）")
        except ImportError:
            pass
        temperature = getattr(self.config, "temperature", 0.7)
        max_tokens = getattr(self.config, "max_tokens", 8192)

        user_content = f"## 用户问题\n{question}"
        if additional_context:
            user_content += f"\n\n## 背景上下文\n{additional_context}"
        if all_external_info:
            user_content += f"\n\n## 外部收集信息\n{all_external_info[:settings.investigation_external_info_max_chars]}"
        else:
            user_content += (
                "\n\n（本次调查未收集到外部信息，请基于问题本身进行分析，"
                "并在 gaps 中标注需要搜索的方向。）"
            )

        response = await self.llm.call(
            messages=[{"role": "user", "content": user_content}],
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        report = self._parse_response(response.content, question)

        high_gaps = [g for g in report.gaps if g.importance == "high"]
        if high_gaps and self.can_search_web and not tools_results:
            log.info("investigation.second_pass", n_high_gaps=len(high_gaps))
            gap_queries = [g.suggested_query for g in high_gaps if g.suggested_query]
            if gap_queries:
                _notify("web_search", "WEB_SEARCH · 补充检索中", {"status": "running", "queries": gap_queries[:3]})
                second_results = await self._multi_search.search_all(gap_queries[:3])
                combined = "\n\n".join(
                    WebSearchTool.format_for_llm(r) for r in second_results if r.ok
                )
                _notify(
                    "web_search",
                    "WEB_SEARCH · 补充检索完成",
                    {"status": "success" if combined else "error", "n_results": len(second_results)},
                )
                steering = await _checkpoint("web_search")
                if steering:
                    additional_context += "\n" + steering
                if combined:
                    user_content2 = (
                        f"## 用户问题\n{question}\n\n"
                        f"## 第一轮调查结果\n{all_external_info[:settings.investigation_external_info_max_chars // 2]}\n\n"
                        f"## 补充搜索\n{combined[:3000]}"
                    )
                    response2 = await self.llm.call(
                        messages=[{"role": "user", "content": user_content2}],
                        system=system,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    report = self._parse_response(response2.content, question)

        log.info("investigation.done", n_facts=len(report.facts),
                 n_gaps=len(report.gaps),
                 has_illustrative=report.illustrative_case is not None)
        return report

    async def _do_web_search(self, question: str, context: str, gaps_text: str) -> tuple[str, list]:
        try:
            query_resp = await self.llm.call(
                messages=[{
                    "role": "user",
                    "content": f"用户问题：{question}\n背景：{context or '无'}\n\n请生成最多3个搜索查询。",
                }],
                system=_SEARCH_QUERY_PROMPT,
                temperature=0.5,
                max_tokens=1024,
            )

            queries = self._parse_queries(query_resp.content)
            if not queries:
                queries = [question]

            log.info("investigation.search_queries", queries=queries)

            results = await self._multi_search.search_all(queries)

            parts = []
            for q, r in zip(queries, results):
                if r.ok:
                    parts.append(f"### 搜索：{q}\n{r.content[:800]}")
                else:
                    log.warning("investigation.search_failed", query=q[:50], error=r.error)

            return "\n\n".join(parts), results

        except Exception as e:
            log.error("investigation.web_search_error", error=str(e))
            return "", []

    async def _read_workspace_files(self, question: str) -> str:
        try:
            if not self.workspace:
                return ""

            list_result = await self.workspace.list.run(path=".")
            if not list_result.ok:
                return ""

            text_exts = (
                ".txt", ".md", ".py", ".json", ".csv", ".toml",
                ".yaml", ".yml", ".html", ".css", ".js", ".ts",
                ".log", ".cfg", ".ini", ".xml",
            )
            lines = list_result.content.split("\n")
            text_files = []
            for line in lines:
                if "[FILE]" in line:
                    fname = line.split("[FILE]")[-1].strip().split(" ")[0]
                    if fname and any(fname.endswith(ext) for ext in text_exts):
                        try:
                            result = await self.workspace.read.run(path=fname)
                            if result.ok and len(result.content) < 50000:
                                text_files.append(f"### 文件：{fname}\n{result.content[:settings.investigation_legacy_per_file_max_chars]}")
                        except Exception:
                            pass

            if text_files:
                log.info("investigation.workspace_files_read", n_files=len(text_files))
                return "\n\n".join(text_files)

            return ""
        except Exception as e:
            log.warning("investigation.workspace_read_error", error=str(e))
            return ""

    def _parse_queries(self, raw: str) -> list[str]:
        raw = raw.strip()
        while raw.startswith("```"):
            idx = raw.find("\n")
            if idx < 0:
                raw = ""
                break
            raw = raw[idx+1:]
            if raw.endswith("```"):
                raw = raw[:-3]
        raw = raw.strip().rstrip("`")
        try:
            data = json.loads(raw)
            return data.get("queries", [])
        except json.JSONDecodeError:
            import re
            found = re.findall(r'"([^"]{5,200})"', raw)
            if found:
                log.info("investigation.fallback_query_extraction", n=len(found))
                return found[:3]
            log.warning("investigation.query_parse_error", raw=raw[:100])
            return []

    def _parse_response(self, raw: str, question: str) -> FactReport:
        raw_original = raw
        raw = raw.strip()

        while raw.startswith("```"):
            idx = raw.find("\n")
            if idx < 0:
                raw = ""
                break
            raw = raw[idx+1:]
            if raw.endswith("```"):
                raw = raw[:-3]
        raw = raw.strip().rstrip("`")

        log.debug("investigation.parse_raw",
                  orig_len=len(raw_original),
                  parsed_len=len(raw))

        data = None
        errors = []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e1:
            errors.append(f"direct: {e1}")

        if data is None:
            for suffix in ["}]}", "]}]}", "}]}]}", "\n]\n}", "]}\n}", "}\n}"]:
                try:
                    data = json.loads(raw + suffix)
                    log.info("investigation.repaired_truncated_json", suffix=repr(suffix))
                    break
                except json.JSONDecodeError:
                    continue

        if data is not None and isinstance(data, dict):
            facts_list = data.get("facts", [])
            if not facts_list:
                for wrapper_key in ("fact_report", "report", "result", "investigation"):
                    inner = data.get(wrapper_key)
                    if isinstance(inner, dict) and inner.get("facts"):
                        log.info("investigation.unwrapped_key", key=wrapper_key,
                                 n_facts=len(inner.get("facts", [])))
                        data = inner
                        break

        if data is None:
            log.warning("investigation.parse_error",
                        raw_first=raw_original[:300],
                        raw_end=raw_original[-200:],
                        errors=errors)
            return FactReport(
                facts=[Fact(
                    id="f1",
                    content=raw_original[:500],
                    source_type="internal",
                    credibility=0.5,
                )],
                gaps=[InformationGap(
                    description="无法解析结构化调查结果，需要重新调查",
                    importance="high",
                )],
                summary="调查结果解析失败，建议重试",
                raw_context=raw_original,
            )

        # 改进一：解析 illustrative_case
        illustrative_case = None
        ic_data = data.get("illustrative_case")
        if ic_data and isinstance(ic_data, dict):
            illustrative_case = IllustrativeCase(
                name=ic_data.get("name", ""),
                description=ic_data.get("description", ""),
                why_typical=ic_data.get("why_typical", ""),
                deep_analysis=ic_data.get("deep_analysis", ""),
                contradictions_revealed=ic_data.get("contradictions_revealed", []),
                key_facts=ic_data.get("key_facts", []),
                lessons_generalizable=ic_data.get("lessons_generalizable", ""),
            )

        # 改进一：标记典型案例中的关键事实
        case_key_facts = set(ic_data.get("key_facts", [])) if ic_data else set()
        case_name = ic_data.get("name", "") if ic_data else ""

        facts = []
        for i, f in enumerate(data.get("facts", [])):
            if isinstance(f, dict):
                fid = f.get("id", f"f{i+1}")
                facts.append(Fact(
                    id=fid,
                    content=f.get("content", "") or f.get("statement", ""),
                    source_type=f.get("source_type", "internal"),
                    credibility=_safe_credibility(f.get("credibility", 0.5)),
                    related_to=f.get("related_to", []),
                    is_illustrative_case=(fid in case_key_facts),
                    case_name=case_name if fid in case_key_facts else "",
                ))

        gaps = []
        for g in data.get("gaps", []) + data.get("information_gaps", []):
            if isinstance(g, dict):
                gaps.append(InformationGap(
                    description=g.get("description", ""),
                    importance=g.get("importance", "medium"),
                    suggested_query=g.get("suggested_query", ""),
                ))

        summary = data.get("summary", "")

        return FactReport(
            facts=facts,
            gaps=gaps,
            summary=summary,
            raw_context=raw_original,
            illustrative_case=illustrative_case,
        )
