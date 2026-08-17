"""实测 command_probe 真实效果。"""
import asyncio, sys, os
sys.path.insert(0, '.')
os.environ.setdefault('DEEPSEEK_API_KEY', 'x')
from praxic.tools.command_probe import CommandProbeTool

async def main():
    tool = CommandProbeTool()
    for cmd in ("lean", "lake", "python", "where", "gh"):
        r = await tool.run(cmd)
        print(f"  {cmd}: {r.content[:80]}")
    # 非法输入
    for bad in ("", "C:/tools/lean.exe", "lean --version"):
        r = await tool.run(bad)
        print(f"  非法 {bad!r}: {r.error[:60]}")

asyncio.run(main())
