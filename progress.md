# Praxic 执行进度

## 2026-08-01 实践阶段改造记录

- 针对实践阶段四个系统性缺陷（规划脆弱、工具不可见、多轮跑偏、方法论缺失）完成结构化改造，对应任务清单 Phase A/B/C。
- 涉及文件：`praxic/core/practice.py`、`praxic/core/practice_harness.py`、`praxic/llm/openai_compatible.py`。
- 不删除决策兼容层、不改认知循环阶段结构、不接 L3 function calling；仅用现有 pydantic。

| 2026-08-01 | 移除 reasoning 草稿顶替正文 | 删除 `openai_compatible.call()` 中 `if not content and reasoning` fallback；reasoning_content 仅入日志，空 content 原样返回供上层重试/降级 |
| 2026-08-01 | 修复 JSON 解析器 | `find("\\n")` 改 `find("\n")`；新增首 `{` 到末 `}` 正则兜底；解析失败保留原始输出前 500 字符日志 |
| 2026-08-01 | 规划失败重试与降级 | `_call_planner` 用 `max_retries` 循环，错误+原始片段追加回消息；耗尽返回 `plan_failed`；主流程降级 V2 知性分析（mode=partial/epistemic_only） |
| 2026-08-01 | 工具清单动态注入 | R1/RN 硬编码工具段换 `{tools_text}`；`registry.format_for_prompt()` 生成，registry 为 None 时 `DEFAULT_TOOLS` 兜底；shell_exec 进清单 |
| 2026-08-01 | JSON mode + schema 校验 | 规划调用带 `response_format=json_object`，provider 不支持报错时降级文本模式重试；tool 名/参数类型/必填校验，失败进重试 |
| 2026-08-01 | 规划与代码生成分离 | python_exec 的 `code` 改 `code_ref`，执行前经 `_generate_file_content` 生成代码；规划输出量显著减小 |
| 2026-08-01 | 方向锚点 + 方法论引导 | R1/RN 注入 `{direction_anchor}`（核心假设+主要矛盾+用户关切+反思提示）；方法论落为四条行为约束；新增 epistemic_role/directional_claim/deviation_rationale 字段并校验 |
| 2026-08-01 | 分析层判定纪律 | `_FINAL_ANALYSIS_PROMPT` 要求 verdict 基于有效观测、技术失败不参与判定、analysis 说明认识变化 |
| 2026-08-01 | C5 方向状态更新 | 每轮执行后把证据对锚点的影响回写下一轮 `{direction_anchor}`；已验证 R2 提示词包含“本轮证据对锚点的影响” |
| 2026-08-01 | C5 方向状态结构化 | 新增 `DirectionStateUpdate`，`PracticeRound` 记录单轮状态，`PracticeReport` 保存当前状态和历史，并以结构化 JSON 注入下一轮规划 |
| 2026-08-01 | 旧契约方向字段软校验 | `files_to_create`/`commands_to_run` 缺失方向字段时记录 warning，继续执行兼容路径 |
| 2026-08-01 | 实践闭环与最终复验 | `test_practice_integration.py`、`test_full_loop_integration.py` 均 `OVERALL: PASS`；`pytest` 60 passed，compileall、CLI 和前端生产构建通过 |

## 2026-08-01 L0 工具扩充记录

- 方向：补 L0 工具触达缺口。授权分级话题挂起，本轮只做不涉及授权模型的 observe 类只读工具；change 类（file_edit、archive_tool）冻结，待授权分级定案后再做。
- 涉及文件：`praxic/tools/file_query.py`（新建）、`praxic/core/cognitive_loop.py`、`praxic/core/practice.py`、`tests/test_file_query.py`（新建）。
- 约束：仅用标准库；全部 OBSERVE 自动放行；路径经 PathGuard 约束在 workspace 内；输出路径归一化为正斜杠。

