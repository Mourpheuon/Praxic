# 临时脚本登记簿

新增一次性脚本必须登记，归档或删除时同步更新。临时脚本默认不进入版本控制。

最后核对：2026-09-17。

| 文件 | 当前状态 |
|------|----------|
| scratch_probe_real.py | 已原样归档至 maintenance/archive/2026-09-17/；正式覆盖见 tests/test_command_probe.py |

根目录当前无 scratch_*.py。旧清理日志在上述归档目录的 SCRATCH_SCRIPTS.md 中保留。
runtime_hook.py 是打包运行时钩子，继续保留。真实模型探针和验收脚本统一放入 scripts/diagnostics/，不参与普通离线测试。
