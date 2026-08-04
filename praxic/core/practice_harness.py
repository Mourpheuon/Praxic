"""
Praxic Agent —— 实践阶段 Harness Prompts
专用于：实验规划、代码生成规范、错误修复策略、边界验证任务生成。
这些 prompts 定义的是"怎么做工程执行"——迭代频率高，独立存放。

修改这些提示词时，牢记实践阶段的三层目标：
1. 生成的代码**能跑**（语法正确、环境兼容、编码正确）
2. 跑出来的结果**能被分析层读懂**（JSON 结构化输出）
3. 失败时**能给出可操作的信号**（明确的错误信息，非纯文本日志）
"""

# ═══════════════════════════════════════════════════════════
# 首轮实验规划
# ═══════════════════════════════════════════════════════════

# 系统未注入 ToolRegistry 时的工具清单兜底（B1：registry.format_for_prompt() 优先）。
DEFAULT_TOOLS = """## 可用工具（默认兜底清单）

### python_exec
执行 Python 代码片段
参数：
  - code_ref（代码意图描述，由执行前代码生成器补齐为实际代码）
  - timeout_seconds (默认=30)
  - requirements

### web_search
搜索网络信息。参数：
  - query

### web_fetch
获取指定 URL 页面内容。参数：
  - url

### file_read
读取工作区文件。参数：
  - path

### file_write
写入工作区文件。参数：
  - path
  - content

### read_user_context
申请查看用户补充背景文本。参数：
  - reason
"""

R1_PLAN = """
你已经有了前序阶段的全部认知产出——调查事实、矛盾分析、理性认识（本质和假设）。
现在由你同时负责提出检验行动并检验前序认识。

## 总体方向锚点（所有实验必须服务于以下核心论断）
{direction_anchor}
每项实验设计都必须能追溯到这个锚点中的某条假设或矛盾。
如果本轮工作偏离锚点，必须在 deviation_rationale 中显式说明理由；
无偏离则 deviation_rationale 填空字符串。

## 核心任务

从前序产出中提炼出 2-4 个**可检验的论断**（必须是可证伪的：如果为真应该观察到X，如果为假应该观察到Y）。
然后设计多轮实验来检验这些论断。

## 可用工具

以下工具清单由系统动态生成，以它为准，不要使用清单之外的工具：
{tools_text}

## 实验策略

每一轮实验都是认识链条上的一环，不是孤立地跑代码。规划前先明确本轮的认识论定位：

1. **先定位，再设计**：本轮是
   - exploration（搜集感性材料）：认识尚未成形，实验广撒网，获取直接经验
   - verification（检验理性认识）：已有明确假设，实验必须能区分真伪（可证伪设计）
   - revision（修正认识）：证据动摇了旧认识，本轮聚焦反例，目标是找出新规律
   在 epistemic_role 字段中写明，并让实验设计与定位匹配。

2. **抓主要矛盾**：与方向锚点中主要矛盾直接相关的论断优先检验。
   次要矛盾上的意外发现记入 unexpected，但不轻易改写实验主线；
   只有证据直接击中主要矛盾本身时，才允许通过 deviation_rationale 转向。

3. **区分技术失败与证伪**：工具报错、代码异常是实践的中断，不是认识的否定。
   只有获得有效观测数据后，才能对论断下支持/动摇/证伪的判定。

4. **从现象上升到认识**：每个实验结果必须回答"它使我对锚点论断的认识发生了什么变化"，
   不能停留在"执行了、得到了这些数值"。数据是感性材料，对论断的判定才是理性认识。

## 前序认知产出

### 原始问题
{question}

### 调查发现
{facts_text}

### 信息缺口
{gaps_text}

### 主要矛盾
{contradiction_text}

### 理性认识（本质）
{essence_text}

### 核心假设（待检验）
{hypotheses_text}

### 实践方向（由本阶段负责形成，不可替代工具证据）
{practice_direction_text}

## 输出格式（严格 JSON——只输出 JSON 对象，不要代码围栏，不要多余文字）
{
  "round_rationale": "第一轮先验证哪个论断？为什么从这个开始？",
  "epistemic_role": "exploration | verification | revision",
  "directional_claim": "本轮检验的论断，必须可追溯到锚点中的某条假设或矛盾",
  "deviation_rationale": "若本轮方向偏离锚点，显式说明原因；无偏离则空字符串",
  "testable_claims": [
    {"claim": "要检验的论断", "source": "来自哪个阶段的什么结论", "if_true": "...", "if_false": "..."}
  ],
  "tool_calls": [
    {"tool": "python_exec", "params": {"code_ref": "代码意图描述", "timeout_seconds": 30}},
    {"tool": "web_search", "params": {"query": "..."}}
  ],
  "expected_outcomes": ["本轮预期成果"]
}
"""

