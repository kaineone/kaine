# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CLI entry point for the module-ignition study runner."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from kaine import legacy_aliases
from kaine.config import load_kaine_config
from kaine.defaults import DEFAULT_REDIS_PORT
from kaine.research.ignition_study import analysis
from kaine.research.ignition_study.plan import (
    DEFAULT_DEVELOPMENT_BUDGET_SECONDS,
    DEFAULT_VIEWING_BUDGET_SECONDS,
    init_study,
    load_plan,
    programme_sha256,
    validate_plan,
)
from kaine.research.ignition_study.runner import (
    WELFARE_DECISIONS,
    StudyComplete,
    StudyCritical,
    StudyError,
    StudyHalted,
    StudyLocked,
    StudyRunner,
    StudyWelfareHold,
    failed_hold_line,
)
from kaine.storage import install_data_root, resolve


def _default_order() -> list[str]:
    # The effectors, perceptual locus and embodiment modules need an effector, body or alternative
    # sensor feed; on the reference host they would be expected nulls (use --order).
    return [
        "episodic_memory",
        "world_model",
        "planning",
        "self_model",
        "social_cognition",
        "vocal",
    ]


def _parse_voice_alignment_step(value: str) -> dict[str, Any]:
    """Parse a ``LINE:K`` voice-alignment step for argparse."""
    if ":" not in value:
        raise argparse.ArgumentTypeError(
            f"Invalid voice alignment step: {value!r}; expected LINE:K"
        )
    line, k_str = value.split(":", 1)
    try:
        k = int(k_str)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid voice alignment step: {value!r}; expected LINE:K ({exc})"
        ) from exc
    return {"line": line, "k": k}


