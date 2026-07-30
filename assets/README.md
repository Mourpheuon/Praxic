# Praxic 素材库

这里保存 Praxic 的品牌母版、图标、纹理和参考素材。素材库与前端发布目录分离，未经确认的母版不会随 Web 构建一起发布。

## 目录约定

- `brand/source/`：品牌图形原始母版，只新增版本，不覆盖旧文件。
- `brand/exports/`：从母版导出的透明、裁切或缩放版本。
- `brand/prompts/`：与生成式品牌素材对应的严格 Prompt。
- `icons/source/`：功能图标原稿。
- `icons/exports/`：经过小尺寸验收的界面图标。
- `textures/`：纸张、印刷颗粒等可重复使用的视觉纹理。
- `references/`：仅供设计参考、不进入产品的素材。
- `catalog.json`：素材来源、状态、用途和完整性信息。

目录按需创建，避免使用空占位目录。

## 使用流程

1. 原始文件进入对应的 `source/` 目录，并在 `catalog.json` 登记。
2. 保留原始母版不变，在 `exports/` 中生成用途明确的衍生版本。
3. 在目标尺寸下检查透明边缘、对比度、轮廓和文字邻接效果。
4. 只有标记为 `approved` 的导出物才复制到 `praxic/web/public/assets/`。
5. 前端引用发布目录中的导出物，不直接引用素材库母版。

## 命名规则

使用小写 kebab-case：`主题-用途-版本-尺寸.扩展名`。

示例：`praxic-compass-ui-v1-64.png`。
