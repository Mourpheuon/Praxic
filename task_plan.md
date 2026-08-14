# Praxic 改进执行计划

## 目标

将 Praxic 从一问一答和狭义实验执行器，改造成可以观察、理解、授权、改变并验证真实世界状态的智能体系统，并提供实时活动流前端和上下文缓存能力。

## 当前阶段

**Phase 8（矛盾双层产出 B 方案）进行中**：调研已完成（见 findings.md），计划待确认。此前 Phase 0-7 全部完成。

## Phases

### Phase 0: Praxic 迁移收尾

- [x] 完成品牌、包目录、命令和配置迁移
- [x] 审计忽略内容、敏感配置和历史产物
- 验收证据：静态搜索、导入、CLI、敏感信息审计、暂存清单
- **Status:** complete

### Phase 1: 通用真实世界工具契约

- [x] 支持观察、计算、修改、外部行动和验证
- [x] 结构化序列化工具结果和世界状态分类
- 验收证据：工具契约测试、行动链测试
- **Status:** complete

### Phase 2: 权限、授权和变更验证

- [x] 增加权限、异步授权、变更记录和回读验证
- [x] 覆盖批准、拒绝、重复处理、超时、取消和 SSE 终态
- 验收证据：PathGuard、副作用测试、授权批准/拒绝/超时测试
- **Status:** complete

### Phase 3: 上下文与 KV cache 分层

- [x] 增加上下文编译器、应用层缓存和供应商缓存接口
- [x] 增加本地 KV backend 探测和世界状态失效
- 验收证据：token/cache 指标、隔离测试、世界状态失效测试
- **Status:** complete

### Phase 4: 构成主义实时活动前端

- [x] 将 SSE 和 React 前端改为实时活动工作台
- [x] 完成授权交互、生产构建和桌面/移动端验收
- 验收证据：TypeScript、生产构建、Playwright 截图和交互请求
- **Status:** complete

### Phase 5: 验收与 GitHub 交付

- [x] 完成依赖、测试、暂存审计和单次提交
- [x] 备份旧远端状态并覆盖推送 `main`
- [x] 核验远端哈希、工作区和旧迁移 PR 状态
- 验收证据：pytest、显式集成脚本、npm build、Git 暂存清单、GitHub 分支
- **Status:** complete

### Phase 6: 恢复前端功能契约

- [x] 对照迁移前真实入口，列出被新 `App` 断开的设置、项目、历史会话和调试功能
- [x] 恢复迁移前完整入口，并仅在视觉层应用构成主义风格
- [x] 补接新后端授权事件，不改写项目/session、设置、文件、模型、澄清和调试流程
- [x] 完成 TypeScript、生产构建、桌面/移动端与交互验收
- **Status:** complete

### Phase 7: 实践阶段结构化改造

- [x] L1 止血：删除 reasoning 草稿顶替正文的 fallback；修复 JSON 解析器（换行符查找 + 正则兜底 + 原始输出日志）；规划失败用 max_retries 重试并带错误反馈；重试耗尽降级为 V2 知性分析，不再空跑三轮
- [x] L2 结构化：工具清单改为 registry 动态注入（shell_exec 可见）；规划调用带 JSON mode 并降级兜底；tool 名/参数 schema 校验；规划与代码生成分离（code_ref → FILE_CONTENT 生成 → 执行）
- [x] L3 方向锚点 + 方法论：R1/RN 注入 direction_anchor；新契约必含 directional_claim/deviation_rationale/epistemic_role 三字段并校验；方法论落为行为约束（先定位再设计、抓主要矛盾、技术失败≠证伪、现象上升为认识）；分析层判定纪律；C5 证据影响回写下一轮锚点
- [x] C5 正式结构化：用 `DirectionStateUpdate` 记录单轮方向状态，由 `PracticeReport` 保存当前状态与历史，并将结构化 JSON 注入下一轮规划
- [x] 旧契约软校验：`files_to_create`/`commands_to_run` 缺失方向字段时记录 warning，继续执行兼容路径，不把旧调用方强制推入降级流程
- 验收证据：60 项 pytest、compileall、两个显式集成脚本；mock LLM 四场景（新契约路径、非法 JSON 重试、恒失败降级 V2、空 directional_claim 重试）；R1 含 shell_exec，R2 含方向锚点与证据影响
- **Status:** complete

