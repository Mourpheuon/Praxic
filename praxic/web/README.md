# 前端状态与边界

- 当前产品入口是 index.html：内联应用，由 FastAPI 和冻结后端直接托管，无需 Vite 编译。
- public/ 为产品静态资源，PyInstaller 会打包。
- src/ 是尚未接入产品的 TypeScript 组件实现，保留用于后续功能对照。当前 index.html 不引用 src/main.tsx，所以 vite build 不会把这些组件变成产品入口。
- `npm --prefix praxic/web run typecheck` 仅验证组件类型；build 是旧 Vite 构建实验，不是桌面发行步骤。
- 迁移前须核对设置、权限、项目、文件编辑、会话事件与恢复等功能，再切换入口；不能仅凭组件文件存在就删除当前页面。
