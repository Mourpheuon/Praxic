#!/usr/bin/env python3
"""
即物穷理技能批量导入 CLI

把 praxic/skills/ 下的外部 Claude 格式技能适配并写入 registry.json。
规则由 praxic/skills/IMPORT_RULES.md 驱动。

用法:
  python scripts/import_skills.py                # 混合模式（确定性 + LLM 精炼），写入
  python scripts/import_skills.py --dry-run      # 只预览映射，不写 registry
  python scripts/import_skills.py --no-llm        # 仅确定性（瞬时、免费、不联网）
  python scripts/import_skills.py --limit 5       # 只处理前 5 个（调试用）
  python scripts/import_skills.py --force         # 重新导入已注册的技能

提示: 混合模式下每个技能一次 LLM 调用，91 个技能约需数分钟。
"""
import argparse
import asyncio
import sys
from pathlib import Path

# 允许从项目根直接运行
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from praxic.core.skill_importer import SkillImporter  # noqa: E402
from praxic.config import settings  # noqa: E402


def _print_report(report: dict, dry_run: bool) -> None:
    mode = "DRY-RUN（未写入）" if dry_run else "已写入 registry"
    print("=" * 60)
    print(f"技能导入报告 [{mode}]")
    print("=" * 60)
    print(f"扫描: {report['scanned']}  |  导入: {len(report['imported'])}  |  "
          f"跳过: {len(report['skipped'])}  |  失败: {len(report['failed'])}")
    print(f"registry 现有技能总数: {report.get('registry_total', '?')}")

    # 阶段分布
    from collections import Counter
    phase_count: Counter = Counter()
    compat_count: Counter = Counter()
    for e in report["imported"]:
        for p in e["phases"]:
            phase_count[p] += 1
        compat_count[e.get("compatibility", "native")] += 1
    if phase_count:
        print(f"\n阶段分布: {dict(phase_count)}")
        print(f"兼容性分布: {dict(compat_count)}")

    print("\n--- 导入明细 ---")
    for e in report["imported"]:
        triggers = "、".join(e["triggers"][:4])
        print(f"  [{'/'.join(e['phases'])}] {e['name']}")
        print(f"       触发: {triggers}  ({e.get('compatibility','native')})")

    if report["skipped"]:
        print("\n--- 跳过 ---")
        for s in report["skipped"]:
            print(f"  {s['name']}: {s['why']}")
    if report["failed"]:
        print("\n--- 失败 ---")
        for s in report["failed"]:
            print(f"  {s['name']}: {s['why']}")


async def _main() -> int:
    ap = argparse.ArgumentParser(description="即物穷理技能批量导入")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写入 registry")
    ap.add_argument("--no-llm", action="store_true", help="仅确定性映射，不调用 LLM")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 个技能")
    ap.add_argument("--force", action="store_true", help="重新导入已注册技能")
    ap.add_argument("--skills-dir", type=str, default=None, help="技能目录（默认取 config）")
    args = ap.parse_args()

    skills_dir = Path(args.skills_dir) if args.skills_dir else getattr(
        settings, "skills_dir", ROOT / "praxic" / "skills")

    llm = None
    if not args.no_llm:
        try:
            from praxic.llm import get_llm
            llm = get_llm()
        except Exception as e:
            print(f"[警告] 无法初始化 LLM（{e}），回退到 --no-llm 确定性模式")
            llm = None

    importer = SkillImporter(skills_dir=skills_dir, llm=llm)
    report = await importer.import_all(
        use_llm=(llm is not None),
        dry_run=args.dry_run,
        limit=args.limit,
        force=args.force,
    )
    _print_report(report, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