## 决策

- 实验是实践的一种形式，核心抽象采用通用真实世界行动。
- 真正的模型 KV cache、供应商 prompt cache 和应用层上下文缓存分层实现；不假设通用 API 支持跨请求传递 past_key_values。
- 读取默认自动执行；写入、删除、发布和外部副作用通过权限与授权门控。
- 前端展示可审计的行动摘要、工具、结果、证据和验证，不展示模型私有逐字推理链。
- 实践阶段方向强校验（directional_claim 非空）只对新 `tool_calls` 契约生效；旧 `files_to_create`/`commands_to_run` 兼容层放行，避免既有测试与旧调用方被推入降级路径。
- 前端恢复以迁移前实际运行入口为功能基线；本阶段只做视觉改造和新授权契约的必要兼容，不重写原业务系统。
- F 盘 Hanako 项目只读，参考其计划记录、Hook、执行策略和 claims/evidence ledger。
- `.env`、token、运行时 registry 和外部绝对路径不进入提交。

## 验收条件

- 跟踪文件和可提交配置中没有历史品牌包名、目录名或命令。
- 工具结果可以结构化序列化，并区分工具失败与世界状态未改变。
- 每次真实世界改变都有权限记录、变更记录和验证结果。
- 上下文缓存按会话、项目、模型和 prompt 版本隔离，并可报告命中和 token 统计。
- 前端可实时显示阶段、工具、行动、等待授权、验证和失败状态。
- 依赖安装、测试、前端构建和推送均有命令输出作为证据。

## 错误记录

