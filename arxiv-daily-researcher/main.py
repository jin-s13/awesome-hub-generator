"""
多数据源论文研究系统入口

运行模式（通过 --mode 参数选择）：
- daily_research（默认）：每日论文监控与研究
- trend_research：关键词驱动的研究趋势分析
"""

import sys
import argparse
from pathlib import Path
from datetime import date, timedelta

# 将 src 目录加入 Python 模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from config import settings
from utils.logger import setup_logger, setup_run_log
from utils.run_lock import run_lock

logger = setup_logger("Main")


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="ArXiv Daily Researcher — 多数据源论文研究系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
运行示例:
  python main.py                                        # 每日研究模式（默认）
  python main.py --mode trend_research --keywords "quantum error correction"
  python main.py --mode trend_research --keywords "quantum error correction" "fault tolerant" \\
                 --date-from 2024-01-01 --date-to 2024-12-31
        """,
    )
    parser.add_argument(
        "--mode",
        default="daily_research",
        choices=["daily_research", "trend_research"],
        help="运行模式：daily_research（每日研究，默认）或 trend_research（研究趋势分析）",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        help="[trend_research] 搜索关键词，多个用空格分隔",
    )
    parser.add_argument(
        "--date-from",
        type=str,
        default=None,
        help="[trend_research] 搜索起始日期，格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--date-to",
        type=str,
        default=None,
        help="[trend_research] 搜索截至日期，格式 YYYY-MM-DD（默认：今天）",
    )
    parser.add_argument(
        "--sort-order",
        type=str,
        choices=["ascending", "descending"],
        default=None,
        help="[trend_research] 时间排序方向：ascending（旧→新）或 descending（新→旧）",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="[trend_research] 最大论文数（安全上限，默认使用配置文件值）",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=None,
        help="[trend_research] 限制搜索的 ArXiv 分类，多个用空格分隔，如 quant-ph cond-mat.mes-hall；不指定则不限制分类",
    )
    return parser.parse_args()


if __name__ == "__main__":
    settings.ensure_directories()

    # 自动更新检查
    if settings.AUTO_UPDATE_ENABLED:
        try:
            from utils.updater import check_and_update

            check_and_update(logger)
        except Exception as e:
            logger.warning(f"自动更新检查失败: {e}")

    args = parse_args()

    if args.mode == "trend_research":
        # 研究趋势分析模式
        log_file = setup_run_log("trend_research")
        logger.info(f"趋势研究日志文件: {log_file}")

        if not args.keywords:
            print("错误: trend_research 模式必须指定 --keywords 参数")
            sys.exit(1)

        date_to = date.today()
        if args.date_to:
            date_to = date.fromisoformat(args.date_to)

        date_from = date_to - timedelta(days=settings.RESEARCH_DEFAULT_DATE_RANGE_DAYS)
        if args.date_from:
            date_from = date.fromisoformat(args.date_from)

        sort_order = args.sort_order or settings.RESEARCH_SORT_ORDER
        max_results = (
            args.max_results if args.max_results is not None else settings.RESEARCH_MAX_RESULTS
        )

        from modes.trend_research import TrendResearchPipeline

        with run_lock(
            "trend_research",
            keywords=args.keywords,
            date_from=date_from,
            date_to=date_to,
            categories=args.categories,
        ):
            TrendResearchPipeline(
                settings=settings,
                keywords=args.keywords,
                date_from=date_from,
                date_to=date_to,
                sort_order=sort_order,
                max_results=max_results,
                categories=args.categories,
            ).run()
    else:
        # 每日研究模式（默认）
        log_file = setup_run_log("daily_research")
        logger.info(f"每日研究日志文件: {log_file}")

        from modes.daily_research import DailyResearchPipeline

        with run_lock("daily_research"):
            DailyResearchPipeline().run()
