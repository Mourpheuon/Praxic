# -*- coding: utf-8 -*-
"""生成 Praxic 三平台图标
从 assets/brand/source/praxic-compass-v1.png 生成:
  - assets/icon.ico   (Windows, 多尺寸 16-256)
  - assets/icon.png   (Linux / 通用, 512x512)
  - assets/icon-1024.png (macOS 图标源, electron-builder 可据此转 icns)
用法: python scripts/gen_icons.py
"""
from pathlib import Path
from PIL import Image

SRC = Path(r"E:\Scripts\Praxic\assets\brand\source\praxic-compass-v1.png")
OUT = Path(r"E:\Scripts\Praxic\assets")

def main():
    img = Image.open(SRC).convert("RGBA")
    assert img.size == (1024, 1024), f"expected 1024x1024, got {img.size}"

    # 1. Windows .ico — 多尺寸 (16,24,32,48,64,128,256)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_path = OUT / "icon.ico"
    img.save(ico_path, format="ICO", sizes=sizes)
    print(f"[OK] {ico_path.name} ({len(sizes)} sizes)")

    # 2. Linux / 通用 PNG — 512x512
    png512 = OUT / "icon.png"
    img.resize((512, 512), Image.LANCZOS).save(png512, format="PNG")
    print(f"[OK] {png512.name} (512x512)")

    # 3. macOS 图标源 — 1024x1024 PNG
    # electron-builder 在 mac 构建时可用 icon.png 自动生成 icns；
    # 这里保留 1024 源图，也可在 mac 上 iconutil 转 icns
    png1024 = OUT / "icon-1024.png"
    img.save(png1024, format="PNG")
    print(f"[OK] {png1024.name} (1024x1024, mac icon source)")

    # 4. macOS iconset 目录（供 mac CI 用 iconutil 转 icns）
    iconset = OUT / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    # iconutil 需要的尺寸: icon_16x16.png, icon_16x16@2x.png, ... icon_512x512@2x.png
    spec = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for fname, px in spec.items():
        img.resize((px, px), Image.LANCZOS).save(iconset / fname, format="PNG")
    print(f"[OK] icon.iconset/ ({len(spec)} files)")

if __name__ == "__main__":
    main()