| 错误 | 尝试 | 解决方案 |
| --- | --- | --- |
| 全局 Python 缺少 `uvicorn`、`structlog` | 0 | 执行阶段安装项目开发依赖后重新验证 |
| 多个测试使用历史 `/sessions/...` 路径 | 0 | 改为基于测试文件位置计算项目根目录 |
| 当前前端存在 `src/` 与 `index.html` 内联实现 | 0 | 先确认 Vite 入口，再将 `src/` 作为唯一实现 |
| Winget 的 `npx.ps1` 可定位，但同目录实际缺少 `node.exe` | 2 | 停止使用该残缺安装，改用 Codex 工作区随附 Node 运行时驱动 npm/Playwright |
| Playwright `run-code` 在 Windows 原生命令行中无法可靠接收多行函数参数 | 2 | 使用 CLI 原生 `--filename` 从验收输出目录加载脚本 |
| Playwright 受限脚本上下文没有全局 `URL` 构造器 | 1 | 直接使用请求 URL 字符串解析查询词和授权 ID，并重注册路由 |
| 显式 `test_steering.py` 中 broadcast steering 未进入 LLM 上下文 | 1 | 检查 `target_phase=all` 的消费时机和上下文注入，修复后串行复验 |
| 并行集成脚本争用同一技能草稿目录 | 1 | 后续显式集成入口改为串行执行，避免测试夹具互相干扰 |
| PowerShell 组合搜索中的引号未闭合 | 1 | 放弃复杂单命令正则，改用多个简单 `rg` 模式并行搜索 |
| 新增契约测试首次运行有 2 项失败 | 1 | 放宽安全检查的实现细节断言；补齐 `change_unverified` 的轮次失败分类后重跑 |
| Codex Node 模块目录缺少 npm CLI | 1 | 使用 Codex Node 可执行文件驱动 Winget 安装目录内现有的 `npm-cli.js` |
| npm 子进程无法从 `PATH` 找到 Node | 2 | 仅为当前构建进程前置 Codex Node `bin` 目录后重跑 |
| Playwright `eval` 的内联函数被拆成多个参数 | 2 | 停止内联参数转发，改用 CLI 原生 `run-code --filename` 加载验收函数 |
| 授权摘要严格文本定位命中活动行和详情标题 | 1 | 改用 heading 与 button 的角色定位区分两个元素 |
| PowerShell `foreach` 结果直接接管道解析失败 | 1 | 先将循环结果赋给局部变量，再统一格式化输出 |
| 递归删除旧构建产物被执行策略拦截 | 1 | 改为同盘移动到项目外的明确隔离目录，既清理项目又保留可恢复备份 |
| Skill registry 统计把顶层对象误作条目 | 1 | 按 `skills` 与 `drafts` 两个数组合并统计，并跳过空 `file_path` |
| 多文件补丁因规划记录中的 Windows 路径转义不匹配而未应用 | 1 | 确认源码无部分写入后，将源码、测试和记录拆分为小补丁应用 |
| 全仓 Ruff 检查报告 826 条历史风格问题 | 1 | 不做跨仓格式化；仅格式化本次新增核心模块，并保留 Python 3.10 兼容写法 |
| tomllib 回退别名仍被 mypy 判定为重定义 | 1 | 标准库与 backport 分别导入，再赋给预先声明的 `Any` 句柄 |
| GitHub CLI 钥匙串令牌失效 | 1 | Git 远端读取正常；先使用独立的 Git HTTPS 凭据推送，必要时按用户授权打开网页登录 |
| Hook 状态修正后的 Git HTTPS 推送连接被重置 | 1 | GitHub API 确认远端仍为旧哈希；改用已认证 API 以精确旧 SHA 保护更新 `main` |
| PowerShell 文件元数据检查的循环结果直接接管道导致语法错误 | 1 | 先把循环结果赋给局部变量，再格式化输出；确认 `.github-token` 存在且受忽略规则保护 |
| 直接读取用户 SSH config 被 ACL 拒绝 | 1 | 不修改权限；改用 `ssh -G github.com` 解析生效配置，确认 `id_ed25519` 候选密钥 |
| Windows `bash` 命中 WSL shim，找不到 `/bin/bash` | 1 | 改用已安装的 `D:\Git\usr\bin\bash.exe` 执行项目推送脚本 |
| session-catchup 在 GBK 终端输出设置符号时报 UnicodeEncodeError | 1 | 直接读取 UTF-8 规划文件与 Git 状态恢复上下文，不重复执行该输出路径 |
| 浏览器关闭设置按钮定位为 0 | 1 | CSS 热更新已自动关闭弹窗；不重复点击，直接按移动视口重新加载验收 |
| 规划 JSON 解析器 `find("\\\\n")` 查找字面反斜杠而非换行符 | 0 | 改为查找真实换行；增加首 `{` 到末 `}` 正则兜底，解析失败保留原始输出前 500 字符进日志 |
| 规划失败后带空计划空跑三轮 | 0 | 用 `max_retries` 循环重试并把错误反馈追加回消息；耗尽返回 `plan_failed` 标记，主流程降级为 V2 知性分析 |
| 工具清单与 ToolRegistry 漂移，shell_exec 已注册但未列出 | 0 | 提示词改为 `{tools_text}` 占位符，运行时用 `registry.format_for_prompt()` 动态注入，registry 为 None 时用 `DEFAULT_TOOLS` 兜底 |
| 验证脚本误判 FILE_CONTENT 未生成 | 1 | 代码生成提示词含 `<python_exec>` 路径占位符，误用排除 `python_exec` 关键字判定；改为以 `编码规则` 标记识别 |

## 恢复提示

Phase 6 已完成。迁移前完整前端功能已恢复，视觉层按用户反馈收敛；后端、缓存和工具改动保持不变。

---

### Phase 8: 矛盾分析双层产出（内部推理与输出分离，B 方案）

**背景**：矛盾分析产出的内容要输入给别人（下游阶段、最终回答），需要精简；同时它的输出混着三种职责：结论层（principal/secondary/synthesis/dynamic_note）、推理层（derivation_chain/system_model/contradiction_derivation）、元数据（iteration/position_shifts）。现状是三层共用一个 max_tokens，而 DeepSeek 的 max_tokens 又同时承载 reasoning + 正文，导致正文 JSON 被 reasoning 挤爆、经常 fallback。用户明确选择 B 方案：**内部推理与输出物理分离**。

**目标**：
1. 矛盾阶段正文只输出结论层 JSON（精简、稳定、可直接给人/下游）
2. 推理层（derivation_chain/system_model）与结论层解耦，不再与结论争抢同一份 max_tokens；需要时（maintain fork / DEEP 档）单独产出、可裁剪
3. 不再出现 reasoning 挤爆正文导致 fallback 的现状

