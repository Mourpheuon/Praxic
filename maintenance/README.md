# 仓库维护索引

本目录对应 2026-09-17 核对的源码；历史计划不作为当前功能依据。

## 当前事实来源

- Python 版本：praxic/__init__.py；发行元数据需与 pyproject.toml、两个 package.json 和 lock 文件同步。
- API 版本直接引用包版本。运行 `python scripts/check_repository.py` 检查静态一致性。
- CLI：安装开发包后使用 `praxic run` / `praxic serve`；`python -m praxic` 只接受 Web 启动参数。
- 实际 Web 页面：praxic/web/index.html（内联应用，依赖 CDN）；API 直接读取它。
- praxic/web/src 是另一套组件实现，目前未被上述服务入口加载。未核对功能等价，保留，不能直接删除或声称其构建产物已用于发布。
- 配置模板选择 deepseek-v4-flash；无模板配置时 Settings 的模型兜底为 deepseek-v4-pro。这是两条路径，不改变用户现有配置。
- prompts/ 中仅与阶段名匹配的文件被 load_phase_prompt 加载；目录受忽略保护。自定义提示词及用户配置保留。
- 已退休的 praxic/ui 原生界面引用及 flet 依赖已去除，ui 安装 extra 保留为空兼容别名。

## 归档边界

原样保留在本机 maintenance/archive/2026-09-17/：旧三份计划记录、四份根目录设计 prompt、jian.md、scratch_probe_real.py、旧 scratch 登记簿、旧 release.sh、cortex-adapter 状态及轨迹。
archive/ 不进入发行源码；归档是可恢复的本地副本，需跨机器保存时应另外备份。此前已提交的版本仍可从 Git 历史读取。

旧 release.sh 仅修改 Python 元数据就提交推送，容易产生版本漂移，已退出活动脚本目录。手工发布前应同步六个版本文件及 Docker 版本默认值，通过一致性检查，再由维护者决定提交、标签和发布。

未删除：data/、workspace/、projects/、logs/、output/、dist/、dist-electron/、依赖环境、设计资产及真实验证脚本。构建产物可以再生，但本轮留作发布问题证据。

本轮 task_plan.md / findings.md / progress.md 工作记录收尾后移入 maintenance/local/，已忽略；产品文档以本索引和 README 为准。未来维护任务的根目录工作记录也在忽略规则中。

## 本轮验证

`python scripts/check_repository.py` 通过；完整 pytest 回归 371 项通过，保留一个已有的 tar 解压弃用警告。未运行真实模型集成、Docker 构建或跨平台安装验收。

## 发布状态

详见 [Windows 发布诊断](RELEASE_DIAGNOSIS.md)。本轮不修改已发布安装包、不修复启动链路、不上传新 release。
