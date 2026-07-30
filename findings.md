# Praxic 研究与发现记录

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
