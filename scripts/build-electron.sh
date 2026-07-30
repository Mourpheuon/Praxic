#!/usr/bin/env bash
# 即物穷理 Praxic —— Electron 壳构建脚本
# 在本地 Windows/macOS/Linux 上运行，构建可分发的 Electron 应用包。
#
# 前置条件：
#   1. Node.js >= 18（https://nodejs.org）
#   2. Python 3.11+（用户自行安装，不打包进应用）
#   3. Git（用于版本标签）
#
# 用法：
#   bash scripts/build-electron.sh          # 构建当前平台
#   bash scripts/build-electron.sh --all    # 构建所有平台（需对应平台或 CI）
#   bash scripts/build-electron.sh --publish # 构建并发布到 GitHub Releases

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  即物穷理 Electron 壳构建${NC}"
echo -e "${GREEN}  version: $(node -e "console.log(require('./package.json').version)")${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# ── 1. 检查 Node.js ──
if ! command -v node &> /dev/null; then
    echo -e "${RED}[错误] 未找到 Node.js，请先安装 https://nodejs.org${NC}"
    exit 1
fi
echo -e "[1/5] Node.js $(node --version)"

# ── 2. 安装依赖 ──
echo "[2/5] 安装 npm 依赖..."
npm install

# 安装前端依赖
if [ -d "praxic/web" ]; then
    echo "       安装前端依赖..."
    cd praxic/web && npm install && cd "$PROJECT_ROOT"
fi

# ── 3. 构建前端 ──
echo "[3/5] 构建前端（Vite）..."
if [ -d "praxic/web" ]; then
    cd praxic/web && npx vite build && cd "$PROJECT_ROOT"
    echo "       前端构建完成 → praxic/web/dist/"
else
    echo -e "${YELLOW}       praxic/web/ 不存在，跳过前端构建${NC}"
fi

# ── 4. Electron Builder 打包 ──
echo "[4/5] 打包 Electron 应用..."
if [ "${1:-}" = "--all" ]; then
    npx electron-builder --win --mac --linux
elif [ "${1:-}" = "--publish" ]; then
    npx electron-builder --publish always
else
    npx electron-builder
fi

# ── 5. 完成 ──
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  构建完成！${NC}"
echo -e "${GREEN}  产物目录: dist-electron/${NC}"
ls -lh dist-electron/ 2>/dev/null || echo "  (查看上方 electron-builder 输出)"
echo -e "${GREEN}========================================${NC}"
