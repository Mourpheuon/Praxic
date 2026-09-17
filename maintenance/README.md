# 仓库维护索引

当前发行版：[v0.2.0](https://github.com/Mourpheuon/Praxic/releases/tag/v0.2.0)，已于 2026-09-17 发布。
本地后续清理不修改已发布标签或附件；重新发行需要新版本。

本轮变更、验证及保留理由见 [集中清理记录](CLEANUP_2026-09-17.md)。

## 唯一事实来源

- 版本源为 praxic/__init__.py。发行前同步 pyproject.toml、根目录与 web 的 package.json/lock、Docker 默认版本，使用 scripts/check_repository.py 检查。
- 运行依赖由 pyproject.toml 声明；desktop extra 服务于本地、CI 和 Docker。高级语义存储的可选 storage extra 独立保留。
- 本地构建入口 scripts/build_desktop.py；bat/PowerShell/bash 旧命令只作薄包装，不再另装依赖或直接发布。
- 发行入口 .github/workflows/build.yml；设置页旧发布入口返回 410，不再修改版本或 Release。
- 产品前端与保留组件的边界见 [前端说明](../praxic/web/README.md)。
- 当前状态看本文件；旧诊断看 [v0.1.8 历史证据](RELEASE_DIAGNOSIS.md)，其中各轮测试数字对应当时提交。

## 已归档或隔离

- 第一轮历史记录位于本机 maintenance/archive/2026-09-17/，包括旧规划、根目录设计提示词、scratch 脚本、release.sh 和内部运行轨迹。
- 本轮旧 push.sh 归档到 maintenance/archive/2026-09-17-post-release/，不再从凭据文件拼接推送 URL；维护者使用正常 Git 凭据管理。
- 四个真实模型验收脚本移到 scripts/diagnostics/，保留在 Git，明确与离线回归隔离。
- PROJECT_HANDOFF.md 属于历史内部交接，原样本地归档，不再作为新开发入口。
- 根目录临时计划在任务结束后收拢到 maintenance/local/；上述本地归档均受忽略规则保护。此前已提交内容也可从 Git 历史恢复。

## 保留项与原因

- data/、workspace/、projects/、logs/、output/：可能包含用户数据和验证证据，不按目录名批量删除。
- dist/、dist-electron/：保留旧发行包及构建证据，新构建仍按工具自身规则更新对应版本产物。
- .venv、.venv-build、node_modules：工作环境，不属于应删除的源码残留。
- prompts/、config.toml、.env、技能及插件目录：用户配置和运行扩展，不归档或展示内容。
- 本地自定义 prompts 和 skills 不再隐式夹带进安装包；在目标运行目录配置或导入，发行默认使用代码内提示词。
- web/src：未整合组件，不声称等价于产品页面；保留直到完成迁移验收。
- praxic/storage 空命名空间、ui 空安装 extra：保留兼容边界，不新增业务逻辑。
- assets/brand/source 与导出图：设计源及产品素材，不以相似文件名判断重复。

## 防止再次漂移

一致性检查覆盖版本、内部文档链接、已退役路径、构建门控与测试边界。Docker 使用默认拒绝的上下文白名单；Python wheel 不强制夹带本地 prompts。
日常修改先运行：

```bash
python scripts/check_repository.py
python -m pytest -q
node --test tests/backend-ready.test.cjs
```

构建、发布和迁移边界见 [操作说明](BUILD_RELEASE.md)。
