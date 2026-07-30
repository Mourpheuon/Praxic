# Praxic 研究与发现记录

## 2026-07-30 前端入口审计结论

- 迁移前浏览器实际加载的是 `siwu/web/index.html` 中 2558 行的完整 React 单页实现；它包含项目与 session、重命名/删除、排序、历史回看、文件拖放、模型选择、运行中 steering、澄清、完整设置、版本/构建和阶段详情。
- 当前提交删除了该入口并用 326 行的新 `App.tsx` 替换；保留下来的 `src/components` 本来只是更早的简化实现，不能作为恢复基线。
- FastAPI 根路由直接读取 `praxic/web/index.html`，Vite 也以该文件为入口。因此从父提交恢复完整 HTML，再做品牌迁移和 CSS 覆盖，是保持原业务逻辑最小变更的路径。
- 新后端增加异步授权事件；恢复旧入口时只补接授权批准/拒绝这一项兼容逻辑，避免真实世界写操作永久等待。其余前端行为按迁移前实现保留。
- 视觉范围限定为构成主义色彩、排版、边界、布局密度和动效；不再替换原有信息架构或业务流程。若需要生成图标素材，先向用户提供 prompt。
- 完整入口恢复后，前端中的历史品牌文本扫描为 0；本地状态键、开发者模式键、模型选择键和 Electron bridge 已统一迁移为 `praxic`。
- 构成主义样式通过独立 CSS 层和少量视觉 class 挂载实现，原项目/session、设置、文件、模型、澄清与 steering 函数保持迁移前结构。
- 用户现场反馈冷灰、亮蓝与高饱和黄不如迁移前色板；视觉层已改回纸张米白、朱砂、橄榄和旧金，构成主义主要由排版、硬边界与信息结构承担。
- 用户进一步指定采用高对比的海报排版质感，但界面不出现风格说明词；已用超大标题、粗分隔、朱砂块面、编号和错位实色阴影表达，业务文案与信息架构不变。
- 浏览器桌面验收确认左栏项目/session、新建与排序、顶部设置入口、文件/模式/审查/模型输入控制均恢复；设置弹窗包含通用、外观、账户、关于、阶段模型和高级运行参数。
- 当前控制台仅有迁移前 CDN Tailwind 与浏览器 Babel 的生产提示，无运行错误；这两项属于恢复入口原有架构，后续可单独迁移，不能在本次视觉恢复中再次重写。
- 桌面截图显示主工作区暖色与高对比层级成立，设置弹窗仍保留旧式圆角，需在纯 CSS 层统一其边界和标题。
- 1440x900 浏览器几何检查：文档宽度等于视口宽度，工作台无横向溢出；左栏 306px，设置弹窗 560x560 且完全位于视口内。
- 设置弹窗统一后只剩内容区一条无意义的横向滚动条，使用局部 `overflow-x: hidden` 收敛，不影响构建日志等自身滚动区域。
- 390x844 移动端检查无文档横向溢出；项目/session 左栏改为顶部 287px 区域，标题工作区与 131px 输入控制均可见，视觉层级未遮挡交互。
- 移动端设置弹窗几何为约 374x760，四页签和保存区均在视口内；账户页的连接测试与保存配置按钮存在，外观页的字体和页面缩放入口存在，未触发真实连接测试。
- 最终 TypeScript、Vite 生产构建、CRLF 兼容差异检查和前端历史品牌扫描均通过；浏览器无运行错误，开发服务与 API 继续监听 5173/8000。

## 当前工作树

- 工作目录：项目根目录
- 分支：`main`
- 远端：`https://github.com/Mourpheuon/Praxic.git`
- 工作区干净，本地 `main` 跟踪 `origin/main`。
- Praxic 迁移、功能改进和规划记录已作为单次改进提交交付。

## 项目事实

