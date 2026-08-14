# Praxic 反思阶段执行预算调控器任务

## 背景

Praxic 的反思阶段（`praxic/core/reflection.py`）当前是"建议者"：产出复盘、收敛判定、`skip_phases`、`focus_hints`、`recommended_mode`、`final_answer`、技能蒸馏建议，由认知循环（`praxic/core/cognitive_loop.py`）消费后影响下一轮。但反思**没有能力直接调控下一轮各阶段的执行参数**——调用次数、max_tokens、推理强度都是静态配置。

现状问题：标准模式单次迭代，矛盾分析单次调用 max_tokens=16384 且无 reasoning 控制（约 85s），调查 max_tokens=8192 无 reasoning 控制（约 60s），而 `PhaseConfig.reasoning_effort` 字段（config.py:136）定义了但四个重阶段从未接线。

目标：让反思阶段作为**内置的执行预算调控器**，基于本轮实际产出质量和耗时表现，为下一轮设置各阶段的调用次数、max_tokens、reasoning_effort。**不取消反思阶段任何原有功能**（复盘、收敛判定、skip_phases、focus_hints、recommended_mode、final_answer、技能蒸馏全部保留），新增能力与原有功能并行。默认行为完全不变：不设预算时与现状等价。

## 改动清单

### Phase A：数据模型（增量字段）

**A1. ReflectionReport 增加 phase_budgets 字段**
- 文件：`praxic/api/schemas/models.py`
- 位置：`class ReflectionReport`（约 335 行）
- 做法：追加字段

```python
phase_budgets: dict[str, dict] = Field(default_factory=dict)
```

- 语义：`{"阶段名": {"max_calls": int, "max_rounds": int, "max_tokens": int, "reasoning_effort": str, "reason": str}}`
  - `max_calls`：调查阶段是否允许补充搜索二轮（1=只跑主调查；不设=允许二轮）
  - `max_rounds`：实践阶段最大轮数（覆盖 practice_rounds；不设=默认）
  - `max_tokens`：该阶段单次 LLM 输出上限（覆盖 config 默认；不设=默认）
  - `reasoning_effort`：`off`/`low`/`medium`/`high`；`off` 映射为 `enable_reasoning=False`；不设=保持现状（medium）
  - `reason`：理由说明，纯注释，不参与执行
- 阶段名限定：`investigation` / `contradiction` / `rational` / `practice`（可选 `reflection` 自身，防递归失控可忽略）
- 字段默认空 dict → 所有现有测试和调用不受影响

### Phase B：反思 prompt 增量（不删原任务）

**B1. 任务列表追加预算调控条目**
- 文件：`praxic/core/reflection.py`，`_REFLECTION_PROMPT`
- 位置：现有任务 10（最终回答）之后追加任务 11
- 文本：

```
11. **阶段预算调控**：基于本轮各阶段的产出质量和耗时表现，为下一轮设置 phase_budgets。
    - 可调项：调用次数（max_calls / max_rounds）、输出上限（max_tokens）、推理强度（reasoning_effort）
    - 原则：兼顾速度与深度。矛盾分析和理性认识是认识深度的核心，推理强度建议保持 medium 及以上；
      调查、反思等事实收集/收敛类阶段可设 low。削减 max_tokens 和调用次数必须有依据——
      该阶段产出已充分、或某阶段显著拖慢主链路且深度收益低。
    - 未列出的阶段保持默认；每一项都要给出简短理由（reason 字段）。
    - 不确定时保守：宁可少调，不要为了省时而牺牲认识深度。
```

**B2. 输出格式 JSON 追加 phase_budgets 示例**
- 位置：`_REFLECTION_PROMPT` 输出格式段
- 追加：

```json
"phase_budgets": {
  "investigation": {"max_calls": 1, "max_tokens": 4096, "reasoning_effort": "low", "reason": "事实已充分，仅需主调查"},
  "practice": {"max_rounds": 2, "reasoning_effort": "off", "reason": "首轮已收敛"}
}
```

并注明：不设置时输出 `"phase_budgets": {}`。

**B3. 解析器接受新字段**
- 文件：`praxic/core/reflection.py`，`_parse_response`（约 331 行）
- 做法：现有解析逻辑构建 ReflectionReport 时，`phase_budgets` 走 Pydantic 默认值（无需特殊处理），但需确认 `_parse_response` 是逐字段赋值还是直接传 data dict。若逐字段赋值，追加 `phase_budgets=data.get("phase_budgets", {})`。

### Phase C：认知循环消费

**C1. 反思结果写入 working_mem**
- 文件：`praxic/core/cognitive_loop.py`
- 位置：迭代末尾反思消费块（现约 995-1008 行，`working_mem.set("skip_phases", next_skip)` 和 `focus_hints` 附近）
- 做法：追加

```python
budgets = getattr(reflection_report, "phase_budgets", None)
if budgets:
    working_mem.set("phase_budgets", budgets)
```

