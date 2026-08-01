# Praxic 预处理与阶段耗时优化任务

## 背景

标准模式完整循环中，从用户输入到实践阶段开始前需要 7+ 次串行 LLM 往返，实测单问题到矛盾分析结束已耗时约 190 秒（预处理 45s + 调查 60s + 矛盾 85s）。三个根因：

1. **模型分级配置断裂**：`config.toml` 的 `[ui] phase_models = {"preprocessing": "deepseek-v4-flash"}` 写了，但 `praxic/llm/__init__.py` 的 `get_phase_llm()` 只读 `data/ui-settings.json`（该文件 `phase_models` 为空 `{}`），配置从未生效。预处理阶段实际在用 deepseek-v4-pro 推理模型。
2. **预处理串行调用过多**：`QuestionPreprocessing.preprocess()` 内部严格串行 4 次 LLM 调用（step1 任务性质 → step3 意图矛盾 → step4 预设审查 → step5 结构化扩展）。step3 与 step4 互不依赖，本可并行。
3. **小 max_tokens 被推理 token 吃光**：step3/step4 的 max_tokens 仅 256/512，deepseek-v4-pro 的 reasoning_content 先耗尽预算，`finish_reason=length`，content 为空 → 解析失败 → fallback。日志中的 `empty_content finish_reason=length` 即此现象。A1 修复（不再用 reasoning 顶替 content）后此类调用产出为零，问题更明显。

目标：预处理阶段耗时从 ~45s 降至 ~10s 内；全链路往返次数减少；不改认知循环阶段结构。

## 改动清单

### Phase A：修通模型分级（最高优先级）

**A1. get_phase_llm 同时读取 config.toml 的 ui_phase_models**
- 文件：`praxic/llm/__init__.py`
- 位置：`get_phase_llm(phase_name)`
- 做法：在读取 `data/ui-settings.json` 之前，先检查 `settings.ui_phase_models`（config.toml 的 `[ui] phase_models`，JSON blob 字符串）。逻辑：
  1. 解析 `settings.ui_phase_models`（json.loads），若 `phase_name` 在其中且非空，取该模型
  2. 否则读取 `data/ui-settings.json` 的 phase_models（UI 运行时覆盖优先于 config.toml？——决策：**ui-settings.json 优先**，因为它是 UI 的最新写入；config.toml 作为初始默认）
  3. 两者都无 → `cfg.model or default_model`
- 验收：临时在 config.toml 设置 `phase_models` 含 `preprocessing: deepseek-v4-flash`，打印 `get_phase_llm("preprocessing").default_model` 应为 flash；移除后回退 pro

**A2. 防御性解析**
- config.toml 的 `ui_phase_models` 是 JSON 字符串，可能有解析失败（旧格式/手改损坏）。解析失败时 log warning 并继续走 ui-settings.json 路径，不抛异常。

### Phase B：预处理步骤并行化

**B1. step3 与 step4 并行**
- 文件：`praxic/core/question_preprocessing.py`
- 位置：`preprocess()` 方法
- 做法：step3（意图矛盾）与 step4（预设审查）互不依赖（都只依赖 step1 的 task_nature/complexity），用 `asyncio.gather` 并行执行：

```python
# 替换现有的串行调用
if complexity != "simple" and do_step4:
    step3_task = asyncio.create_task(self._step_contradiction_in_intent(question, task_nature, _ctx_prefix))
    step4_task = asyncio.create_task(self._step_premise_audit(question, task_nature, _ctx_prefix))
    step3, step4 = await asyncio.gather(step3_task, step4_task)
elif complexity != "simple":
    step3 = await self._step_contradiction_in_intent(question, task_nature, _ctx_prefix)
    step4 = {"questionable_premises": [], "overlooked_factors": []}
else:
    step3 = {"contradiction_in_question": ""}
    step4 = {"questionable_premises": [], "overlooked_factors": []}
```

注意：`do_step4` 的计算依赖 step1 结果，必须在 gather 之前完成；保持现有条件逻辑（simple 任务跳过 step3，`_STEP4_SKIP_TASK_TYPES` 跳过 step4）不变。

**B2. （可选，B1 验证有效后做）step3+4+5 合并为一次调用**
- 把 `_STEP3_CONTRADICTION_IN_INTENT_PROMPT`、`_STEP4_PREMISE_AUDIT_PROMPT`、`_STEP5_STRUCTURE_PROMPT` 合并为一个 prompt，一次调用输出 `contradiction_in_question + questionable_premises + overlooked_factors + 全部 step5 字段`。
- 收益：预处理从 3 次调用降为 2 次（step1 + 合并步）。
- 风险：单个 prompt 变长，输出变多；需要保持 JSON 解析兼容。若 B1 后耗时已达标，此步可延后。

### Phase C：推理控制（配参数，低风险）

**C1. openai_compatible 透传 reasoning 控制参数**
- 文件：`praxic/llm/openai_compatible.py`
- 位置：`call()` 与 `stream()` 的 params 组装处
- 做法：支持从 kwargs 透传 `reasoning_effort`（low/medium/high）或 `enable_reasoning`（bool）。DeepSeek 若支持则透传；不支持时由 provider 忽略或报错后降级（沿用现有降级模式，参考 practice 的 `_looks_like_unsupported_response_format` 思路，捕获参数不支持错误后去掉该参数重试一次）。
- 注意：**不改变默认行为**，只有显式传参时才启用。

**C2. 预处理步骤默认不启用深度推理**
- 文件：`praxic/core/question_preprocessing.py`
- 位置：`_call_step()` 或各 step 的调用处
- 做法：`_call_step` 调用 `self.llm.call` 时默认传 `reasoning_effort="low"`（或等效参数），让分类/审查类小任务不做深度推理，避免 reasoning 耗尽 max_tokens。若 provider 不支持则自动降级（C1 的机制）。

### Phase D：矛盾分析瘦身（可选，观望）

- 文件：`praxic/core/contradiction.py`
- 背景：矛盾分析单次 85s，大头是 system_model 全量 JSON 输出 + 推理。
- 做法（任选其一，先测量再决定）：
  - D1：为实践导向任务限制 system_model 的 elements/relationships 数量上限（如 elements ≤ 5）
  - D2：矛盾分析 prompt 中要求输出紧凑 JSON（字段不省略但描述限长）
- 验收：对比改动前后单次矛盾分析耗时。若 85s 主要来自推理而非输出长度，D2 无效，应优先 C 类推理控制。

## 验收标准

1. `python -m pytest -q` 全部通过，`python -m compileall -q praxic` 通过
2. 单元测试：mock LLM 验证 step3/step4 并行（两次调用同时发出，gather 后结果正确）；验证 A1 的模型覆盖优先级（config.toml vs ui-settings.json）
3. 手工/脚本验证：`python -m praxic run "测试问题" --mode fast` 观察日志，预处理阶段总耗时 ≤ 15s（原 ~45s）；`question_preprocessing.done` 日志的 intent/task_nature 与串行版结果一致（抽样比对 3 个问题）
4. 回归：预处理各 step 的 fallback 路径（LLM 失败返回 default_result）仍然工作
5. 真实验收脚本 `scripts/verify_practice_real.py` 的 RecordingLLM 记录中，`llm_calls` 总数下降（至少减少 step3/step4 串行等待时间）

## 约束

- 不删除决策兼容层，不改认知循环阶段结构
- 不引入新依赖
- 不改动 `praxic/web` 前端
- 默认行为保持不变：所有优化在未配置/未传参时与现状等价
- 提示词保持中文，风格与现有 harness 一致