- `praxic/tools/base.py` 和 `praxic/tools/registry.py` 已提供可序列化的结构化结果、权限记录、变更记录、回读验证和世界状态分类。
- `praxic/core/practice.py` 已消费决策行动项并保留旧位置参数兼容；决策阶段和两/三参数 `on_phase` 回调兼容已恢复。
- 授权流程会发出 `authorization_requested`，等待批准、拒绝或超时；批准后继续原工具调用，拒绝和超时不执行。
- API 已提供 `GET /api/v1/agent/authorizations` 与 `POST /api/v1/agent/authorizations/{request_id}`。
- `praxic/memory/context_cache.py`、`praxic/llm/cache.py` 和 `praxic/llm/kv_cache.py` 已实现分层缓存、隔离、运行时能力探测和世界状态变化失效。
- `praxic/web/src` 是唯一 Vite React 实现；根 HTML 已收敛为入口页。
- SSE 和前端已支持阶段、工具、行动、证据、等待授权、验证及失败状态，授权证据面板提供批准与拒绝操作。
- 当前 `App.tsx` 没有挂载仍存在的 `Sidebar`、`SettingsDialog`、`DevTracePanel`、`PhaseOutputPanel`、`PhaseTimeline`、`QuestionCard`、`ResultPanel` 和 `StatusBar`；文件保留但运行时不可达，构成功能回退。
- `SettingsDialog` 目前只保留开发者模式开关；模型供应商、Base URL、模型和 API Key 逻辑位于只在首次配置时出现的 `SetupGate`，已配置后没有再次进入入口。

## 前端恢复方向

- 视觉命题：保留红、黑、白的构成主义操作台，用清晰分栏和硬边界承载设置，不恢复旧界面的米色卡片系统。
- 内容计划：顶部工具入口负责设置；设置面板覆盖模型连接、运行偏好和开发者模式；项目、会话与调试入口回到主工作流附近。
- 交互命题：设置采用右侧抽屉进入；模式与二元选项使用分段控件和开关；关闭后回到原活动上下文，不重置当前运行状态。

## 迁移前前端功能契约

- 迁移前 `App` 明确挂载 `Sidebar`、`QuestionCard`、`PhaseTimeline`、`PhaseOutputPanel`、`DevTracePanel`、`ResultPanel`、`StatusBar` 和 `SettingsDialog` 八类组件。
- 左栏负责项目选择、项目创建、session 历史、新建 session、session 选择与设置入口；用户确认该信息架构属于必须保留的设计原则。
- 迁移前会请求 `/api/v1/projects`、按 `project_id` 请求 `/api/v1/conversations`，选择 session 后请求其 turns，并在运行完成后刷新项目与历史列表。
- 新 `App` 只保留实时活动、授权和证据状态，没有项目/session 数据加载、历史回看、设置挂载或开发者追踪开关，属于装配层功能回退。
- 项目、session、设置、模型配置和 trace 的后端 API 仍存在；恢复应复用现有契约并把阶段状态移入中区，不重写后端系统。
- 父提交与远端备份仍保存迁移前完整实现，所有恢复以 Git 历史为事实源，不凭记忆重建。

## Hanako 参考

- Hanako 的 `agentic-rl/templates` 提供 task plan、findings、progress 的持久记录结构。
- Hanako 的 `agentic-rl/hook_trigger.py` 和 `hanako_integration.yaml` 展示事件 Hook 与定时任务的分离方式。
- Hanako 的 `personal-principle-harness/SKILL.md` 展示 `execution_mode`、`reporting_mode`、`risk_flags` 和 claims/evidence ledger。
- 以上资料只读，不复制代码和数据。

## 缓存结论

- 应用层上下文缓存负责减少每轮实际拼接和发送的上下文长度。
- 供应商 prompt cache 负责复用稳定前缀；能力必须运行时探测并支持回退。
- 本地推理 KV cache 依赖具体推理引擎，不能作为通用 OpenAI 兼容接口的前提。
- 任何写入或外部副作用都必须使受影响的世界状态缓存失效，并执行回读验证。

## 当前验证证据

- `python -m pytest -q` 最终完整结果为 `44 passed`。
- `tests/test_tools_and_cache.py` 最终为 `19 passed`，覆盖授权终态、文件变更、验证、命令安全、缓存隔离、供应商缓存和取消传播。
- 前端 TypeScript 与 Vite 生产构建通过，33 个模块完成转换。
- 全项目最终静态搜索未发现历史品牌字符串或文件名。
- Playwright 桌面/移动端截图、授权按钮请求、终态更新和控制台复验均已完成。
- Playwright 发现授权响应已更新顶部状态，但证据面板仍显示原始 SSE 的 `pending`；根因是面板未读取 `authorizations` 中的最新记录，现已修复。
- 桌面 1440×900 和移动端 390×844 的文档均无横向溢出或文字裁切；授权待处理截图位于 `output/playwright/`。
- 浏览器记录显示批准与拒绝均请求正确端点，正文分别为 `{"action":"approve","project_id":""}` 和 `{"action":"deny","project_id":""}`；响应后面板分别显示 `approved` 与 `denied`，按钮消失。
- broadcast steering 生命周期已修复；targeted、broadcast 与 interrupt/resume 最终均通过。
- 五个完整循环脚本因共享草稿目录按串行执行，最终全部 `OVERALL: PASS`。

