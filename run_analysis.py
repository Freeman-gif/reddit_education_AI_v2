#!/usr/bin/env python3
"""CLI entry point for the analysis and dashboard pipeline."""

import argparse
import sys


def cmd_prepare(args):
    from analysis.db_schema import init_analysis_tables
    from analysis.prepare import run_prepare
    init_analysis_tables()
    run_prepare(skip_llm=getattr(args, 'skip_llm', False))


def cmd_embed(args):
    from analysis.db_schema import init_analysis_tables
    from analysis.embed_cluster import run_embed, run_cluster
    init_analysis_tables()
    run_embed()
    run_cluster()


def cmd_hierarchy(args):
    from analysis.hierarchy import run_hierarchy
    run_hierarchy()


def cmd_emotions(args):
    from analysis.emotions import run_emotions, run_stance
    run_emotions()
    run_stance()


def cmd_edges(args):
    from analysis.db_schema import init_analysis_tables
    init_analysis_tables()
    from analysis.edges import run_edges
    run_edges()


def cmd_aggregate(args):
    from analysis.precompute import run_aggregate
    run_aggregate()


def cmd_dashboard(args):
    from dashboard.app import main as dash_main
    dash_main()


def cmd_all(args):
    """Run full pipeline sequentially."""
    from analysis.db_schema import init_analysis_tables
    init_analysis_tables()

    print("=" * 60)
    print("Phase 0: Data Preparation")
    print("=" * 60)
    from analysis.prepare import run_prepare
    run_prepare(skip_llm=getattr(args, 'skip_llm', False))

    print("\n" + "=" * 60)
    print("Phase 1: Embedding + Clustering")
    print("=" * 60)
    from analysis.embed_cluster import run_embed, run_cluster
    run_embed()
    run_cluster()

    print("\n" + "=" * 60)
    print("Phase 2: Hierarchy + LLM Labels")
    print("=" * 60)
    from analysis.hierarchy import run_hierarchy
    run_hierarchy()

    print("\n" + "=" * 60)
    print("Phase 3: Emotion & Stance Analysis")
    print("=" * 60)
    from analysis.emotions import run_emotions, run_stance
    run_emotions()
    run_stance()

    print("\n" + "=" * 60)
    print("Phase 4: Aggregation")
    print("=" * 60)
    from analysis.precompute import run_aggregate
    run_aggregate()

    print("\n" + "=" * 60)
    print("Phase 5: Edge Computation")
    print("=" * 60)
    from analysis.edges import run_edges
    run_edges()

    print("\n" + "=" * 60)
    print("Pipeline complete! Run 'python run_analysis.py dashboard' to view results.")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="AI in K-12 Education: Topic Modeling & Emotion Analysis Pipeline"
    )
    sub = parser.add_subparsers(dest="command", help="Pipeline phase to run")

    p_prepare = sub.add_parser("prepare", help="Phase 0: Fill missing summaries, build embed texts")
    p_prepare.add_argument("--skip-llm", action="store_true",
                           help="Skip LLM summary regeneration (use title as fallback)")
    sub.add_parser("embed", help="Phase 1: Embed + BERTopic clustering")
    sub.add_parser("hierarchy", help="Phase 2: L1/L2 topics + LLM labels")
    sub.add_parser("emotions", help="Phase 3: Emotion + stance on comments")
    sub.add_parser("aggregate", help="Phase 4: Pre-aggregate for dashboard")
    sub.add_parser("edges", help="Phase 5: Compute KNN post edges + topic edges")
    sub.add_parser("dashboard", help="Launch Plotly Dash app")
    sub.add_parser("all", help="Run full pipeline (Phases 0-5)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "prepare": cmd_prepare,
        "embed": cmd_embed,
        "hierarchy": cmd_hierarchy,
        "emotions": cmd_emotions,
        "aggregate": cmd_aggregate,
        "edges": cmd_edges,
        "dashboard": cmd_dashboard,
        "all": cmd_all,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