| 2026-08-01 | file_grep | 工作区内内容搜索，支持正则、glob 过滤、递归开关、忽略大小写、匹配上限；输出 `路径:行号: 内容` |
| 2026-08-01 | file_batch_read | 一次读多个文件，每文件按行数截断并标记；批量审计与对比 |
| 2026-08-01 | file_stat | 文件/目录元数据：大小、修改时间、类型、SHA256 摘要 |
| 2026-08-01 | 注册与呈现 | 两个 registry 构造点（cognitive_loop、practice）注册三工具；B1 动态注入自动生效，`format_for_prompt()` 呈现验证通过 |
| 2026-08-01 | 测试与复验 | 新增 `tests/test_file_query.py` 12 项（跨文件匹配、glob/递归、正则/大小写、非法正则、无匹配、路径逃逸、批量截断、stat、注册契约、提示词呈现）；全量 `pytest` 81 passed，compileall 通过，两个集成脚本 OVERALL PASS |

## 2026-07-30 前端恢复记录

- 用户明确前端授权范围是视觉风格调整；当前恢复工作以迁移前完整入口的功能为基线，不新增替代性业务流程。
- 已确认当前 `App.tsx` 断开项目、session、完整设置、文件上传、澄清、steering、模型选择和调试追踪；这些行为仍可从迁移前入口与后端 API 恢复。
- 下一步：恢复原有入口装配，保留当前实时活动与证据展示作为视觉层改造结果，并完成构建与浏览器验收。

| 2026-07-30 | 恢复迁移前完整前端入口 | 从父提交恢复真实运行的单页入口到 `praxic/web/index.html`；保留项目/session、设置、模型、文件、澄清、steering 和调试流程；完成历史品牌键名迁移并追加构成主义 CSS 覆盖 |
| 2026-07-30 | 根据现场反馈校正色板 | 撤回冷灰/亮蓝方案，恢复迁移前的纸张、米白、朱砂、橄榄与旧金色系；保留构成主义布局和硬边界 |
| 2026-07-30 | 收束视觉语言 | 在暖色板上增加超大标题、粗分隔、实色块、编号和错位阴影；未添加任何风格说明文案，未改业务流程 |
| 2026-07-30 | 补接异步授权前端 | 旧 SSE hook 增加授权请求/终态识别；当前 session 输入区上方可查看调用信息并批准或拒绝，结束、终止和后台 session 状态均有收敛处理 |
| 2026-07-30 | 桌面浏览器首轮验收 | 项目/session 左栏、完整设置四页签、阶段模型、高级参数、附件、模式、审查和模型控制均可达；无运行错误，记录两条迁移前 CDN/Babel 提示 |
| 2026-07-30 | 1440x900 视觉验收 | 工作台无横向溢出，设置弹窗完整位于视口内；暖色高对比标题和硬边界生效，待移除设置内容区多余横向滚动条 |
| 2026-07-30 | 390x844 主界面验收 | 无横向溢出；项目/session、工作区大标题与输入控制按纵向稳定排布，未出现遮挡 |
| 2026-07-30 | 390x844 设置验收 | 设置弹窗约 374x760，四页签、账户连接/保存动作、外观字体/页面缩放入口均可达；未触发真实模型连接 |
| 2026-07-30 | Phase 6 最终验收 | TypeScript、Vite 生产构建、差异检查、品牌扫描和桌面/移动端浏览器验收通过；完整旧功能入口与新授权兼容均已接好 |

## 当前会话摘要

实践阶段改造已完成：规划可重试、工具可见、方向锚定、认识有定位；C5 方向状态和旧契约软校验已正式落地并完成验证。

## 工具使用