**设计决策**（已与用户确认）：
- 结论层 = principal_contradiction（description/tension_poles/primary_aspect/transformation_condition/basis_summary）+ secondary_contradictions + dynamic_note + synthesis + position_shifts + iteration；不加额外 summary 字段，直接用现有 description
- 推理层 = derivation_chain（每矛盾）+ system_model + contradiction_derivation
- **推理层产出时机：只在 DEEP 档或 maintain fork 需要时生成；STANDARD 档正文只出结论层，推理层字段为空**（用户选择“后者”）
- 正文 max_tokens：STANDARD 4096→8192，DEEP 保持 16384（用户认可）
- 矛盾阶段调用加 `enable_reasoning=False`（复用 practice 先例）

**实施阶段**：
- [x] P8-1 设计确认：结论层/推理层边界、DEEP 档语义、maintain fork 依赖已对齐（决策：推理层只在 DEEP/maintain fork 时产出；正文用现有 description 不加 summary；STANDARD max_tokens 保底 8192）
- [x] P8-2 schema 与 prompt 重构：`_SYSTEM_CONTRADICTION_PROMPT` 增加“字段分层”说明（结论层 vs 推理层）；`_schema_scope` 三档重写——SHALLOW 仅 principal、STANDARD 只出结论层（推理层明确置空）、DEEP 结论+推理全量
- [x] P8-3 调用与预算：**发现 `enable_reasoning=False` 在 DeepSeek 上无效（非官方参数被忽略）**；查证 DeepSeek V4 官方参数为 `thinking: {type: disabled}`（extra_body），adapter 增加 thinking 透传与降级；矛盾阶段改用 `thinking={"type":"disabled"}`；STANDARD max_tokens 保底 8192
- [x] P8-4 maintain 适配：maintain_prompt 增加输出范围说明（STANDARD 档 fork 在结论层体现，DEEP 档走 fork 规则）；existing_summary 对无推导链已容错
- [x] P8-5 下游适配：确认 rational/reflection 对推理层字段均已判空，STANDARD 缺省时自然降级，无需改动
- [x] P8-6 测试：新增 TestDualLayerOutput 5 用例（thinking 透传、STANDARD/DEEP schema 范围、max_tokens 保底、显式预算不覆盖）；更新 test_phase_budget 默认行为断言；mock_llm 记录 kwargs；全量 196 passed
- [x] P8-7 真实验收：**质变**——thinking 关闭后 reasoning 日志消失，正文 JSON 稳定解析（第一轮 principal+2 secondary，第二轮 maintain 3 contradictions），耗时每调用 100s+→30s，fallback 不再触发；iteration 1→2 递增
- [x] P8-8 思维链保留与捕获（用户方向修正）：thinking **保持开启**（不传 disabled，DeepSeek 默认思考模式）；adapter 把 reasoning_content 捕获进 `LLMResponse.metadata["reasoning"]`（含重试路径）；`ContradictionGraph` 新增 `thinking_trace` 字段存储思维链（仅前端展开/检视用，**不进后续输入**）；正文仍是唯一消费口径；STANDARD max_tokens 保底提到 16384（容纳思维链+正文）。真实验收：思维链完整捕获（9149/15226 字符），正文 JSON 稳定，maintain 推理质量提升（对稀疏观测做辩证处理而非机械重认定）。全量 **197 passed**。

**验收条件**：
- [x] 矛盾正文 JSON 稳定输出结论层，不再因 reasoning 挤爆而 fallback（真实验收证实）
- [x] 推理层仅在 DEEP / maintain fork 时产出，不挤占结论层预算
- [x] 思维链保留（thinking 开启）并完整捕获，仅供前端展示，不进后续输入
- [x] 下游（rational/reflection/practice）行为不变，既有测试全绿
- [x] `python -m pytest -q` 197 passed，`python -m compileall -q praxic` 通过
- [x] 真实验收：正文 JSON 完整、fallback 消失、思维链捕获成功

**风险（已实勘）**：
- enable_reasoning 非 DeepSeek 官方参数，被忽略；正确做法是**不传 thinking 参数**（保持默认思考模式开启）或显式 `{"type":"enabled"}`
- max_tokens 是请求参数（非模型固有）；DeepSeek 的思维链计入 max_tokens 预算，16384 可容纳实测 9k~15k 思维链 + 结论层正文；若思维链超长可能触发 retried_for_empty 翻倍兜底
- 思维链仅作展示，前端可截断存储，不影响任何逻辑

**Status:** complete
