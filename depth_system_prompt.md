# Praxic 推理深度体系重构任务

## 背景

Praxic 当前的"推理控制"存在三个结构性问题，实测数据（probe_reasoning_control.py 探针 + 真实验收）已确认：

1. **模型分级虚设**：`get_phase_llm` 的 per-phase 模型路由读 `ui_phase_models` / `ui-settings.json`，但两处配置均为空，所有阶段实际都在用 deepseek-v4-pro。分级配置从未真正生效，却增加了复杂度。
2. **reasoning_effort 与模型不适配**：探针实测——DeepSeek v4-pro 接受 `reasoning_effort` 但不分级（low=1589 vs high=1792 reasoning tokens，差异可忽略）；`enable_reasoning=False` 完全无效（2829 vs 基线 3362）；小预算下 reasoning 抢占导致 empty_content（max_tokens=64 时 content=0）。同一档位语义在 OpenAI/DeepSeek/Claude 上完全分裂。
3. **深度无真实杠杆**：`light_phases` 只写入（cognitive_loop.py:599-601）从未被消费，是死配置。深度控制只有 max_tokens 裁剪，没有连输出结构一起变化。

目标：建立**模型无关的推理深度体系**。深度档位由纯语义定义（max_tokens + 推理指令 + 输出 schema 层级），不依赖任何 provider 私有参数；统一使用 deepseek-v4-flash 作为唯一模型；深度由预处理查表决定第一轮，反思阶段通过 phase_budgets 调控后续轮次。

## 设计总纲

```
depth（SHALLOW / STANDARD / DEEP）→ 三要素，全部模型无关：
  1. max_tokens 预算
  2. 推理指令（prompt 文本："直接作答" / "简要分析" / "完整推理链"）
  3. 输出 schema 层级（required / standard_extended / deep_extended）

分层：
  - 档位定义层：三要素映射表（纯语义，与模型无关）
  - 初始分配层：预处理查表 task_nature × complexity → 各阶段 depth（第一轮）
  - 反思调控层：phase_budgets 的 reasoning_effort 字段替换为 depth（后续轮次）
  - 适配层：各家推理私有参数（reasoning_effort/thinking budget/enable_reasoning）的映射表，可留空，不进档位定义
  - 兜底层：empty_content → max_tokens 翻倍重试一次（模型无关）
```

## 改动清单

### Phase A：档位定义与工具层

**A1. 新增深度枚举与映射表**
- 新建文件：`praxic/core/depth.py`
- 内容：

```python
from enum import Enum

class Depth(Enum):
    SHALLOW = "shallow"
    STANDARD = "standard"
    DEEP = "deep"

# 三要素映射（模型无关的纯语义）
DEPTH_CONFIG = {
    Depth.SHALLOW: {
        "max_tokens": 1024,
        "instruction": "直接给出结论，不展示推理过程。",
        "schema_level": "required",
    },
    Depth.STANDARD: {
        "max_tokens": 4096,
        "instruction": "简要推理后给出结论，推理与结论都精炼。",
        "schema_level": "standard_extended",
    },
    Depth.DEEP: {
        "max_tokens": 16384,
        "instruction": "进行完整推理，展示关键推理链、依据和每步原因。",
        "schema_level": "deep_extended",
    },
}

def parse_depth(raw, default=Depth.STANDARD) -> Depth:
    """解析深度值；非法值返回 default。"""
    if isinstance(raw, Depth):
        return raw
    try:
        return Depth(str(raw).strip().lower())
    except (ValueError, AttributeError):
        log.warning("depth.invalid", value=raw)
        return default

def depth_schema_text(depth: Depth, schema: dict) -> str:
    """按深度注入输出 schema 层。schema 形如
    {"required": {...}, "standard_extended": {...}, "deep_extended": {...}}
    返回当前深度应输出的字段说明拼接文本。"""
    levels = ["required"]
    if depth in (Depth.STANDARD, Depth.DEEP):
        levels.append("standard_extended")
    if depth == Depth.DEEP:
        levels.append("deep_extended")
    return "\n".join(schema[level] for level in levels if level in schema)
```