## 恢复后的提交前审查

- broadcast steering 生命周期问题已修复；五个显式集成脚本串行复验全部通过。
- 最近一次全量 pytest 为 `32 passed`，Python 编译、核心导入、CLI 和前端生产构建均通过。
- 已确认重复批准会返回现有请求，重复拒绝还会再次发出结束事件，因此 API 无法按契约对已处理请求返回 409。
- 已确认授权超时只把 registry 状态改为 `expired`，没有发出 `authorization_resolved`，SSE 前端可能永久保留等待状态。
- 已确认 `_redact_params()` 只处理顶层键，嵌套 header/token 会原样进入授权和工具活动事件。
- 已确认 Shell 将副作用命令的退出码 0 直接记录为 `changed=True`，并把退出码检查作为通过的回读验证；该证据不能证明世界状态已经改变。
- `ChangeRecord.changed` 虽标注为 `bool`，`ToolResult.world_changed` 已允许 `None`；可用 `None` 表达命令成功但状态变化未经回读证实，并分类为 `change_unverified`。
- 当前实践层只在 `world_changed is True` 时失效上下文缓存；对未知副作用也应保守失效，但不能把它计入“已证实改变”。
- 已确认 Python/Node 解释器默认在 Shell 白名单内，普通脚本执行被归为 `compute` 并自动允许；需要把除版本/帮助外的解释器调用归为外部行动，限制脚本路径并阻止内联代码绕过边界。
- 显式集成脚本使用 `python primes.py`，解释器边界调整必须保留工作区内脚本的可执行路径，同时由授权策略控制副作用。
- `test_practice_integration.py` 与 `test_full_loop_integration.py` 的标准循环都依赖 `python primes.py` 自动完成；直接把解释器统一改成外部授权会令无 UI 的集成流程等待 900 秒。
- CognitiveLoop 已同时注册 `PythonExecTool`。优先评估把兼容格式中的工作区 Python 脚本路由到该受限工具，让 Shell 保持更保守的命令边界。
- `PROJECT_HANDOFF.md` 明确要求实践规划使用 `tool_calls`，代码只能经 `python_exec` 执行；保留旧格式解析时，应把简单的“生成 Python 文件并执行”机械转换为 `python_exec`，不再交给 Shell。
- `PythonExecTool` 当前仍允许 `open()`、`pathlib`、动态导入等路径，并固定报告 `world_changed=False`；需收紧为纯计算 AST 边界。`requirements` 引发的依赖安装属于外部行动，必须单独分类并授权。

## 最终浏览器复验

- 全新 Playwright 会话 `praxic-final` 打开 Vite 页面成功，标题为 `Praxic`，七阶段、实时活动区和证据面板均进入可访问性树。
- 首次加载控制台为 0 errors、0 warnings；仅有 React 开发工具提示，favicon 不再产生 404。
- 最终几何审计：1440×900、390×844 以及授权批准后的桌面页面均无文档横向溢出，检测到的裁切文本为 0。
- 最终授权审计：POST 正文为 `{"action":"approve","project_id":""}`；响应后 `approved` 可见，批准按钮数量变为 0。
- 最终截图目视确认：桌面三栏、移动端纵向重排、授权前后证据面板均无元素重叠或不可读裁切，构成主义视觉层级稳定。
- 授权交互完成后控制台仍为 0 errors、0 warnings。

## 最终缓存与授权边界复核

