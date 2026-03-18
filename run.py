#!/usr/bin/env python3
"""CLI entry point for Reddit AI-in-K12 data collection pipeline."""

import argparse
import sys

from db import init_db, db_session, get_stats


def cmd_collect(args):
    """Run data collection."""
    from pipeline import run_arctic_only, run_full_pipeline
    if args.source == "arctic":
        run_arctic_only()
    elif args.source == "all":
        run_full_pipeline(skip_llm=True)
    else:
        print(f"Unknown source: {args.source}")


def cmd_filter(args):
    """Run filtering stages."""
    init_db()
    if args.stage in ("keyword", "all"):
        from filters.keyword_filter import run_keyword_filter
        matched, total = run_keyword_filter(callback=print)
        print(f"Keyword: {matched}/{total} matched")

    if args.stage in ("llm", "all"):
        from filters.llm_filter import run_llm_filter
        relevant, total = run_llm_filter(callback=print)
        print(f"LLM: {relevant}/{total} relevant")


def cmd_comments(args):
    """Fetch comments for relevant posts."""
    from pipeline import run_comments_only
    run_comments_only()


def cmd_export(args):
    """Export data."""
    init_db()
    from export import export_csv, export_json, export_stats

    if args.format in ("csv", "all"):
        export_csv()
    if args.format in ("json", "all"):
        export_json()
    if args.format in ("stats", "all"):
        export_stats()


def cmd_stats(args):
    """Show current database statistics."""
    init_db()
    with db_session() as conn:
        stats = get_stats(conn)

    print(f"Total posts:      {stats['total_posts']}")
    print(f"Keyword matched:  {stats['keyword_matched']}")
    print(f"Classified:       {stats['classified']}")
    print(f"LLM relevant:     {stats['llm_relevant']}")
    print(f"Total comments:   {stats['total_comments']}")
    print(f"\nBy subreddit:")
    for sub, count in sorted(stats["by_subreddit"].items()):
        print(f"  r/{sub}: {count}")
    print(f"\nBy category:")
    for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")


def cmd_pipeline(args):
    """Run the full pipeline."""
    from pipeline import run_full_pipeline
    run_full_pipeline(skip_llm=args.skip_llm)


def main():
    parser = argparse.ArgumentParser(
        description="Reddit AI-in-K12 Education Data Collection"
    )
    sub = parser.add_subparsers(dest="command", help="Command to run")

    # collect
    p_collect = sub.add_parser("collect", help="Collect posts from Reddit")
    p_collect.add_argument("source", choices=["arctic", "all"], default="arctic",
                           nargs="?", help="Data source (default: arctic)")
    p_collect.set_defaults(func=cmd_collect)

    # filter
    p_filter = sub.add_parser("filter", help="Run filtering stages")
    p_filter.add_argument("stage", choices=["keyword", "llm", "all"], default="all",
                          nargs="?", help="Filter stage (default: all)")
    p_filter.set_defaults(func=cmd_filter)

    # comments
    p_comments = sub.add_parser("comments", help="Fetch comments for relevant posts")
    p_comments.set_defaults(func=cmd_comments)

    # export
    p_export = sub.add_parser("export", help="Export data to CSV/JSON")
    p_export.add_argument("format", choices=["csv", "json", "stats", "all"],
                          default="all", nargs="?", help="Export format (default: all)")
    p_export.set_defaults(func=cmd_export)

    # stats
    p_stats = sub.add_parser("stats", help="Show database statistics")
    p_stats.set_defaults(func=cmd_stats)

    # pipeline
    p_pipe = sub.add_parser("pipeline", help="Run full pipeline end-to-end")
    p_pipe.add_argument("--skip-llm", action="store_true",
                        help="Skip LLM classification")
    p_pipe.set_defaults(func=cmd_pipeline)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