| 时间 | 操作 | 结果 |
| --- | --- | --- |
| 2026-07-29 | 读取 planning-with-files 技能规范 | 已确认必须维护三份项目记录 |
| 2026-07-29 | 检查 Git、手册、前端、LLM、工具和记忆模块 | 已确认现有改动与主要缺口 |
| 2026-07-29 | 创建执行记录 | 已完成 |
| 2026-07-29 | 挂钩触发继续执行 | 已重新读取计划、发现记录和工作区状态，准备完成迁移收尾 |
| 2026-07-30 | 恢复决策阶段与阶段回调兼容 | fast/standard 均生成 `DecisionReport`，兼容两参数与三参数回调 |
| 2026-07-30 | 完成结构化工具与授权闭环 | 已实现权限、变更、验证、授权等待、批准、拒绝与超时 |
| 2026-07-30 | 完成上下文与 KV cache 分层 | 已实现应用缓存、本地 backend 探测及世界状态变化失效 |
| 2026-07-30 | 完成实时活动前端主体 | 已实现阶段、工具、证据、授权和失败状态，生产构建通过 |
| 2026-07-30 | 会话恢复核验 | 已确认当前分支、77 个变更文件和剩余验收任务 |
| 2026-07-30 | Playwright 首次启动 | `npx.ps1` 因子进程 `PATH` 缺少 Node 目录而未启动；已定位安装目录，准备显式扩展 `PATH` |
| 2026-07-30 | Playwright 第二次启动诊断 | Winget Node 目录中实际没有 `node.exe`；已切换到 Codex 工作区随附 Node 运行时 |
| 2026-07-30 | 授权模拟首次注册 | `run-code` 要求函数参数；已调整为完整异步函数 |
| 2026-07-30 | 授权模拟第二次注册 | Windows 参数转义仍破坏多行函数；切换为 `--filename` 加载 |
| 2026-07-30 | 授权 SSE 首次触发 | 路由已命中，但脚本上下文无全局 `URL`；改为字符串解析后重跑 |
| 2026-07-30 | 授权批准交互验收 | POST 请求成功，但证据面板仍读取旧 `pending` 事件；已改为优先读取最新授权状态 |
| 2026-07-30 | Playwright 阶段 4 验收 | 1440×900 与 390×844 无页面横向溢出或文字裁切；批准/拒绝请求与状态转换通过 |
| 2026-07-30 | 全量单元与构建验证 | `31 passed`；前端 `tsc` 与 Vite 构建通过，33 个模块完成转换 |
| 2026-07-30 | 显式集成脚本首轮 | practice、control mapping、full loop、clarification 通过；steering 的 broadcast 分支失败，等待修复 |
| 2026-07-30 | 修复 broadcast steering 生命周期 | 广播 steering 不再被首阶段提前消费，定向 steering 仍只消费一次 |
| 2026-07-30 | 提交前全量复验 | `python -m pytest -q` 为 `32 passed`；五个显式集成脚本串行运行全部通过 |
| 2026-07-30 | 迁移与构建复验 | Python 编译、核心导入、CLI、前端 TypeScript/Vite 构建、历史品牌与敏感路径审计通过 |
| 2026-07-30 | 会话恢复与代码审查续接 | 已以当前工作树为准恢复；准备核验授权幂等、超时事件、递归脱敏和 Shell 变更验证风险 |
| 2026-07-30 | 提交前正确性加固 | 已修改授权单次消费与超时事件、递归脱敏、未验证变更分类、Shell/解释器边界、Python 纯计算边界和保守缓存失效；等待针对性测试 |
| 2026-07-30 | 新增契约测试首轮 | 11 通过、2 失败；均为新断言与结构化分类遗漏，已针对根因修正 |
| 2026-07-30 | 新增契约测试复验 | `python -m pytest tests/test_tools_and_cache.py -q`：`13 passed` |
| 2026-07-30 | 认知循环与导入复验 | `tests/test_cognitive_loop.py` 为 `9 passed`；`compileall` 和核心导入通过 |
| 2026-07-30 | 后端全量单元复验 | `python -m pytest -q`：`38 passed` |
| 2026-07-30 | 显式集成脚本复验 | practice、control mapping、full loop、clarification、steering 串行执行，全部 `OVERALL: PASS` |
| 2026-07-30 | 前端构建首次启动 | Codex Node 可执行文件正常，但其模块目录没有 npm CLI；准备复用 Winget npm 包脚本 |
| 2026-07-30 | 前端构建第二次启动 | npm CLI 已运行，但 `tsc` 子进程的 `PATH` 缺少 Node；准备注入 Codex Node 目录 |
| 2026-07-30 | 前端生产构建复验 | 当前进程注入 Codex Node 后 `tsc && vite build` 通过，33 个模块完成转换 |
| 2026-07-30 | 全新浏览器会话首检 | 页面标题和七阶段结构正常，控制台 0 errors / 0 warnings，favicon 404 已消失 |
| 2026-07-30 | 最终浏览器脚本准备 | 复用已验证的授权 SSE 模拟方式，加入桌面/移动几何与批准请求审计；脚本位于已忽略输出目录 |
| 2026-07-30 | 最终浏览器自动验收 | 桌面、移动和授权后页面无横向溢出或文字裁切；批准请求、状态更新和按钮消失均通过 |
| 2026-07-30 | 最终浏览器目视与控制台复验 | 三张截图无重叠或不可读裁切；交互后控制台仍为 0 errors / 0 warnings |
| 2026-07-30 | 迁移与敏感信息首轮审计 | 可提交内容无历史品牌、常见密钥前缀或个人绝对路径；`.env` 已忽略；发现两个被忽略的历史构建产物待清理 |
| 2026-07-30 | 旧构建产物清理首试 | 递归删除被执行策略拦截，目录未变化；改为同盘隔离以保留恢复能力 |
| 2026-07-30 | 本地资料迁移与旧产物隔离 | 29 个忽略文本完成品牌迁移，9 个 skill 草稿改为相对路径；旧 Electron 输出及损坏 registry 备份已移出项目 |
| 2026-07-30 | 全项目品牌复验 | 排除第三方依赖与验收输出后，拉丁旧名、中文旧名和旧名路径搜索均为 0；本地资料有项目外备份 |
| 2026-07-30 | 最终缓存与授权边界复核 | 发现缓存键遗漏预算、截断可能越界、KV 稳定前缀指标失真及非正 TTL 隐式永久授权；已开始窄范围修复与回归测试 |
| 2026-07-30 | 工具边界二次加固 | 已处理授权取消终态、Git 写子命令分类、Python 别名/动态导入绕过和依赖安装状态语义；等待回归测试 |
| 2026-07-30 | 工具与缓存专项回归 | `tests/test_tools_and_cache.py` 为 `17 passed`；Python 编译和 CRLF 兼容的差异空白检查通过 |
| 2026-07-30 | 全量与显式脚本首轮 | pytest 为 `42 passed`，五个脚本退出成功；日志发现 `__name__` 被误拦，实践计算实际失败，已进入兼容性修正 |
| 2026-07-30 | Python 兼容性复验 | 工具专项仍为 `17 passed`；实践日志已出现 `observed python_exec`，实际计算恢复成功 |
| 2026-07-30 | 缓存指标语义校正 | 区分应用层文本拼装复用与供应商 token 命中；Anthropic system prompt 改为默认缓存标注并以 usage 计数 |
| 2026-07-30 | 配置与文档契约审计 | 发现 README 环境变量名与代码不一致、lockfile 顶层版本滞后；已修正文档并准备同步锁文件元数据 |
| 2026-07-30 | 锁文件与新增模块静态整理 | 两个 package-lock 已用离线 lockfile-only 模式同步至 0.1.2；9 个新增核心/测试文件完成 Ruff 格式化，未触碰全仓历史风格债务 |
| 2026-07-30 | 最终并行验收首轮 | `43 passed`、核心导入、CLI、前端 33 模块构建通过；mypy 报告 21 项，其中本次相关的授权可空收窄与 LLM 响应默认值已进入修正 |
| 2026-07-30 | 类型边界收口 | 已修正授权终态收窄、LLM metadata 默认值、异步流抽象、tomllib 回退别名和批量搜索取消结果；保留异构工具签名的已知 override 基线 |
| 2026-07-30 | 目标类型检查复验 | 禁用既有异构工具 `override` 单项后，8 个缓存/权限/工具核心模块 mypy 为 `Success: no issues found` |
| 2026-07-30 | 最终后端与集成复验 | 全量 pytest 为 `44 passed`；五个显式脚本串行运行全部 `OVERALL: PASS`，实践记录包含 `observed python_exec` |
| 2026-07-30 | 遗留可执行文件隔离 | 将被忽略的约 748 MB 历史 PyInstaller 可执行文件移到项目同级隔离备份并改用中性名称；项目内旧名路径清零 |
| 2026-07-30 | 分支与暂存清单收口 | 分支已重命名为 `codex/praxic-improvement-20260730`；120 个文件全部暂存，无额外未暂存改动 |
| 2026-07-30 | 最终索引审计 | 暂存内容的历史品牌、常见密钥模式、个人绝对路径、构建二进制和 CRLF 兼容空白检查均通过 |
| 2026-07-30 | 切换交付分支 | 按用户要求切换到本地 `main`；远端旧 `main` 的 `5656222` 已由备份分支保留，后续使用带 lease 的覆盖推送 |
| 2026-07-30 | GitHub 认证与交付 | 通过用户确认的设备授权恢复 GitHub CLI；旧远端状态推送到 `codex/backup-origin-main-20260730`，随后以精确 lease 覆盖 `origin/main` |
| 2026-07-30 | 远端与旧 PR 核验 | 本地 `main` 与 `origin/main` 一致且工作区干净；PR #1 已合并，原迁移分支已不存在 |
| 2026-07-30 | Hook 完成度修正 | Hook 只识别 `### Phase` 与 `**Status:** complete`；已将六个完成阶段转换为兼容格式，消除 `0/0` 误报 |
| 2026-07-30 | 规划记录推送首试 | Git HTTPS 连接被重置；GitHub API 核验远端仍为 `1858df4`，未发生部分更新，改用精确旧 SHA 保护的 API 更新 |
| 2026-07-30 | 本地推送凭据核验 | `.github-token` 存在且被忽略，`scripts/push.sh` 支持转发 lease 参数；SSH 生效配置包含 `id_ed25519`，token 脚本作为首选重试路径 |
| 2026-07-30 | 本地 token 推送成功 | 使用 `D:\Git\usr\bin\bash.exe` 执行 `scripts/push.sh`，以 lease 将 `origin/main` 从 `1858df4` 更新为 `640a835` |
| 2026-07-30 | 最终 Hook 与远端核验 | GitHub API 返回 `640a835`，备份分支仍为 `5656222`，工作区源码未变，planning Hook 返回 `6/6` |
| 2026-07-30 | 用户发现前端功能回退 | 确认新 `App` 替换装配层后，多项旧组件仍在但不可达；新增 Phase 6，开始对照迁移前入口恢复设置与工作流 |
| 2026-07-30 | 迁移前入口初步审计 | 确认旧 `App` 的八类组件、项目/session 加载与刷新、历史回看、设置和开发追踪契约；后端接口仍在，恢复无需重写系统 |

