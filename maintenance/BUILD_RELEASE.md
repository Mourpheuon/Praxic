# 构建与发布的当前入口

## 安装依赖

Python 3.11+，Node.js 20+。在虚拟环境中：

```bash
python -m pip install -e ".[desktop,dev]" pyinstaller
npm ci
```

不需要把本地 prompts/ 放入发行源码。缺省阶段提示词有代码内回退；自定义提示词通过运行目录或 PRAXIC_PROMPTS_DIR 配置。

## 本地构建

```bash
python scripts/build_desktop.py
python scripts/build_desktop.py --backend-only
python scripts/build_desktop.py --shell-only
```

默认顺序：版本一致性 → PyInstaller → 冻结后端健康/页面/资源/版本检查 → 当前平台 Electron 打包。
shell-only 不重建后端，但不会跳过后端检查；backend-only 不打桌面壳。
所有本地路径强制 --publish never。跨平台构建在对应系统完成，单机 --all 已退役。
脚本仅执行构建，不自动安装依赖；依赖缺失或任一步失败均以非零状态退出。
旧 build_exe.bat、scripts/build-electron.ps1、scripts/build-electron.sh 仅保留兼容包装；-Publish/--publish 不再直接发布。

## 正式发布

1. 同步六个版本文件（pyproject.toml、praxic/__init__.py、根目录和 web 的 package.json/package-lock.json）及 Docker 默认版本；lock 根包版本也必须同步。
2. 增加 maintenance/releases/vX.Y.Z.md，运行一致性检查和测试，提交并推送分支。
3. 可先手动运行 build 工作流做预检。确认标签尚不存在，再创建并推送新的 vX.Y.Z 标签。
4. 标签流程在 Windows、macOS、Linux 原生构建。测试、冻结后端检查和安装包生成全部通过后，publish job 发布附件及 SHA256SUMS.txt。
5. 核对 GitHub Release 非草稿、附件平台/架构和摘要。不得通过覆盖旧标签或删除同名 Release 来重试；失败需查明具体原因。

HTTP /setup/build-electron 和 /setup/release-check 仅保留退役提示，不触发命令、安装工具、改写版本或删除产物。

## Docker

```bash
docker build -t praxic .
docker run --rm -p 8000:8000 --env-file .env praxic
```

需要持久化时，按部署环境为 data、workspace 等运行目录挂载可写卷。
Docker 使用同一 desktop 运行依赖，默认拒绝的构建上下文只允许产品源码与必要元数据。凭据、本地归档、环境目录和历史安装包不发送给构建器。
Docker、真实模型调用和完整安装/卸载应独立验收，单元测试通过不能替代这些检查。
