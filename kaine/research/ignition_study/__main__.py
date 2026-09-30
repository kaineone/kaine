# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CLI entry point for the module-ignition study runner."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kaine.research.ignition_study import analysis
from kaine.research.ignition_study.plan import (
    DEFAULT_GESTATION_BUDGET_SECONDS,
    DEFAULT_VIEWING_BUDGET_SECONDS,
    init_study,
    load_plan,
    programme_sha256,
    validate_plan,
)
from kaine.research.ignition_study.runner import (
    StudyComplete,
    StudyCritical,
    StudyError,
    StudyHalted,
    StudyLocked,
    StudyRunner,
)


def _default_order() -> list[str]:
    return [
        "mnemos",
        "phantasia",
        "nous",
        "eidolon",
        "empatheia",
        "vox",
        "praxis",
        "perception",
        "mundus",
    ]


def _cmd_init(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    manifest = Path(args.programme_manifest).resolve()
    plan = {
        "study_id": args.study_id,
        "repo_root": str(repo_root),
        "base_modules": args.base_modules,
        "order": args.order,
        "programme": {
            "manifest": str(manifest),
            "sha256": programme_sha256(manifest),
        },
        "redis": {
            "base_url": args.redis_base_url,
            "db": {
                "gestation": args.db_gestation,
                "branch": args.db_branch,
                "repeat": args.db_repeat,
                "accumulate": args.db_accumulate,
            },
        },
        "collections": {
            "gestation": f"study_{args.study_id}_g_",
            "branch": f"study_{args.study_id}_b_",
            "repeat": f"study_{args.study_id}_r_",
            "accumulate": f"study_{args.study_id}_a_",
        },
        "viewing_budget_seconds": args.viewing_budget_seconds,
        "gestation_budget_seconds": args.gestation_budget_seconds,
        "min_free_gb": args.min_free_gb,
    }
    validate_plan(plan)

    study_dir = (
        Path(args.study_dir)
        if args.study_dir
        else Path("studies") / args.study_id
    )
    init_study(study_dir, plan)
    print(f"Initialized study at {study_dir}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        runner = StudyRunner(args.study_dir)
        runner.run(retry_failed=args.retry_failed)
        print("Study complete")
        return 0
    except StudyHalted as exc:
        rec = exc.record
        print(
            f"Study halted: {rec['outcome']} at {rec['line']} step {rec['step']}",
            file=sys.stderr,
        )
        return 1
    except StudyComplete:
        print("Study complete")
        return 0
    except StudyLocked as exc:
        print(f"Cannot run study: {exc}", file=sys.stderr)
        return 2
    except StudyCritical as exc:
        print(
            f"Study halted, operator action needed: {exc}. Stop the cycle, then "
            "re-run with --retry-failed.",
            file=sys.stderr,
        )
        return 3
    except StudyError as exc:
        print(f"Cannot run study: {exc}", file=sys.stderr)
        return 2


def _cmd_status(args: argparse.Namespace) -> int:
    # Re-validate the plan is readable, then show progress.
    _ = load_plan(args.study_dir)
    try:
        runner = StudyRunner(args.study_dir)
    except StudyError as exc:
        print(f"Cannot read study: {exc}", file=sys.stderr)
        return 2
    print(runner.status())
    return 0


def _cmd_analyse(args: argparse.Namespace) -> int:
    json_path, md_path = analysis.run_analysis(args.study_dir)
    print(f"Wrote analysis report to {json_path} and {md_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kaine.research.ignition_study"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="create a study directory and manifest")
    init_p.add_argument("--study-id", required=True)
    init_p.add_argument("--study-dir", default=None)
    init_p.add_argument("--repo-root", default=str(Path.cwd()))
    init_p.add_argument(
        "--base-modules",
        nargs="+",
        default=["soma", "chronos", "topos", "audition", "lingua", "thymos", "hypnos"],
    )
    init_p.add_argument("--order", nargs="+", default=_default_order())
    init_p.add_argument("--programme-manifest", required=True)
    init_p.add_argument("--redis-base-url", default="redis://127.0.0.1:6479")
    init_p.add_argument("--db-gestation", type=int, default=10)
    init_p.add_argument("--db-branch", type=int, default=11)
    init_p.add_argument("--db-repeat", type=int, default=12)
    init_p.add_argument("--db-accumulate", type=int, default=13)
    init_p.add_argument(
        "--viewing-budget-seconds",
        type=float,
        default=DEFAULT_VIEWING_BUDGET_SECONDS,
    )
    init_p.add_argument(
        "--gestation-budget-seconds",
        type=float,
        default=DEFAULT_GESTATION_BUDGET_SECONDS,
    )
    init_p.add_argument(
        "--min-free-gb",
        type=float,
        default=20.0,
    )

    run_p = sub.add_parser("run", help="run or resume the study")
    run_p.add_argument("--study-dir", required=True)
    run_p.add_argument(
        "--retry-failed",
        action="store_true",
        help="re-run the most recent failed step from the same start bundle",
    )

    status_p = sub.add_parser("status", help="show progress")
    status_p.add_argument("--study-dir", required=True)

    analyse_p = sub.add_parser(
        "analyse",
        help="analyse completed ignition viewings and write the report",
    )
    analyse_p.add_argument("--study-dir", required=True)

    args = parser.parse_args(argv)
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "analyse":
        return _cmd_analyse(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
