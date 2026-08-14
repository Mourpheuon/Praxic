# Praxic 矛盾主线化改造任务

## 背景

Praxic 的辩证唯物主义内核中，"主要矛盾"应当是贯穿认知循环的主线索：矛盾通过多轮迭代持续演化，任意阶段按需读取。但当前实现有三个断裂：

1. **矛盾维护机制存在但未接线**：`contradiction.py` 已有完整的 `maintain_contradictions()`（Retain/Refine/Append/Position shift、derivation_chain fork、iteration 递增），模型层有 `ContradictionPositionShift` 和 `iteration` 字段，前端已渲染"矛盾地位转换"面板——但认知循环从不调用 maintain，矛盾每轮从零 `analyze()`，演化数据流是死的。
2. **调查阶段看不到矛盾**：`working_memory.py` 的 `get_context_for_phase()` 中 `if phase not in ("investigation", "contradiction")` 显式排除调查——第一轮调查只能看到预判矛盾（contradiction_in_question），第二轮调查拿不到上一轮识别的主要矛盾，无法"带着检验任务"去收集证据。
3. **阶段只能被动接收上下文**：各阶段依赖 cognitive_loop 拼装的 additional_context，没有主动读取矛盾结构的能力，无法在阶段内部按需追问"新事实与主要矛盾的关系"。

目标：把主要矛盾升级为**持续维护、可主动阅读的核心状态**：
- 矛盾通过多轮矛盾分析被维护（第二轮起走 maintain，而非重新 analyze）
- 任意阶段即使不被被动输入，也可通过受控句柄主动阅读矛盾
- 调查阶段可见上一轮矛盾（作为检验对象，而非被其锚定）

## 改动清单

### Phase A：认知循环接线（矛盾持续维护）

**A1. 第二轮起矛盾分析走 maintain**
- 文件：`praxic/core/cognitive_loop.py`
- 位置：标准路径矛盾分析处（约 832 行）与快速路径（约 815 行）
- 做法：

```python
# 标准路径，替换现有 analyze 调用：
_prev_graph = working_mem.get_contradiction_graph()
if _prev_graph is not None and trace.metadata.iterations > 1:
    contradiction_graph = await self.contradiction.maintain_contraditions(
        previous_graph=_prev_graph,
        updated_fact_report=fact_report,
        question=effective_question + _hint("contradiction") + _steer("contradiction"),
        budget=phase_budgets.get("contradiction", {}),
    )
else:
    contradiction_graph = await self.contradiction.analyze(
        fact_report=fact_report,
        question=effective_question + _hint("contradiction") + _steer("contradiction"),
        additional_context=working_mem.get_context_for_phase("contradiction"),
        budget=phase_budgets.get("contradiction", {}),
    )
```

- 快速路径（fast 模式）保持 analyze（单轮无维护意义）
- 注意：`maintain_contraditions` 当前签名没有 `budget` 参数，需补充（见 A3）

**A2. maintain 方法接 budget 与 depth 分层**
- 文件：`praxic/core/contradiction.py`
- 位置：`maintain_contraditions` 签名（约 631 行）
- 做法：
  - 签名增加 `budget: dict = None`
  - 内部 max_tokens 应用 `budget_max_tokens`（当前硬编码 16384，见约 706 行）
  - 按 depth 注入 schema 分层（与 analyze 一致）：SHALLOW 只要求 principal 与 retained/position_shifts；DEEP 才要求完整 system_model 与 derivation fork 细节
  - maintain 的 prompt 追加一行"本档输出范围"说明（复用 analyze 的 `_schema_scope` 模式，提取为共用方法避免重复）

**A3. 矛盾演化数据落 trace**
- `maintain_contraditions` 已返回带 `position_shifts`、`iteration` 的图；cognitive_loop 已有 `trace.contradictions = contradiction_graph` 和 `working_mem.set_contradiction()`，无需额外改动，但需确认 fast/标准两路径都走这两个存储点（现状已满足）。

### Phase B：调查阶段可见矛盾（检验对象）

**B1. working_memory 放开调查阶段**
- 文件：`praxic/memory/working_memory.py`
- 位置：`get_context_for_phase()` 中矛盾注入条件（约 96 行）
- 做法：

```python
# 原：if phase not in ("investigation", "contradiction"):
# 改：矛盾分析阶段保持独立认定（不看旧矛盾）；调查阶段可见（作为检验对象）
if phase != "contradiction":
    cc = self.get_contradiction_context()
    if cc:
        if phase == "investigation":
            parts.append("## 上一轮识别的矛盾结构（作为本轮调查的检验对象：可验证、深化或推翻，勿默认其为正确）\n%s" % cc)
        else:
            parts.append("## 当前矛盾结构（贯穿本轮所有阶段）\n%s" % cc)
```

- 第一轮矛盾未产出时 `get_contradiction_context()` 为空，条件自然跳过（兼容第一轮）

**B2. 调查 prompt 追加检验语义**
- 文件：`praxic/core/investigation.py`，`_INVESTIGATION_PROMPT`
- 做法：在 prompt 末尾或调查任务说明中追加：