**C2. 每轮迭代起始时清理上一轮预算（可选但推荐）**
- 位置：循环体起始（`skip_phases = working_mem.get("skip_phases") or []` 附近）
- 做法：预算只作用于反思后的下一轮；若该轮结束时未产生新预算，不应沿用旧预算。在每次反思写入新预算前先 `working_mem.set("phase_budgets", {})` 或设计为"反思后立即应用、执行完即失效"。

### Phase D：各阶段应用（默认行为不变）

**D1. 传递机制：cognitive_loop 注入，不新增全局状态**
- 各阶段方法签名**不改**（investigate 当前不接受 wm；practice 接受 wm）。统一通过 cognitive_loop 在调用前读取预算并作为参数或上下文传入。
- 推荐做法：cognitive_loop 调用各阶段时，把 `budget = working_mem.get("phase_budgets", {}).get(phase, {})` 通过已有通道传入：
  - investigation / contradiction / rational：追加到 `additional_context` 之外的专用参数不可行（签名未定义）——**方案：给 investigate/analyze/synthesize 增加可选参数 `budget: dict = None`**，默认 None 时行为不变；cognitive_loop 传入。
  - practice：已有 `wm` 参数，内部 `wm.get("phase_budgets", {}).get("practice", {})` 读取。
- 约束：新增参数默认 None/空，现有测试与调用不受影响。

**D2. investigation.py 应用预算**
- 位置：`investigate()` 主调查调用（约 320 行）与 second pass 条件（约 340 行）
- 做法：
  - 主调用：`max_tokens = budget.get("max_tokens", max_tokens)`；`reasoning_effort` 传入 `llm.call`（复用 openai_compatible 的 `_REASONING_CONTROLS` 机制，不支持自动降级）
  - second pass 条件追加：`and budget.get("max_calls", 2) != 1`（预算明确限制为 1 时不触发补充搜索）
  - `_do_web_search` 的 query 生成调用同样应用 reasoning_effort（若设 low）

**D3. contradiction.py 应用预算**
- 位置：`analyze()` 调用（约 334 行）
- 做法：`max_tokens = budget.get("max_tokens", max_tokens)`；`reasoning_effort` 透传。默认（无预算）保持现状 16384/无控制——但注意：这是本项目方法论核心阶段，prompt 已提示反思保守处理。

**D4. rational.py 应用预算**
- 位置：`synthesize()` 调用（约 171 行）与 deepen 调用（约 289 行）
- 做法：同上，`max_tokens` 与 `reasoning_effort` 覆盖。

**D5. practice.py 应用预算**
- 位置：`practice()` 入口（`self.practice_rounds` 使用处）与 `_call_planner` / `_generate_file_content` / `_analyze_all_rounds`
- 做法：
  - 入口：`rounds = budget.get("max_rounds", self.practice_rounds)`
  - 规划/生成/分析调用：`max_tokens` 覆盖；`reasoning_effort` 为 `off` 时传 `enable_reasoning=False`（与当前正在做的方案 B 兼容：现已在规划/生成硬编码 `enable_reasoning=False`，预算为 off 时保持一致，预算为 low/medium 时以预算为准）
  - 注意兼容：不要移除现有 `enable_reasoning=False` 硬编码，预算存在时预算优先

**D6. 值域校验**
- 所有阶段在应用前校验 `reasoning_effort in {"off","low","medium","high"}`，非法值忽略并 log warning；`max_tokens` 为正整数否则忽略；`max_calls`/`max_rounds` 为正整数否则忽略。

## 验收标准

1. `python -m pytest -q` 全部通过，`python -m compileall -q praxic` 通过
2. 单元测试：mock LLM 返回含 `phase_budgets` 的反思输出，验证：
   - ReflectionReport.phase_budgets 正确解析
   - cognitive_loop 写入 working_mem，下一轮各阶段收到预算
   - investigation 预算 max_calls=1 时不触发 second pass
   - practice 预算 max_rounds=2 时实际只跑 2 轮
   - reasoning_effort 透传至 llm.call（mock 捕获 kwargs）
   - 非法值（reasoning_effort="super"、max_tokens=-1）被忽略，走默认
3. 回归：不设置 phase_budgets（反思输出 `{}`）时，各阶段调用参数与改动前完全一致
4. 反思原有功能不回退：skip_phases、focus_hints、recommended_mode、final_answer、技能蒸馏字段仍正常解析和消费
5. 真实验收（可选）：`scripts/verify_practice_real.py` 跑一轮，观察反思输出的 phase_budgets 是否随质量/耗时合理变化

## 约束

- **不取消反思阶段任何原有功能**——新增为纯增量
- 不删除决策兼容层，不改认知循环阶段结构（跳过逻辑仍由 skip_phases 负责）
- 不引入新依赖
- 不改动 `praxic/web` 前端
- 默认行为完全不变：无预算时与现状等价
- 预算只影响反思后的下一轮，不持久化，不污染全局 config（不修改 PhaseConfig 实例）
- 预算只调控"可选的额外调用"（调查二轮、实践轮数）和输出规模/推理强度，**不砍掉主调用**——主调用永远执行，保证认知循环完整
- 提示词保持中文，风格与现有 harness 一致