**A2. phase_budget.py 适配 depth**
- 文件：`praxic/core/phase_budget.py`
- 做法：
  - `budget_reasoning_kwargs` 保留（适配层仍可用），但新增 `budget_depth(budget) -> Depth | None`：读取预算中 `depth` 字段，经 `parse_depth` 解析
  - `budget_max_tokens` 逻辑改为：预算里有显式 `max_tokens` 用它；否则按 `depth` 查 `DEPTH_CONFIG`；两者都无 → 保持当前值
  - `reasoning_effort` 字段标记为 deprecated（兼容读取，但新输出用 `depth`）

### Phase B：统一模型与取消分级

**B1. 取消 per-phase 模型路由**
- 文件：`praxic/llm/__init__.py`
- 做法：
  - `get_phase_llm(phase_name)` 简化为 `get_llm(model=None)` 等价：不再读 `ui_phase_models`、不再读 `ui-settings.json`，`_config_phase_model` 删除
  - 保留 `get_llm(provider, model)` 签名（外部兼容），但认知循环内不再按阶段路由
  - `settings.ui_phase_models` 字段保留（配置兼容，不再消费）
- 验收：`get_phase_llm("preprocessing").default_model == settings.default_model`（全阶段同一模型）

**B2. 默认模型切换为 flash**
- 文件：`config.toml`（本地）、`config.toml.example`
- 做法：`[llm] model = "deepseek-v4-flash"`
- 注意：这是本地配置，不提交 config.toml；config.toml.example 可更新

### Phase C：各阶段深度感知输出契约

**C1. 通用改造模式（六个阶段统一做法）**
- 每个阶段的 prompt 输出格式段：从"固定完整 schema"改为按 depth 注入
- 每个阶段模块的调用处：从 `self.config` 读 depth（默认 STANDARD），生成 `depth_schema_text` 注入 prompt，`max_tokens` 按 `DEPTH_CONFIG[depth]` 取
- 每个阶段方法的 `budget` 参数已存在（上一轮加的），depth 读取优先级：`budget.depth` > `self.config.depth` > STANDARD

**C2. 具体阶段改造点**
- `praxic/core/question_preprocessing.py`：
  - `_call_step` 的 `reasoning_kwargs` 移除（不再传 reasoning_effort）；max_tokens 由 depth 决定（step1 固定 SHALLOW，step345 合并按 task complexity：simple→SHALLOW，standard→STANDARD，complex→DEEP）
  - step345 的 schema 分层：SHALLOW 只出 question_intent/expanded_question，STANDARD 全字段，DEEP 加 detailed_report 详因
- `praxic/core/investigation.py`：
  - `investigate()`：max_tokens 按 depth；输出 schema 分层——SHALLOW 只 facts，STANDARD facts+gaps+summary，DEEP 加 illustrative_case（解剖麻雀）
  - `_do_web_search` 的 query 生成调用固定 SHALLOW（max_tokens=1024，直接出 query 列表）
  - second pass 条件已有（budget max_calls=1 禁用），保留
- `praxic/core/contradiction.py`：
  - `analyze()`：DEEP 才要求完整 system_model（elements/relationships/feedback_loops/emergent_properties）；STANDARD 只要 principal + secondary + 简短推导；SHALLOW 只要 principal_contradiction
  - prompt 输出格式段按 depth 注入；max_tokens 按 `DEPTH_CONFIG`（DEEP=16384，STANDARD=4096，SHALLOW=1024）
- `praxic/core/rational.py`：
  - `synthesize()` 与 deepen：DEEP 要求完整 essence+hypotheses+contradiction_motion；SHALLOW 只要 essence
- `praxic/core/practice.py`：
  - `_call_planner`：规划是结构化 JSON 输出，固定 `enable_reasoning=False`（现行为保留），depth 决定 max_tokens 与 schema 层级——SHALLOW 只要 tool_calls+directional_claim，STANDARD 加 testable_claims+rationale，DEEP 加策略推演
  - `_generate_file_content` 固定 SHALLOW（代码生成不需要推理链）
  - `_analyze_all_rounds` / `_boundary_analysis` 固定 STANDARD
- `praxic/core/reflection.py`：
  - `reflect()`：输出 schema 分层——SHALLOW 只要 convergence+should_reinvestigate+final_answer；STANDARD 加复盘+focus_hints+phase_budgets；DEEP 加认知偏差+技能蒸馏+phase_budgets 详因
  - prompt 中"任务 11 阶段预算调控"的输出字段从 `reasoning_effort` 改为 `depth`（值域 shallow/standard/deep）

