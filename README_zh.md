# 即物穷理（Praxic）

以调查、分析、实践验证和反思迭代组织任务的 AI 智能体。

当前已发布版本：**v0.2.0**。修复了 Windows 安装后的后端启动、中文日志编码和数据目录权限问题。

[下载发行版](https://github.com/Mourpheuon/Praxic/releases/tag/v0.2.0) · [升级说明](maintenance/releases/v0.2.0.md) · [English](README.md)

## 使用发行版

Windows 下载名称含 win 的 exe；macOS 下载匹配架构的 dmg/zip；Linux 下载 AppImage/deb。
当前安装包未签名。升级前备份旧配置与数据；旧安装目录数据不会自动迁移。
桌面运行数据位于用户数据目录的 backend 子目录，可用 PRAXIC_RUNTIME_DIR 覆盖。首次启动通过设置页配置模型服务。

## 从源码运行

需要 Python 3.11+。建议先创建并激活虚拟环境：

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[desktop]"
```

复制 config.toml.example 为 config.toml，复制 .env.example 为 .env 并填写密钥，也可以通过设置页配置。
不要把密钥写进 config.toml。配置模板选择 deepseek-v4-flash；没有该配置时，代码兜底选择 deepseek-v4-pro，二者均可自行修改。

```bash
python -m praxic --host 127.0.0.1
praxic run "你的问题" --mode standard
praxic run --help
```

python -m praxic 是 Web 启动入口；praxic run 是安装后可用的 CLI。
Windows 也可以使用 start-praxic.bat，它优先选择项目 .venv，不依赖固定盘符。

## 当前功能与边界

- 预处理与五阶段循环：调查、矛盾分析、理性认识、实践、反思；支持 fast、standard、deep 与自定义跳阶段。
- 工具、授权、工作区、项目、会话记忆、SSE 活动与恢复。
- 模型深度与阶段预算控制、技能导入、证据及实践验证。
- 文件、网页、数据查询和执行工具；部分工具需要额外依赖或外部服务，权限按配置控制。

当前产品前端是 praxic/web/index.html 内联页面，FastAPI 与桌面包直接托管它，部分资源依赖外部 CDN。
web/src 组件树尚未接入产品入口，不能将 Vite 构建成功等同于桌面 UI 已切换。详见 [前端边界](praxic/web/README.md)。

## 开发、构建与测试

```bash
python -m pip install -e ".[desktop,dev]" pyinstaller
npm ci
python scripts/check_repository.py
python -m pytest -q
node --test tests/backend-ready.test.cjs
python scripts/build_desktop.py
```

本地构建只生成当前操作系统的安装包，不发布：一致性检查 → 冻结后端 → 启动/版本检查 → Electron 安装包。
已构建后端时，可运行 npm run electron:build，它仍会先检查后端。
产物目录为 dist-electron，Windows 安装包命名如 Praxic-0.2.0-win-x64.exe。

正式发布统一使用 GitHub 标签流程，各平台原生构建并全部验证后发布。
设置页旧构建/发布入口已退役；旧请求返回 HTTP 410，不再删除 Release 或重打标签。

详细说明：[构建与发布](maintenance/BUILD_RELEASE.md)。

## 目录导航

| 路径 | 职责 |
| --- | --- |
| praxic/core/ | 认知编排与阶段模块 |
| praxic/cordis/ | 资源装配与会话生命周期 |
| praxic/tools/ | 工具、权限与执行契约 |
| praxic/memory/ | 记忆、检索及上下文缓存 |
| praxic/llm/ | 模型适配与调用缓存 |
| praxic/api/ | 设置、会话、项目与流式接口 |
| praxic/web/ | 产品内联页面与待整合组件树 |
| electron/ | 桌面外壳和后端健康检查 |
| scripts/ | 构建、检查及导入命令 |
| scripts/diagnostics/ | 显式执行、可能收费的真实模型诊断 |
| tests/ | 自动化回归 |
| maintenance/ | 当前维护边界、发布说明与历史问题证据 |

本地归档、凭据、运行数据与构建产物不进入 Git。清理范围和保留项见 [维护索引](maintenance/README.md)。
项目元数据声明 MIT 许可。