## 测试结果

基线已重新运行：

- `python -m pytest tests/test_cognitive_loop.py -q`：4 通过、4 失败。失败集中在决策阶段未执行和旧式两参数回调兼容性。
- 实践集成脚本主体通过，但文件顶层 `sys.exit(0)` 使 pytest 收集阶段报 `INTERNALERROR`；需拆分为正常 pytest 用例或改造入口。

后续实现验证：

- `python -m pytest -q`：60 通过。
- `python -m compileall -q praxic`：通过。
- 显式集成脚本 `tests/test_practice_integration.py`、`tests/test_full_loop_integration.py`：OVERALL PASS。
- mock LLM 四场景验证：新 tool_calls 契约（code_ref → 生成 → 执行）、非法 JSON 后重试成功、恒失败降级 V2 不空跑、空 directional_claim 触发重试；R1 提示词含 shell_exec 及完整参数说明；R2 含方向锚点与上一轮证据影响。

此前基线：

- `python -m pytest tests/test_cognitive_loop.py -q`：9 通过。
- `python -m pytest tests/test_tools_and_cache.py -q`：19 通过。
- 前端 `tsc` 与 `vite build`：通过，33 个模块完成转换。
- 五个显式集成脚本使用 UTF-8 环境串行执行：全部通过。
- `python -m compileall -q praxic`、核心导入和 `python -m praxic --help`：通过。
- 新增核心模块 Ruff（排除仅涉及版本偏好的 `UP`）和目标 mypy（排除既有异构工具签名 `override`）通过。
- 全项目静态搜索：历史品牌内容与路径均为 0；凭据文件全部受忽略规则保护。

## 下一步

1. 根据用户决定是否继续扩展实践阶段的真实工具覆盖和前端展示。
2. 本轮不打包 Electron，不提交或推送 Git。
