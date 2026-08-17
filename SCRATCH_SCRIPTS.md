<!--
  ⚠️ 维护要求：本文件是临时脚本（scratch_*.py）的唯一登记簿。
  - 新增任何 scratch_*.py / 一次性调试脚本时，必须在这里登记一行；
  - 删除或清理某个临时脚本时，必须同步更新本清单；
  - 每次提交前请顺手核对：清单与实际文件是否一致。
  任何后续智能体 / 维护者都不许跳过这条规则。
-->

# 临时脚本登记簿（SCRATCH SCRIPTS）

> 用途：记录项目根目录下一次性调试脚本（scratch_*.py）的位置与用途，避免它们沦为无人认领的杂物。
> 政策：这些脚本均未被 git 跟踪、不进提交；新增必须登记、删除必须同步更新本清单。
>
> 最后核对时间：2026-08-18

## ✅ 清理记录（2026-08-18 执行）

按用户要求"要么清理要么放 scripts"，**全部 25 个 scratch_*.py 已直接删除**（无保留价值：一次性前端改造调试脚本，参照的 index.html.work 工作副本已不存在，对应功能已由 tests/ 覆盖；不值得移入 scripts/）。随同清理：根目录 $null 残留文件、server.log / server.err.log（已移入 logs/）、.mypy_cache / .pytest_cache / .ruff_cache（可再生缓存）。

删除清单（25 个）：scratch_check_final、scratch_clarify、scratch_concurrent、scratch_diff、scratch_diff2、scratch_e2e、scratch_flist、scratch_idx2、scratch_idx3、scratch_idx_struct、scratch_insert、scratch_insert2、scratch_insert3、scratch_insert4、scratch_insert5、scratch_set、scratch_ts、scratch_verify_work、scratch_verify_work2、scratch_win_cmd、scratch_work1、scratch_work2、scratch_work3、scratch_work4、scratch_work5（后缀 .py）。

其中 scratch_flist.py（用 Praxic 原生工具列出工作区）、scratch_win_cmd.py（验证 Windows 兼容命令列目录）为 8-17 晚间的补充调试脚本，与本清单原登记同源，一并删除。

若将来再次出现 scratch_*.py，必须按开头维护要求登记，并在用毕后删除。

## 背景

以下 23 个脚本全部诞生于同一次前端改造任务：将设置页（SettingsDialog 页签、对话权限下拉、默认权限保存等）以**内联 React（text/babel）**方式直接改写到 `praxic/web/index.html`。
它们是一次性的定位 / 检查 / 补丁工具，不是测试、不是产品代码。

⚠️ 关键事实：这些脚本大多读取的 `praxic/web/index.html.work` 工作副本**已不存在**（改造完成后被合并/删除），
因此引用它的脚本（diff / insert / verify_work / work 系列）如今已无法原样重跑，属于历史遗留。

## 清单

### A. 前端改造前的定位与结构探查（只读，已过期）

| 文件 | 用途 | 状态 |
|------|------|------|
| scratch_idx_struct.py | 正则定位 index.html 内联 React 的运行模式下拉结构 | 只读，过期 |
| scratch_idx2.py | 定位 SettingsDialog 页签（activeTab）结构 | 只读，过期 |
| scratch_idx3.py | 定位启动表单 textarea / praxic-project-dialog 附近 | 只读，过期 |

### B. diff 与文件状态对比（引用已删除的 .work 副本）

| 文件 | 用途 | 状态 |
|------|------|------|
| scratch_diff.py | index.html 与 index.html.work 逐行 diff | **失效**（.work 已删） |
| scratch_diff2.py | 同上（二次对比） | **失效**（.work 已删） |
| scratch_clarify.py | 对比 praxic/web/index.html 与 dist/index.html | 过期 |
| scratch_ts.py | 查看 index.html / .work 的大小与时间戳 | **失效**（.work 已删） |
| scratch_concurrent.py | 查看 index.html 的 git 状态与最近改动 | 只读，可跑 |

### C. 向 .work 副本插入代码的一次性补丁

| 文件 | 用途 | 状态 |
|------|------|------|
| scratch_insert.py | 定位 about 块结束位置（Footer 注释锚点） | **失效**（.work 已删） |
| scratch_insert2.py | 从 Footer 往前找 about 块插入代码 | **失效**（.work 已删） |
| scratch_insert3.py | 在 SettingsDialog handleSave 附近加 saveDefaultPermission | **失效**（.work 已删） |
| scratch_insert4.py | 找输入区组件 conversationId 相关行 | **失效**（.work 已删） |
| scratch_insert5.py | 定位 activeConvId 相关行 | **失效**（.work 已删） |

### D. 定位 SettingsDialog 各段结构的工作脚本（work 系列）

| 文件 | 用途 | 状态 |
|------|------|------|
| scratch_work1.py | 定位页签导航按钮渲染处 | **失效**（.work 已删） |
| scratch_work2.py | find() 逐行找指定模式 | **失效**（.work 已删） |
| scratch_work3.py | 找 about 页签内容块与 SettingsDialog 结尾 | **失效**（.work 已删） |
| scratch_work4.py | 从 about 块(4394行)往后找内容区结束 | **失效**（.work 已删） |
| scratch_work5.py | 找 SettingsDialog footer 按钮与 return 收尾 | **失效**（.work 已删） |

### E. 改造后的验收 / 冒烟（针对真实文件或服务）

| 文件 | 用途 | 状态 |
|------|------|------|
| scratch_check_final.py | 检查替换后 index.html 大小与功能标记（权限下拉等） | 可跑（仅读文件） |
| scratch_verify_work.py | 验证新功能存在性（TABS 权限页签等） | **失效**（.work 已删） |
| scratch_verify_work2.py | 提取 babel 脚本块验证内容 | **失效**（.work 已删） |
| scratch_e2e.py | httpx 打 http://localhost:8000 检查页面功能 | 需后端运行 |
| scratch_set.py | GET /api/v1/settings 冒烟验证 | 需后端运行 |

## 不在清单内的同源文件

- `runtime_hook.py` —— **不是**临时脚本：PyInstaller 运行时钩子，被 `praxic.spec` 的 `runtime_hooks=[...]` 引用，勿删。
- `tail_fix.py` —— 已不存在（.gitignore 中的条目是残留，可择机移除该 ignore 行）。

## 清理建议（未来某天执行）

1. 全部 23 个 scratch_*.py 已无产品价值，功能验证均已由 `tests/` 覆盖；
2. 一次性删除即可：`Remove-Item scratch_*.py`；
3. 删除后同步更新本清单（标记"已清理"或删除本文件），并顺手移除 .gitignore 中 `tail_fix.py` 一行。