**C3. 解析层按 depth 校验**
- 各阶段 `_parse_response` / `_parse_json_safe` 后追加：校验当前 depth 要求的 schema 层字段是否存在（如 DEEP 缺 deep_extended 字段 → log warning 并按失败处理/重试）。校验失败不崩溃，走该阶段既有 fallback。

### Phase D：深度分配链

**D1. 初始深度表（第一轮）**
- 文件：`praxic/core/question_preprocessing.py` 或新 `praxic/core/depth.py`
- 内容：`INITIAL_DEPTH_TABLE: dict[task_nature, dict[complexity, dict[phase, Depth]]]`
- 原则：
  - code_generation / fact_lookup：investigation/contradiction/rational → SHALLOW（或 skip），practice → STANDARD
  - causal_explanation / exploration_understanding：investigation → STANDARD，contradiction/rational → DEEP，practice → STANDARD
  - comparison_decision / creative_design：STANDARD 为主
  - simple 复杂度整体降一档，complex 升一档
- 认知循环在迭代起始（现 `light_phases` 写入处，cognitive_loop.py:599）改为写入 `initial_depths` 到 working_mem；`light_phases` 写入删除（死配置收编）

**D2. 反思调控**
- `phase_budgets` 的字段：`reasoning_effort` 替换为 `depth`（值域 shallow/standard/deep），`max_tokens`/`max_calls`/`max_rounds` 保留
- cognitive_loop 消费：`budget.depth` 优先于 `initial_depths`（反思是后续轮次的最终裁决）
- 各阶段 depth 解析优先级：`budget.depth` > `working_mem.initial_depths[phase]` > `self.config.depth` > STANDARD

### Phase E：兜底层（模型无关）

**E1. empty_content 翻倍重试**
- 文件：`praxic/llm/openai_compatible.py`（`call()` 内）或各阶段 `_call_step` 层
- 建议位置：`openai_compatible.py` 的 `call()`——content 为空且 `finish_reason=length` 时，内部自动用 `max_tokens * 2` 重试一次（不进递归：重试后仍空则返回空，交上层 fallback）
- 理由：这是模型无关的通用行为，放 adapter 层一次覆盖所有调用方
- 注意：重试增加一次 API 调用，需要日志标记 `retried_for_empty`；不改变默认行为（content 非空时不触发）

## 验收标准

1. `python -m pytest -q` 全部通过，`python -m compileall -q praxic` 通过
2. 单元测试（mock LLM）：
   - `parse_depth` 非法值回退 STANDARD
   - `depth_schema_text` 按深度返回对应层级文本（SHALLOW 无 standard/deep 层，DEEP 全含）
   - `budget_depth` 从 phase_budgets 解析
   - 各阶段 mock 验证：depth=SHALLOW 时 prompt 只含 required 字段说明、max_tokens=1024；DEEP 时含 deep_extended、max_tokens=16384
   - cognitive_loop 验证：迭代起始写入 initial_depths，反思 phase_budgets.depth 覆盖之
   - `get_phase_llm` 全阶段返回同一模型
   - empty_content 翻倍重试：mock 第一次返回空 content + finish=length，第二次成功，断言 max_tokens 翻倍且只重试一次
3. 回归：现有测试不受影响（depth 默认 STANDARD 时各阶段行为与现状等价；唯一变化是 reasoning_effort 不再透传——断言现有测试不依赖该参数）
4. 真实验收（可选）：`scripts/verify_practice_real.py` 跑一轮，观察 empty_content 次数下降（E1 生效）与各阶段耗时变化（SHALLOW 档确实更快）

## 约束

- **深度档位定义层不依赖任何 provider 私有参数**——reasoning_effort/thinking/enable_reasoning 只在适配层可查表使用，且可全部留空
- 不取消反思阶段原有功能（复盘/收敛/skip/focus/mode/final_answer/技能蒸馏全保留，只是 schema 按深度分层）
- 不删除决策兼容层，不改认知循环阶段结构
- 不引入新依赖
- 默认行为尽量不变：depth 未设置时按 STANDARD，与现行为等价（除 reasoning_effort 透传移除）
- `light_phases` 死配置收编删除，不留双轨
- 提示词保持中文，风格与现有 harness 一致