# ═══════════════════════════════════════════════════════════
# 后续轮次实验规划
# ═══════════════════════════════════════════════════════════

RN_PLAN = """
你正在执行多轮实践实验。现在是第 {round_num} 轮。

## 总体方向锚点（每轮都必须先对齐方向，再决定本轮内容）
{direction_anchor}
在写本轮规划前，先回答自己：本轮要推进锚点中的哪个论断？
前一轮的证据使这个论断的状态发生了什么变化？本轮成功或失败分别意味着什么？
然后在 directional_claim 中写出答案。

## 可用产物（前序轮次已生成/修改的文件，可直接引用路径，不必重新探索）
{artifacts_text}

## 认知上下文（所有轮次共享）

### 原始问题
{question}

### 调查发现
{facts_text}

### 信息缺口
{gaps_text}

### 主要矛盾
{contradiction_text}

### 理性认识（本质）
{essence_text}

### 核心假设
{hypotheses_text}

### 实践方向（由本阶段根据上一轮证据更新）
{practice_direction_text}

## 上一轮完整记录

### 上一轮实验规划
{prev_round_plan}

### 上一轮工具调用结果
{prev_round_results}

### 上一轮工具执行状态（结构化，优先参考）
{execution_status_text}

### 上一轮耗时
{prev_round_duration}

## 全部已完成轮次的执行日志
{all_rounds_log}

## 本轮规划策略

先对齐方向锚点，明确本轮 epistemic_role（exploration/verification/revision），再基于前序轮次结果决定方向：
- 如果上一轮有明确的验证失败：本轮聚焦复验，说明这与锚点的关系
- 如果上一轮建立了基线但未充分覆盖：本轮扩展检验
- 如果上一轮发现了意外结果：先判断它是否服务于锚点，再决定深挖或回归
- 如果上一轮工具调用出错：本轮修复参数重试（技术失败，不构成证伪）
- 如果持续偏离锚点，检查是否该通过 deviation_rationale 显式转向

## 可用工具

以下工具清单由系统动态生成，以它为准，不要使用清单之外的工具：
{tools_text}

## 输出格式（严格 JSON——只输出 JSON 对象，不要代码围栏，不要多余文字）
{
  "round_rationale": "基于上一轮结果，本轮做什么、为什么",
  "epistemic_role": "exploration | verification | revision",
  "directional_claim": "本轮检验的论断，必须可追溯到锚点中的某条假设或矛盾",
  "deviation_rationale": "若本轮方向偏离锚点，显式说明原因；无偏离则空字符串",
  "testable_claims": [
    {"claim": "本轮要检验的论断", "if_true": "...", "if_false": "..."}
  ],
  "tool_calls": [
    {"tool": "python_exec", "params": {"code_ref": "代码意图描述", "timeout_seconds": 30}},
    {"tool": "web_search", "params": {"query": "..."}}
  ],
  "expected_outcomes": ["本轮成功标准"],
  "done": false
}
如果实验结果充分，设 done: true（tool_calls 可为空）。
"""

# ═══════════════════════════════════════════════════════════
# 代码生成规范
# ═══════════════════════════════════════════════════════════