```
## 矛盾检验（若有）

若上下文提供"上一轮识别的矛盾结构"：本轮调查须围绕它展开——
- 收集与该矛盾两极直接相关的事实
- 标注哪些事实支持、哪些削弱、哪些与矛盾无关
- 若发现矛盾被证据推翻的迹象，在 gaps 中注明"该矛盾需重新认定"
若无矛盾结构：按问题本身调查即可。
```

### Phase C：阶段主动阅读矛盾（受控句柄）

**C1. 各阶段方法增加可选 contradiction 参数**
- 文件：`praxic/core/investigation.py`、`praxic/core/rational.py`、`praxic/core/practice.py`、`praxic/core/reflection.py`
- 做法：各阶段入口方法（investigate / synthesize / practice / reflect）签名增加 `contradiction=None`（investigation 在 `budget` 后追加；rational 在 `budget` 后追加；practice 已有 `trace` 参数内含 contradictions，可跳过或复用；reflect 已有 `trace`，同样可跳过）
- 语义：**受控句柄，非直接读 working_mem**。contradiction 为 None 时阶段行为完全不变（兼容第一轮与单阶段调用）；非 None 时阶段内部按需使用

**C2. cognitive_loop 传入句柄**
- 文件：`praxic/core/cognitive_loop.py`
- 做法：调用 investigation / rational / practice / reflection 时传入 `contradiction=working_mem.get_contradiction_graph()`（reflection 和 practice 有 trace 可复用，不必重复传，由执行者按现状选择最小改动）

**C3. 阶段内部按需使用的具体语义**
- investigation：prompt 已由 B2 覆盖（被动注入 + 主动检验说明）；若实现主动阅读，可在调查过程中将新事实与矛盾极比对（记入 facts 的 related_to 或新字段）
- rational：essence 输出要求"本质是主要矛盾的内部联系"，hypotheses 标注来源矛盾极（prompt 层面微调，若已覆盖则跳过）
- practice：方向锚点中主要矛盾已置前（既有改造）；`directional_claim` 校验可加"与主要矛盾的关联度"提示（软提示，不硬校验）
- reflection：复盘以矛盾演变为骨架——`contradiction_retrospective` 要求覆盖：矛盾是否演化、position_shifts 是否发生、认识是否深化。prompt 已有"矛盾追踪"任务 9，强化其使用 position_shifts 数据

### Phase D：数据流与校验

**D1. 调查 facts 的矛盾相关性标注（可选，B2 验证有效后做）**
- `FactReport.facts` 已有 `related_to` 字段；可加 `contradiction_relevance: str = ""`（support / oppose / irrelevant / 空）
- 调查 prompt 输出格式对应追加；不强制（深度 SHALLOW 可不填）

**D2. 反思消费 position_shifts**
- 文件：`praxic/core/reflection.py`
- 做法：`_summarize_trace` 中，若 `trace.contradictions.position_shifts` 非空，追加到反思输入："矛盾地位转换：xxx 从 secondary 升为 principal（第 N 轮，触发事实：...）"
- 反思的 `contradiction_shift_detected` 判定可参考 position_shifts 数据（软参考，不硬绑定）

## 验收标准

1. `python -m pytest -q` 全部通过，`python -m compileall -q praxic` 通过
2. 单元测试（mock LLM）：
   - 第二轮迭代：cognitive_loop 调用 `maintain_contraditions` 而非 `analyze`（mock 断言调用方法名）；第一轮仍走 analyze
   - maintain 收到 budget（depth=SHALLOW 时 max_tokens 受控）
   - working_memory：phase="investigation" 时矛盾上下文注入且文案含"检验对象"；phase="contradiction" 时不注入
   - 各阶段方法：contradiction=None 时行为与现有测试一致（回归）
   - maintain 的 position_shifts 累积（previous + new）与 iteration 递增
3. 回归：现有 test_phase_budget / test_depth / test_practice_upgrade 全过（句柄参数默认 None 不影响）
4. 真实验收（可选）：`scripts/verify_practice_real.py` 跑一轮多迭代（max_iterations=2）问题，观察：第二轮调查 prompt 含上一轮矛盾结构；矛盾分析日志显示 maintain 而非 analyze；position_shifts 有数据（若发生地位转换）

## 约束

- **不重新实现矛盾分析逻辑**——maintain_contraditions 已存在，只接线和接 budget
- 矛盾分析阶段本身保持独立认定（不被动注入旧矛盾，避免被锚定）；调查阶段可见但标注"检验对象，勿默认正确"
- 主动阅读通过**受控句柄参数**实现，不引入"阶段直接 import working_mem"的隐式耦合
- 不取消任何既有功能；矛盾为 None 时各阶段行为完全不变
- 不引入新依赖；提示词保持中文；depth/schema 分层规则与现有深度体系一致
- position_shifts / iteration 是既有字段，本次只接通数据流，不改模型结构（除非验收发现字段缺失）
