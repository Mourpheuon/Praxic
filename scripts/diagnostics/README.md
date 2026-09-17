# 手动真实服务诊断

这些脚本保留在版本控制中，不参与普通测试、启动、打包或发布。运行会调用真实模型，可能执行工具、写入运行数据并消耗 API 配额；本轮清理没有运行它们。

| 脚本 | 用途 |
| --- | --- |
| probe_reasoning_control.py | 比较推理参数行为；少量样本，不能当作统计结论 |
| verify_practice_real.py | 真实实践阶段的规划、代码与失败记录 |
| verify_contradiction_spine_real.py | 完整循环中的矛盾增量维护 |
| verify_contradiction_spine_real_light.py | 两轮矛盾模块对照 |

从仓库根目录显式执行 `python scripts/diagnostics/<脚本名>`。先检查 config.toml/.env，确认预算和工具权限。离线回归使用 `python -m pytest -q`。