FILE_CONTENT = """
你是一个 Python 代码生成专家。根据问题上下文和文件用途，生成完整可运行的 Python 代码。

## 问题上下文
{question}

## 核心假设（需要检验的）
{hypotheses}

## 执行方案
{plan_summary}

## 文件信息
- 文件路径：{file_path}
- 用途：{purpose}

## 编码规则

### 基础要求
1. 代码必须自包含——所有函数定义、main 入口、print 输出都在一个文件里
2. 必须有 `if __name__ == '__main__': main()` 入口
3. 文件名已指定，不要在你的输出中重复路径声明
4. 只输出 Python 代码，不要有任何解释、markdown 标记或代码围栏
5. 不要使用需要额外安装的第三方库（Python 标准库即可）
6. 如果涉及数据，使用内联模拟数据或从问题描述中提取——不要从外部文件读取

### 编码与输出格式（关键——违反会导致整轮实践白跑）
7. **编码声明（必备）**：文件第一行必须是 `# -*- coding: utf-8 -*-`。
   第二行必须加上：
   ```python
   import sys; sys.stdout.reconfigure(encoding='utf-8')
   ```
   这确保在 Windows 上中文输出不会变成乱码。缺少这两行，分析系统将无法读取输出。
8. **结构化 JSON 输出（必备）**：所有的 print 输出必须使用 JSON 格式。分析系统 parse JSON 来判断结果，纯文本无法被自动分析。
   ```python
   import json
   result = {"status": "ok", "data": {...}, "summary": "..."}
   print(json.dumps(result, ensure_ascii=False, indent=2))
   ```
   执行失败时也必须输出 JSON：
   ```python
   {"status": "error", "message": "具体错误描述", "traceback": "..."}
   ```
9. **结构化字段约定**：
   - `status`: "ok" / "error" / "partial" —— 一句话说明执行状态
   - `data`: 核心计算结果（数字、列表、字典），放在这里供分析层提取
   - `summary`: 人类可读的一句话摘要
   - 可选 `details`: 补充说明或中间计算步骤

### 错误处理
10. 所有可能抛出异常的操作都要 try/except，捕获后输出 JSON 格式错误。
    main() 函数中用一个总的 try/except 包裹：
    ```python
    def main():
        try:
            _run()
        except Exception as e:
            import traceback
            print(json.dumps({"status": "fatal", "error": str(e),
                              "traceback": traceback.format_exc()},
                             ensure_ascii=False))
    ```
11. 如果代码依赖模拟数据，先验证数据的合理性（非空、字段齐全、数值在合理范围）。
    如果数据不符合预期，输出 `{"status": "error", "message": "数据验证失败：字段 xxx 缺失"}` 并退出。

### 可复现性
12. 涉及随机数的使用 `random.seed(42)` 或在输出 JSON 的 `data` 中包含种子值。
    涉及时间戳的使用固定参考日期而非动态获取（除非问题本身需要当前时间）。

### 示例骨架
以下是一个符合所有规范的最小文件骨架，你的代码应以此为模板：

```python
# -*- coding: utf-8 -*-
import sys; sys.stdout.reconfigure(encoding='utf-8')
import json

def _run():
    # 核心逻辑
    data = {"value": 42, "unit": "example"}
    print(json.dumps({
        "status": "ok",
        "data": data,
        "summary": "计算完成：值为 42"
    }, ensure_ascii=False, indent=2))

def main():
    try:
        _run()
    except Exception as e:
        import traceback
        print(json.dumps({
            "status": "fatal",
            "error": str(e),
            "traceback": traceback.format_exc()
        }, ensure_ascii=False))

if __name__ == '__main__':
    main()
```
"""

# ═══════════════════════════════════════════════════════════
# 代码修复
# ═══════════════════════════════════════════════════════════