def _cmd_init(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    manifest = Path(args.programme_manifest).resolve()
    protocol = getattr(args, "protocol", "branching")

    if protocol == "progressive":
        plan: dict[str, Any] = {
            "protocol": "progressive",
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
                "db": args.db_progressive,
            },
            "viewing_budget_seconds": args.viewing_budget_seconds,
            "development_budget_seconds": args.development_budget_seconds,
            "min_free_gb": args.min_free_gb,
        }
        if args.broadcast_capacity is not None:
            plan["broadcast_capacity"] = args.broadcast_capacity
        if args.collection_prefix is not None:
            plan["collection_prefix"] = args.collection_prefix
        if args.voice_alignment_step_index:
            plan["voice_alignment_steps"] = [
                {"step_index": i} for i in args.voice_alignment_step_index
            ]
    else:
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
                    "development": args.db_development,
                    "branch": args.db_branch,
                    "repeat": args.db_repeat,
                    "accumulate": args.db_accumulate,
                },
            },
            "collections": {
                "development": f"study_{args.study_id}_g_",
                "branch": f"study_{args.study_id}_b_",
                "repeat": f"study_{args.study_id}_r_",
                "accumulate": f"study_{args.study_id}_a_",
            },
            "viewing_budget_seconds": args.viewing_budget_seconds,
            "development_budget_seconds": args.development_budget_seconds,
            "min_free_gb": args.min_free_gb,
        }
        if args.voice_alignment_step:
            plan["voice_alignment_steps"] = list(args.voice_alignment_step)
    # validate_plan returns the normalised plan (its defaults filled in); that
    # is what the study records, so study.json shows every setting it runs with.
    plan = validate_plan(plan)

    study_dir = resolve(
        Path(args.study_dir)
        if args.study_dir
        else Path("studies") / args.study_id
    )
    init_study(study_dir, plan)
    print(f"Initialized study at {study_dir}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    study_dir = resolve(Path(args.study_dir))
    try:
        runner = StudyRunner(study_dir)
        runner.run(retry_failed=args.retry_failed)
        print("Study complete")
        return 0
    except StudyHalted as exc:
        rec = exc.record
        print(
            f"Study halted: {rec['outcome']} at {rec['line']} step {rec['step']}",
            file=sys.stderr,
        )
        try:
            check = StudyRunner(study_dir)
            failed_hold = check.unanswered_failed_hold()
            if failed_hold is not None:
                print(
                    failed_hold_line(
                        failed_hold, study_dir, check.failed_welfare_hold() is not None
                    ),
                    file=sys.stderr,
                )
        except StudyError as err:
            # The halt itself is already reported; say that its welfare hold
            # could not be checked rather than imply there is none.
            print(f"Welfare hold not checked: {err}", file=sys.stderr)
        return 1
    except StudyWelfareHold as exc:
        rec = exc.record
        reasons = ", ".join((rec.get("welfare_hold") or {}).get("reasons") or [])
        if str(rec.get("outcome", "")).startswith("failed"):
            what = (
                f"Study held for welfare review: {rec['line']} step {rec['step']} failed "
                f"({rec['outcome']}) after the welfare net acted or an indicator crossed "
                f"({reasons}). The step is not retried until a person answers: "
            )
        else:
            what = (
                f"Study held for welfare review after {rec['line']} step {rec['step']} "
                f"({reasons}). The next step does not start until a person answers: "
            )
        print(
            what
            + f"python -m kaine.research.ignition_study ack-welfare --study-dir "
            f"{study_dir} --step {rec['line']}/{rec['step']} --decision continue|stop",
            file=sys.stderr,
        )
        return 4
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
    study_dir = resolve(Path(args.study_dir))
    # Re-validate the plan is readable, then show progress.
    _ = load_plan(study_dir)
    try:
        runner = StudyRunner(study_dir)
    except StudyError as exc:
        print(f"Cannot read study: {exc}", file=sys.stderr)
        return 2
    print(runner.status())
    return 0


def _cmd_ack_welfare(args: argparse.Namespace) -> int:
    """Record the operator's answer to a welfare hold. Never edits an entity's state."""
    study_dir = resolve(Path(args.study_dir))
    line, sep, k_text = args.step.partition("/")
    try:
        k = int(k_text)
    except ValueError:
        k = -1
    if not sep or not line or k < 0:
        print("--step must be LINE/K, for example development/0", file=sys.stderr)
        return 2
    try:
        runner = StudyRunner(study_dir)
        ack = runner.acknowledge_welfare(line, k, args.decision)
    except StudyError as exc:
        print(f"Cannot record the answer: {exc}", file=sys.stderr)
        return 2
    print(
        f"Recorded {ack['decision']} for {line} step {k} at {ack['acknowledged_at']}"
        + ("; the line has ended and its preservations are kept" if ack["decision"] == "stop" else "")
    )
    return 0


def _cmd_analyse(args: argparse.Namespace) -> int:
    study_dir = resolve(Path(args.study_dir))
    json_path, md_path = analysis.run_analysis(study_dir)
    print(f"Wrote analysis report to {json_path} and {md_path}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
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
        default=["interoception", "sequence", "vision", "audition", "language", "affect", "sleep"],
    )
    init_p.add_argument("--order", nargs="+", default=_default_order())
    init_p.add_argument("--programme-manifest", required=True)
    init_p.add_argument("--redis-base-url", default=f"redis://127.0.0.1:{DEFAULT_REDIS_PORT}")
    init_p.add_argument("--db-development", dest="db_development", type=int, default=10)
    init_p.add_argument("--db-branch", type=int, default=11)
    init_p.add_argument("--db-repeat", type=int, default=12)
    init_p.add_argument("--db-accumulate", type=int, default=13)
    init_p.add_argument(
        "--viewing-budget-seconds",
        type=float,
        default=DEFAULT_VIEWING_BUDGET_SECONDS,
    )
    init_p.add_argument(
        "--development-budget-seconds",
        dest="development_budget_seconds",
        type=float,
        default=DEFAULT_DEVELOPMENT_BUDGET_SECONDS,
    )
    init_p.add_argument(
        "--min-free-gb",
        type=float,
        default=20.0,
    )
    init_p.add_argument(
        "--protocol",
        choices=["progressive", "branching"],
        default="branching",
        help="plan protocol: progressive (development run) or branching (study)",
    )
    init_p.add_argument(
        "--db-progressive",
        type=int,
        default=10,
        help="single Redis db for the progressive protocol (1-15)",
    )
    init_p.add_argument(
        "--broadcast-capacity",
        type=int,
        default=None,
        help="workspace broadcast capacity (progressive only)",
    )
    init_p.add_argument(
        "--collection-prefix",
        type=str,
        default=None,
        help="Chromadb collection prefix (progressive only, default: devrun)",
    )
    init_p.add_argument(
        "--voice-alignment-step-index",
        action="append",
        type=int,
        default=None,
        help="step index for voice alignment (progressive only, repeatable)",
    )
    init_p.add_argument(
        "--voice-alignment-step",
        action="append",
        default=None,
        type=_parse_voice_alignment_step,
        help="pre-register a voice-alignment step as LINE:K (repeatable)",
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

    ack_p = sub.add_parser(
        "ack-welfare",
        help="answer a welfare hold: continue to the next step, or stop the line",
    )
    ack_p.add_argument("--study-dir", required=True)
    ack_p.add_argument("--step", required=True, help="the held step as LINE/K")
    ack_p.add_argument("--decision", required=True, choices=WELFARE_DECISIONS)

    analyse_p = sub.add_parser(
        "analyse",
        help="analyse completed ignition viewings and write the report",
    )
    analyse_p.add_argument("--study-dir", required=True)

    legacy_aliases.add_cli_aliases(init_p)
    legacy_aliases.add_cli_aliases(run_p)
    legacy_aliases.add_cli_aliases(status_p)
    legacy_aliases.add_cli_aliases(analyse_p)
    legacy_aliases.add_cli_aliases(ack_p)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        install_data_root(load_kaine_config())
    except Exception as exc:
        # Without a config the study/setup still runs with paths relative to
        # the working directory, exactly as before a data root existed.
        print(f"kaine: could not load config; no data root installed ({exc})", file=sys.stderr)

    parser = _build_parser()

    args = parser.parse_args(argv)
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "analyse":
        return _cmd_analyse(args)
    if args.command == "ack-welfare":
        return _cmd_ack_welfare(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
