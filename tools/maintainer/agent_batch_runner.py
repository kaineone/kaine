# SPDX-License-Identifier: LicenseRef-CAL-0.5
"""Agent batch runner for KAINE maintainer jobs (Ollama worker workflow)."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

MAX_CONCURRENCY = 4
SPDX = "SPDX-License-Identifier: LicenseRef-CAL-0.5"


def sanitize_id(value: Any) -> str:
    text = str(value).strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    text = text.strip("._-")
    return text or "job"


def _clean_mapping(mapping: Any) -> dict[str, Any] | None:
    if not isinstance(mapping, dict):
        return None
    return {str(k): v for k, v in mapping.items() if v is not None}


def normalize_job(job: Any, index: int | None = None) -> dict[str, Any]:
    if isinstance(job, str):
        job = {"command": job}
    if not isinstance(job, dict):
        job = {"value": job}
    original = dict(job)

    def first(*keys: str, default: Any = None) -> Any:
        for key in keys:
            if key in job and job.get(key) is not None:
                return job.get(key)
        return default

    job_id = first("id", "name", "title", "task", "job", "job_id")
    if job_id is None:
        job_id = f"job_{index}" if index is not None else "job"

    brief = first("brief", "brief_path", "brief_file", "prompt", "prompt_file", "brief_text")
    allow = first("allow", "allow_paths", "allowed", "allowed_paths", "paths")
    if isinstance(allow, str):
        allow = [allow]
    if allow is None:
        allow = []

    apply_flag = first("apply", "apply_output", "write", "do_apply", default=True)
    verify = first("verify", "verification", "verify_command", "verify_commands", "checks")
    tests = first("tests", "test", "test_command", "test_commands", "validation")
    cmd = first("command", "worker_command", "apply_command", "run", "action", "script")
    cwd = first("cwd", "working_dir", "workdir", "path", "workspace", "root")
    timeout = first("timeout", "time_limit", "timeout_seconds")
    retries = first("retries", "retry_count", "max_retries", "attempts", default=0)
    try:
        retries = max(0, int(retries))
    except (TypeError, ValueError):
        retries = 0
    lane = first("lane", "lane_id", "worker_lane")
    try:
        lane = int(lane) if lane is not None else None
    except (TypeError, ValueError):
        lane = None
    model = first("model", "worker_model")

    return {
        "id": str(job_id),
        "brief": brief,
        "allow": [str(x) for x in allow],
        "apply": bool(apply_flag),
        "verify": verify,
        "tests": tests,
        "command": cmd,
        "cwd": cwd,
        "timeout": timeout,
        "retries": retries,
        "lane": lane,
        "model": model,
        "env": _clean_mapping(first("env", "environment", "environment_variables")),
        "raw": original,
    }


def load_queue(queue: Any) -> Any:
    if isinstance(queue, str):
        path = Path(queue)
        if path.is_file():
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        try:
            return json.loads(queue)
        except json.JSONDecodeError:
            pass
    if isinstance(queue, (os.PathLike, Path)):
        path = Path(queue)
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    return queue


def _extract_jobs(data: Any) -> list[Any]:
    if isinstance(data, dict):
        for key in ("jobs", "queue", "tasks", "items", "work", "commands"):
            if isinstance(data.get(key), list):
                return data[key]
        if isinstance(data.get("job"), dict):
            return [data["job"]]
        return [data]
    if isinstance(data, list):
        return data
    return [data]


def normalize_queue(data: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if isinstance(data, (str, os.PathLike, Path)):
        data = load_queue(data)
    meta = data if isinstance(data, dict) else {}
    jobs_raw = _extract_jobs(data)
    jobs = [normalize_job(item, index=i) for i, item in enumerate(jobs_raw)]
    return meta, jobs


def assign_lanes(jobs: Any, lanes: int = MAX_CONCURRENCY) -> list[list[dict[str, Any]]]:
    count = max(1, min(int(lanes or 1), MAX_CONCURRENCY))
    result: list[list[dict[str, Any]]] = [[] for _ in range(count)]
    normalized = []
    for i, job in enumerate(jobs):
        if isinstance(job, dict) and "id" in job and "command" in job and "brief" in job:
            normalized.append(job)
        else:
            normalized.append(normalize_job(job, index=i))

    for index, job in enumerate(normalized):
        lane = job.get("lane")
        if lane is None:
            lane_idx = index % count
        else:
            try:
                lane_idx = int(lane) % count
            except (TypeError, ValueError):
                lane_idx = index % count
        job["lane"] = lane_idx
        result[lane_idx].append(job)
    return result


def _command_to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def run_command(command: Any, cwd: Any = None, env: dict[str, Any] | None = None,
                timeout: float | None = None, shell: bool | None = None) -> dict[str, Any]:
    started = time.monotonic()
    if isinstance(command, (list, tuple)):
        args: Any = list(command)
        use_shell = False if shell is None else shell
    else:
        args = str(command)
        use_shell = True if shell is None else shell
    merged_env = None
    if env:
        merged_env = dict(os.environ)
        merged_env.update({str(k): str(v) for k, v in env.items()})
    try:
        proc = subprocess.run(
            args, cwd=str(cwd) if cwd is not None else None,
            env=merged_env, timeout=timeout, shell=use_shell,
            capture_output=True, text=True)
        returncode = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + "\ncommand timed out"
    except FileNotFoundError as exc:
        returncode = 127
        stdout = ""
        stderr = str(exc)
    except Exception as exc:
        returncode = 1
        stdout = ""
        stderr = str(exc)
    return {
        "ok": returncode == 0,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def _write_brief(job: dict[str, Any], out_dir: Path) -> Path:
    brief = job.get("brief")
    path = out_dir / "brief.txt"
    if isinstance(brief, (str, os.PathLike, Path)):
        src = Path(brief)
        if src.is_file():
            path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            return path
    if isinstance(brief, str):
        path.write_text(brief, encoding="utf-8")
        return path
    # brief_text support
    if isinstance(brief, dict):
        text = brief.get("text") or brief.get("content") or json.dumps(brief)
        path.write_text(str(text), encoding="utf-8")
        return path
    if brief is None:
        path.write_text("", encoding="utf-8")
        return path
    path.write_text(str(brief), encoding="utf-8")
    return path


def _parse_file_blocks(response_text: str) -> list[str]:
    paths = []
    for line in response_text.splitlines():
        m = re.match(r"^@@@FILE\s+(\S+)", line)
        if m:
            paths.append(m.group(1))
    return paths


def run_ollama_worker(
    job: dict[str, Any],
    lane_idx: int,
    out_dir: Any,
    *,
    repo: Any = None,
    worker_script: Any,
    model: str,
    max_retries: int,
    timeout: float | None,
    semaphore: threading.Semaphore,
    defaults: dict[str, Any],
    retry_base_delay: float = 1.0,
    retry_max_delay: float = 10.0,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    worker_script = Path(worker_script)
    repo = Path(repo).resolve() if repo is not None else None
    effective_model = job.get("model") or model or defaults.get("model") or "kimi-k2.7-code:cloud"
    allow = job.get("allow") or []
    apply_flag = bool(job.get("apply", True))
    retries = max(int(job.get("retries", 0) or 0), int(max_retries or 0))

    _write_brief(job, out_dir)
    brief_path = out_dir / "brief.txt"

    attempt = 0
    last_error = None
    last_stdout = ""
    last_stderr = ""
    result: dict[str, Any] = {
        "ok": False,
        "attempts": 0,
        "files": [],
        "apply_requested": apply_flag,
    }
    while attempt <= retries:
        attempt += 1
        cmd = [sys.executable, str(worker_script), str(brief_path), str(out_dir)]
        cmd += ["--model", effective_model]
        if allow:
            cmd += ["--allow"] + [str(p) for p in allow]
        if apply_flag and repo is not None and allow:
            cmd += ["--apply", str(repo)]
        with semaphore:
            try:
                proc = subprocess.run(
                    cmd, cwd=str(repo) if repo else None,
                    capture_output=True, text=True,
                    timeout=timeout or 3900,
                )
                rc = proc.returncode
                stdout = proc.stdout or ""
                stderr = proc.stderr or ""
            except subprocess.TimeoutExpired as exc:
                rc = 124
                stdout = exc.stdout or ""
                stderr = (exc.stderr or "") + "\nworker timed out"
            except Exception as exc:
                rc = 1
                stdout = ""
                stderr = str(exc)
        last_stdout = stdout
        last_stderr = stderr
        # inspect response
        response_text = ""
        response_path = out_dir / "response.txt"
        if response_path.exists():
            try:
                response_text = response_path.read_text(encoding="utf-8")
            except Exception:
                response_text = ""
        empty = len(response_text.strip()) < 10
        files = _parse_file_blocks(response_text)
        (out_dir / f"worker_attempt_{attempt}.stdout").write_text(stdout, encoding="utf-8")
        (out_dir / f"worker_attempt_{attempt}.stderr").write_text(stderr, encoding="utf-8")
        if rc == 0 and not empty:
            result.update({
                "ok": True,
                "returncode": rc,
                "attempts": attempt,
                "stdout": stdout,
                "stderr": stderr,
                "files": files,
            })
            break
        last_error = f"rc={rc} empty={empty} stderr={stderr[:500]}"
        # backoff
        if attempt <= retries:
            base = max(0.0, float(retry_base_delay or 0.0))
            cap = max(base, float(retry_max_delay or 0.0))
            delay = min(cap, base * (2 ** (attempt - 1)) + random.random() * 0.5)
            time.sleep(delay)
    if not result.get("ok"):
        result.update({
            "ok": False,
            "attempts": attempt,
            "error": last_error,
            "stdout": last_stdout,
            "stderr": last_stderr,
            "files": _parse_file_blocks(response_text) if response_text else [],
        })
    (out_dir / "worker_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _run_boundary_commands(commands: Any, cwd: Path | None, env: dict[str, Any] | None,
                          timeout: float | None, out_dir: Path, name: str) -> dict[str, Any]:
    command_list = []
    if isinstance(commands, (list, tuple)):
        # if list of strings/commands, run each
        command_list = list(commands)
    elif commands is None:
        command_list = []
    else:
        command_list = [commands]
    if not command_list:
        status = {"status": "skipped", "reason": "no command", "results": []}
        (out_dir / f"{name}_result.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
        return status
    results = []
    for idx, command in enumerate(command_list):
        r = run_command(command, cwd=cwd, env=env, timeout=timeout)
        results.append(r)
        (out_dir / f"{name}_{idx}.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
        if not r["ok"]:
            break
    overall_ok = len(results) > 0 and all(r.get("ok") for r in results)
    status = {
        "status": "passed" if overall_ok else "failed",
        "results": results,
        "exit_code": results[-1]["returncode"] if results else 0,
    }
    (out_dir / f"{name}_result.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status


def _job_cwd(job: dict[str, Any], default_cwd: Path | None) -> Path | None:
    cwd = job.get("cwd")
    if cwd is not None:
        return Path(cwd)
    return default_cwd


def process_job(
    job: dict[str, Any],
    lane_idx: int,
    out_root: Any,
    *,
    repo: Path | None,
    worker_script: Any,
    model: str,
    max_retries: int,
    timeout: float | None,
    semaphore: threading.Semaphore,
    defaults: dict[str, Any],
    default_cwd: Path | None,
    retry_base_delay: float = 1.0,
    retry_max_delay: float = 10.0,
) -> dict[str, Any]:
    out_root = Path(out_root)
    job_id = sanitize_id(job.get("id"))
    out_dir = out_root / f"lane_{lane_idx}" / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "job.json").write_text(json.dumps(job, indent=2, default=str), encoding="utf-8")

    started = time.monotonic()
    state: dict[str, Any] = {
        "job_id": job.get("id"),
        "lane": lane_idx,
        "out_dir": str(out_dir),
        "boundaries": {
            "generation": "pending",
            "apply": "pending",
            "verify": "pending",
            "test": "pending",
        },
        "status": "running",
    }

    # generation boundary
    worker_result = run_ollama_worker(
        job, lane_idx, out_dir,
        repo=repo, worker_script=worker_script, model=model,
        max_retries=max_retries, timeout=timeout, semaphore=semaphore,
        defaults=defaults, retry_base_delay=retry_base_delay,
        retry_max_delay=retry_max_delay,
    )
    state["worker"] = {
        "ok": worker_result.get("ok"),
        "attempts": worker_result.get("attempts"),
        "files": worker_result.get("files", []),
        "error": worker_result.get("error"),
    }
    state["boundaries"]["generation"] = "passed" if worker_result.get("ok") else "failed"
    state["boundaries"]["apply"] = ("passed" if (job.get("apply", True) and worker_result.get("ok")) else
                                     ("skipped" if not job.get("apply", True) else "failed"))

    # verify boundary
    verify_cmds = job.get("verify")
    if verify_cmds is None:
        verify_cmds = defaults.get("verify_default")
    cwd = _job_cwd(job, default_cwd or repo)
    verify_result = _run_boundary_commands(verify_cmds, cwd, job.get("env"), timeout, out_dir, "verify")
    state["verify_result"] = verify_result
    state["boundaries"]["verify"] = verify_result["status"] if verify_result["results"] or verify_cmds else "skipped"

    # test boundary
    test_cmds = job.get("tests")
    if test_cmds is None:
        test_cmds = defaults.get("test_default")
    test_result = _run_boundary_commands(test_cmds, cwd, job.get("env"), timeout, out_dir, "test")
    state["test_result"] = test_result
    state["boundaries"]["test"] = test_result["status"] if test_result["results"] or test_cmds else "skipped"

    # final status
    ok = worker_result.get("ok", False)
    if job.get("apply", True) and not worker_result.get("ok"):
        ok = False
    if verify_result.get("status") == "failed":
        ok = False
    if test_result.get("status") == "failed":
        ok = False
    state["status"] = "ok" if ok else "failed"
    state["duration_seconds"] = round(time.monotonic() - started, 3)
    state["touched_files"] = worker_result.get("files", [])
    (out_dir / "job_state.json").write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    return state


def _lane_worker(lane_idx: int, jobs: list[dict[str, Any]], shared: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for job in jobs:
        state = process_job(job, lane_idx, shared["out_root"], repo=shared["repo"],
                            worker_script=shared["worker_script"], model=shared["model"],
                            max_retries=shared["max_retries"], timeout=shared["timeout"],
                            semaphore=shared["semaphore"], defaults=shared["defaults"],
                            default_cwd=shared["default_cwd"],
                            retry_base_delay=shared.get("retry_base_delay", 1.0),
                            retry_max_delay=shared.get("retry_max_delay", 10.0))
        results.append(state)
    return results


def process_queue(
    queue: Any,
    *,
    lanes: int = MAX_CONCURRENCY,
    out_root: Any = None,
    repo: Any = None,
    model: str | None = None,
    worker_script: Any = None,
    max_retries: int = 0,
    timeout: float | None = None,
    defaults: dict[str, Any] | None = None,
    dry_run: bool = False,
    default_cwd: Any = None,
    retry_base_delay: float = 1.0,
    retry_max_delay: float = 10.0,
) -> dict[str, Any]:
    raw = load_queue(queue)
    meta, jobs = normalize_queue(raw)
    defaults = defaults or {}

    # meta overrides
    meta_lanes = meta.get("lanes", lanes)
    meta_repo = meta.get("repo", repo)
    meta_out = meta.get("out_root", out_root)
    meta_model = meta.get("model", model)
    meta_worker = meta.get("worker", worker_script)
    meta_retries = meta.get("max_retries", max_retries)
    meta_verify = meta.get("verify_default", defaults.get("verify_default"))
    meta_test = meta.get("test_default", defaults.get("test_default"))
    meta_base_delay = meta.get("retry_base_delay", retry_base_delay)
    meta_max_delay = meta.get("retry_max_delay", retry_max_delay)
    defaults = dict(defaults)
    defaults["verify_default"] = meta_verify
    defaults["test_default"] = meta_test

    lanes_eff = max(1, min(int(meta_lanes or lanes or 1), MAX_CONCURRENCY))
    repo_path = Path(meta_repo).resolve() if meta_repo else None
    out_path = Path(meta_out) if meta_out else Path("agent_batch_out")
    out_path.mkdir(parents=True, exist_ok=True)
    worker_path = Path(meta_worker) if meta_worker else Path(__file__).with_name("worker.py")
    worker_path = worker_path.resolve()
    effective_model = meta_model or model or "kimi-k2.7-code:cloud"
    effective_retries = int(meta_retries if meta_retries is not None else max_retries)
    effective_timeout = timeout if timeout is not None else None
    if effective_timeout is None and meta.get("timeout") is not None:
        effective_timeout = meta.get("timeout")

    lane_groups = assign_lanes(jobs, lanes_eff)

    if dry_run:
        preview = {
            "lanes": lanes_eff,
            "repo": str(repo_path) if repo_path else None,
            "out_root": str(out_path),
            "jobs": [
                {"id": j.get("id"), "lane": j.get("lane"), "allow": j.get("allow"),
                 "apply": j.get("apply"), "verify": j.get("verify"), "tests": j.get("tests")}
                for j in jobs
            ],
        }
        (out_path / "dry_run.json").write_text(json.dumps(preview, indent=2), encoding="utf-8")
        return preview

    sem = threading.Semaphore(lanes_eff)
    shared = {
        "repo": repo_path,
        "out_root": out_path,
        "worker_script": worker_path,
        "model": effective_model,
        "max_retries": effective_retries,
        "timeout": effective_timeout,
        "semaphore": sem,
        "defaults": defaults,
        "default_cwd": Path(default_cwd) if default_cwd else (repo_path if repo_path else None),
        "retry_base_delay": meta_base_delay,
        "retry_max_delay": meta_max_delay,
    }

    all_results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=lanes_eff) as executor:
        futures = []
        for lane_idx, group in enumerate(lane_groups):
            futures.append(executor.submit(_lane_worker, lane_idx, group, shared))
        for future in concurrent.futures.as_completed(futures):
            all_results.extend(future.result())

    # preserve job order
    order = {j.get("id"): i for i, j in enumerate(jobs)}
    all_results.sort(key=lambda x: order.get(x.get("job_id"), 9999))

    summary = {
        "lanes": lanes_eff,
        "repo": str(repo_path) if repo_path else None,
        "out_root": str(out_path),
        "total_jobs": len(jobs),
        "succeeded": sum(1 for r in all_results if r.get("status") == "ok"),
        "failed": sum(1 for r in all_results if r.get("status") != "ok"),
        "jobs": all_results,
    }
    (out_path / "run_state.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


def _render_report(summary: dict[str, Any]) -> str:
    lines = []
    lines.append("# Agent batch run report")
    lines.append("")
    lines.append(f"- Lanes (global max): {summary.get('lanes')}")
    lines.append(f"- Total jobs: {summary.get('total_jobs')}")
    lines.append(f"- Succeeded: {summary.get('succeeded')}")
    lines.append(f"- Failed: {summary.get('failed')}")
    lines.append("")
    lines.append("| Job | Lane | Status | Generation | Apply | Verify | Test | Files |")
    lines.append("|---|---:|---|---|---|---|---|---|")
    for job in summary.get("jobs", []):
        b = job.get("boundaries", {})
        files = ", ".join(job.get("touched_files", []) or [])
        lines.append(
            f"| {job.get('job_id')} | {job.get('lane')} | {job.get('status')} | "
            f"{b.get('generation')} | {b.get('apply')} | {b.get('verify')} | {b.get('test')} | {files} |"
        )
    lines.append("")
    lines.append("## Integration boundaries")
    for job in summary.get("jobs", []):
        b = job.get("boundaries", {})
        crossed = [name for name, state in b.items() if state == "passed"]
        lines.append(f"- {job.get('job_id')}: crossed {', '.join(crossed) if crossed else 'none'}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run KAINE agent jobs in parallel lanes.")
    parser.add_argument("queue", nargs="?", help="Path to a JSON job queue")
    parser.add_argument("-q", "--queue", dest="queue_opt", help="Path to a JSON job queue")
    parser.add_argument("-n", "--lanes", type=int, default=MAX_CONCURRENCY)
    parser.add_argument("-o", "--out-dir", "--out-root", dest="out_dir", default=None)
    parser.add_argument("--report", nargs="?", const="report.md", default=None)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--retry-base-delay", type=float, default=1.0)
    parser.add_argument("--retry-max-delay", type=float, default=10.0)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--cwd", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--worker", default=None)
    args = parser.parse_args(argv)

    queue_path = args.queue or args.queue_opt
    if queue_path is None:
        parser.error("queue path is required")

    defaults = {}
    if args.model:
        defaults["model"] = args.model

    summary = process_queue(
        queue_path,
        lanes=args.lanes,
        out_root=args.out_dir,
        model=args.model,
        worker_script=args.worker,
        max_retries=args.retries,
        timeout=args.timeout,
        dry_run=args.dry_run,
        default_cwd=args.cwd,
        defaults=defaults,
        retry_base_delay=args.retry_base_delay,
        retry_max_delay=args.retry_max_delay,
    )

    if args.report:
        report_path = Path(args.report)
        report_path.write_text(_render_report(summary), encoding="utf-8")
        print(f"report written to {report_path}")

    print(json.dumps({
        "total_jobs": summary.get("total_jobs", 0),
        "succeeded": summary.get("succeeded", 0),
        "failed": summary.get("failed", 0),
        "out_root": summary.get("out_root"),
    }, indent=2))
    return 0 if summary.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