CODE_FIX = """
你是一个代码调试专家。下面是一个 Python 脚本在执行时出错了。
你的任务：分析错误，修复代码，返回完整的修正版本。

## 规则
1. 仔细阅读错误信息（stderr），准确定位问题
2. 修复所有语法错误、运行时错误、导入错误、逻辑错误
3. 保持代码意图不变——不要改变算法或添加新功能，只修bug
4. 返回完整的修正后文件内容（不是 diff，是完整代码）
5. 如果错误是环境问题（缺少包、文件不存在等），设置 unfixable: true
6. 如果错误是编码问题（UnicodeEncodeError、UnicodeDecodeError、乱码输出）：
   - 检查文件是否缺少 `# -*- coding: utf-8 -*-` 声明 → 补上
   - 检查是否缺少 `sys.stdout.reconfigure(encoding='utf-8')` → 补上
   - 检查 print 语句是否输出 JSON 而非裸中文文本 → 如果是裸文本，改为 JSON 输出
7. 如果错误是 KeyError / AttributeError / IndexError / TypeError：
   - 检查数据来源——很可能是模拟数据字段不完整或类型不对
   - 补全缺失的数据字段，或增加 `.get(key, default)` 缺省值保护
8. 如果错误是 SyntaxError：
   - 逐行排查：括号匹配？引号闭合？缩进一致？f-string 引号嵌套？
   - 修复后确保语法正确
9. 如果错误是 ImportError / ModuleNotFoundError：
   - 检查是否用了非标准库（如 requests、pandas、numpy）
   - 如果是 → unfixable: true（标准库限制）
   - 如果是拼写错误（如 `form json import`）→ 修正

## 常见错误速查
| 错误类型 | 根因 | 修复方向 |
|---------|------|---------|
| UnicodeEncodeError | 缺编码声明 | 加 # -*- coding: utf-8 -*- 和 sys.stdout.reconfigure |
| KeyError: 'xxx' | 模拟数据字段缺失 | 补全数据或改用 .get() |
| ImportError: No module named 'xxx' | 用了非标准库 | unfixable（除非是拼接错误） |
| SyntaxError: invalid syntax | 拼写/括号/引号 | 逐行排查语法 |
| TypeError: 'NoneType' object is not subscriptable | 数据源返回 None | 加 None 检查 |
| ZeroDivisionError | 分母可能为零 | 加分母非零检查 |
| FileNotFoundError | 路径拼接错误 | 修正相对路径或使用绝对路径 |

## 原始代码
**文件**: {file_path}
```
{original_code}
```

## 执行错误
exit code: {exit_code}
stderr:
{stderr}

## 输出格式（严格 JSON）
{{
  "fixed_content": "完整修正后的代码（必须是完整文件，不是diff）",
  "fix_summary": "一句话说明修了什么（如'补全模拟数据中缺失的 date 字段'）",
  "unfixable": false
}}

如果错误无法修复，设置 unfixable: true 并在 fix_summary 中说明原因。
修复后的代码必须保留或补充编码声明行和 JSON 输出格式。
只输出 JSON。
"""

# ═══════════════════════════════════════════════════════════
# 边界模式验证任务生成
# ═══════════════════════════════════════════════════════════

BOUNDARY_TASKS = """
你正在为一个非技术性问题设计"真实世界实践验证清单"。

这份清单不是给智能体执行的——智能体无法做到这些。
这份清单是给用户的：如果他想真正验证前面的分析，他需要在现实世界中做什么。

## 前序分析
问题：{question}

知性分析评估（各主张的支持程度）：
{claim_assessments}

前序认识中需要检验的核心论断：
{action_items}

## 你的任务

为每个"uncertain"或"challenged"状态的主张，设计一个现实世界验证任务。
对于"supported"状态的主张，也应设计一个验证任务（支持性证据不等于实践验证）。

每个验证任务必须：
1. 具体、可操作——不是"做调研"，而是"在 GitHub 上抽样 20 个 1000+ star 的项目，记录..."
2. 有明确的时间范围
3. 有明确的成功/失败判断标准
4. 说明为什么智能体自己无法完成（不能只说"无法访问"——要说清楚这个验证需要什么样的现实条件）

## 输出格式（JSON）
{{
  "real_world_practice_needed": [
    {{
      "hypothesis": "要验证的假设",
      "why_important": "为什么这个假设对当前判断至关重要",
      "practice_method": "具体怎么做（足够详细，用户拿到后能直接执行）",
      "observable_outcome": "成功标准（量化或可观察的）",
      "estimated_duration": "需要多长时间",
      "why_agent_cannot": "为什么智能体无法完成这个验证"
    }}
  ]
}}
只输出 JSON。
"""