- 上下文编译缓存键原先未包含 `token_budget`，相同上下文在不同预算下可能错误复用已截断或未截断结果。
- 截断逻辑原先按字符近似后追加标记，实际 token 估算可能超过预算；应以估算器回查并保证最终结果不越界。
- 稳定前缀指标应只计算第一个动态块之前的连续稳定块，并在本地 KV backend 恢复时保留该元数据。
- 授权 TTL 原先在非正值时生成 `expires_at=0`，而 `active()` 将其解释为永久有效；API 与策略层都应拒绝这种隐式永久授权。
- 授权等待任务被取消时，异步事件虽被移除，但请求状态会永久停留在 `pending`；取消路径也必须发出终态事件。
- Shell 的 Git 分类原先只列举部分变更词，`branch -D`、`switch`、`tag` 等写操作可落入只读分类；应改成显式只读子命令集合。
- `python_exec` 的 AST 黑名单可被 `writer = open` 和动态导入绕过；普通计算需要显式 import allowlist，依赖安装则作为授权后的外部行动记录。
- 首轮显式集成日志显示严格规则误拦了安全且常见的 `__name__` 入口；流程脚本自身仍返回 PASS，因此最终验收还必须检查工具行动是否真正成功。
- 应用层命中只省去上下文编译工作，仍会把文本发送给远程模型；原 `tokens_saved` 递增会夸大节省，应改记 `assembly_tokens_reused`，真正缓存命中只信供应商 usage。
- Anthropic 适配器已有 prompt cache 结构和 usage 统计，但调用方没有传 opt-in 参数；稳定 system prompt 应默认标注缓存，仍允许显式关闭。
- 目标 mypy 首轮发现授权等待路径复用了“原始请求”和“可空终态请求”变量；运行分支虽有保护，类型契约不清晰，需按 request ID 重新读取终态对象。
- 类型检查同时发现 `tomllib` 回退别名重定义，以及批量搜索可能把 `CancelledError` 当作正常结果；前者影响静态契约，后者可能在取消流程触发属性访问错误。
- 剩余 override 提示来自 `BaseTool.run(**kwargs)` 与各工具异构显式参数之间的既有类型建模冲突，不宜在本次迁移中用大范围签名改造解决。

## 最终迁移与敏感信息审计

- 可提交源码、配置和规划记录中未发现历史品牌内容或文件名；CLI 显示 `即物穷理 Praxic`，核心导入正常。
- 全项目未发现常见真实密钥前缀，也未发现项目路径、用户目录等个人绝对路径进入可提交内容。
- `.env`、`config.toml` 和 `.github-token` 均由 `.gitignore` 排除，Git 只跟踪无真实凭据的示例配置。
- `git -c core.whitespace=cr-at-eol diff --check` 通过；大量 CRLF 提示属于 Windows 行尾转换预告。
- 首轮审计发现的历史构建产物均已验证为可再生成内容，并移入项目外隔离目录保存。
- 集成脚本生成的 `examples/primes.py` 位于已忽略的运行工作区；因用户强调无备份，暂不删除该可能承载本地数据的文件。
- 跟踪内容再次用 `git grep` 核验，历史品牌命中为 0。
- `.AGENT/`、`docs/`、`prompts/`、`praxic/config.toml` 和虚拟环境激活脚本已在保留修改前备份后完成品牌迁移。
- `praxic/skills/registry.json` 是被忽略的运行时数据；历史损坏备份已隔离，集成测试重新生成的本机路径不会进入 Git。
- 旧 `dist-electron/` 与约 748 MB 的历史 PyInstaller 可执行文件均已移入隔离目录，并改用中性备份名。
- 审计时的 9 个 skill 草稿元数据已保留，运行时 registry 不作为可移植源码提交。
- 本地项目资料已完成大小写一致的品牌迁移，虚拟环境激活路径已更新；旧 Electron 输出和损坏 registry 备份已移入项目外隔离目录。
- 最终全项目搜索（排除第三方依赖、浏览器输出和缓存）对拉丁旧名、中文旧名及旧名路径均为 0。
- 隔离备份位于项目同级的 `Praxic-stale-artifacts-20260730/`，包含旧构建产物和修改前的 32 个本地文本文件。
- README 一度使用程序不会读取的 `PRAXIC_API_KEY`、`PRAXIC_BASE_URL` 和 `PRAXIC_MODEL`；实际配置契约是 `PRAXIC_LLM_*`，提交前已统一。
- 根目录与 Web 的 package-lock 已用离线 lockfile-only 模式同步到对应 `package.json` 的 `0.1.2`。
- 最终暂存清单包含 120 个文件，主要由包目录迁移、新增工具/缓存模块、前端重构、测试和规划记录构成。
- 暂存索引的历史品牌、常见密钥模式、个人绝对路径和大体积构建二进制搜索均无命中；`git -c core.whitespace=cr-at-eol diff --cached --check` 通过。
- 用户指定由当前工作分支覆盖 `main` 并在 `main` 继续开发；覆盖前的远端 `main`（`5656222`）已保留为 `codex/backup-origin-main-20260730`。
- GitHub 远端核验显示本地 `main` 与 `origin/main` 一致；PR #1 已合并，其源分支 `codex/migrated-main-20260729-v2` 已不存在。
- planning-with-files Stop Hook 只统计英文 `### Phase` 标题与 `**Status:** complete` 状态；中文勾选列表会被误报为 `0/0`，计划现已转换为兼容格式。
- 最终 GitHub API 核验显示 `main` 指向 `640a835`；本地 token 推送使用项目内 `scripts/push.sh`，未将 token 写入 Git 配置或提交。
