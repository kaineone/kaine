#!/usr/bin/env python3
"""Dark-factory controller: autonomous OpenSpec task execution via Ollama workers."""
import argparse, datetime, hashlib, json, os, re, shutil, shlex, subprocess, sys, time
from pathlib import Path
from typing import Tuple

ROOT = Path.cwd()
DEFAULT_CONFIG = Path("config/dark-factory.json")


class TaskFailed(Exception):
    pass


def load_config(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def check_disk(cfg):
    limit = cfg.get("min_free_gb", 20)
    st = os.statvfs(str(ROOT))
    free_gb = (st.f_bavail * st.f_frsize) / (1024 ** 3)
    if free_gb < limit:
        raise RuntimeError(f"disk free {free_gb:.1f}GB < {limit}GB, stopping")


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(ROOT))


def run_cmd(cmd: str):
    try:
        argv = shlex.split(cmd)
    except ValueError:
        argv = ["/bin/sh", "-c", cmd]
    return subprocess.run(argv, capture_output=True, text=True, cwd=str(ROOT))


def parse_tasks(tasks_path: Path):
    tasks = []
    if not tasks_path.exists():
        return tasks
    for line in tasks_path.read_text().splitlines():
        m = re.match(r"-\s*\[\s*\]\s*(.+)", line)
        if m:
            tasks.append(m.group(1).strip())
    return tasks


def load_state(state_path: Path):
    if state_path.exists():
        s = json.loads(state_path.read_text())
    else:
        s = {"completed": [], "failed": {}, "current": None}
    if isinstance(s.get("failed"), dict):
        migrated = {}
        for key, value in s.get("failed", {}).items():
            if isinstance(value, str):
                migrated[key] = {"reason": value[:4000], "attempts": 1}
            elif isinstance(value, dict):
                migrated[key] = {
                    "reason": str(value.get("reason", value))[:4000],
                    "attempts": int(value.get("attempts", 1)),
                }
        s["failed"] = migrated
    s.setdefault("usage", {"tokens": 0, "usd": 0.0, "gpu_minutes": 0.0, "attempts": 0})
    s.setdefault("started_at", datetime.datetime.now(datetime.timezone.utc).isoformat())
    s.setdefault("deferred", [])
    s.setdefault("release_phase", "internal-alpha")
    return s


def save_state(state_path: Path, state):
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(state_path)


def run_tests(cmd: str) -> Tuple:
    proc = run_cmd(cmd)
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-4000:]


def run_tests_rate(cmd: str, attempts: int = 1, threshold: float = 1.0):
    passes = 0
    last = ""
    for _ in range(max(1, attempts)):
        ok, out = run_tests(cmd)
        if ok:
            passes += 1
        last = out
    rate = passes / max(1, attempts)
    return rate >= threshold, last, passes, max(1, attempts)


def verify_no_stubs(repo: Path):
    src = repo / "src"
    if not src.exists():
        return
    for pat in ["todo!()", "unimplemented!()", "STUB", "PLACEHOLDER", "FIXME"]:
        proc = subprocess.run(["grep", "-rn", pat, str(src)], capture_output=True, text=True)
        if proc.returncode == 0 and proc.stdout.strip():
            raise RuntimeError(f"stub marker found: {pat}")


def within_budget(state, cfg):
    usage = state.setdefault("usage", {"tokens": 0, "usd": 0.0, "gpu_minutes": 0.0, "attempts": 0})
    if cfg.get("budget_tokens") is not None and usage["tokens"] >= cfg["budget_tokens"]:
        return False, "token budget exhausted"
    if cfg.get("budget_usd") is not None and usage["usd"] >= cfg["budget_usd"]:
        return False, "cost budget exhausted"
    if cfg.get("gpu_minutes") is not None and usage["gpu_minutes"] >= cfg["gpu_minutes"]:
        return False, "gpu budget exhausted"
    dl = cfg.get("deadline")
    if dl:
        deadline = datetime.datetime.fromisoformat(dl.replace("Z", "+00:00"))
        if datetime.datetime.now(datetime.timezone.utc) >= deadline:
            return False, "deadline reached"
    return True, "ok"


def scope_freeze(cfg, state):
    dl = cfg.get("deadline")
    if not dl:
        return False
    deadline = datetime.datetime.fromisoformat(dl.replace("Z", "+00:00"))
    started = cfg.get("started_at", deadline.isoformat())
    started_dt = datetime.datetime.fromisoformat(started.replace("Z", "+00:00"))
    total = (deadline - started_dt).total_seconds()
    if total <= 0:
        return True
    elapsed = (datetime.datetime.now(datetime.timezone.utc) - started_dt).total_seconds()
    if elapsed / total >= cfg.get("scope_freeze_at", 0.85):
        return True
    usage = state.get("usage", {})
    bt = cfg.get("budget_tokens")
    if bt and usage.get("tokens", 0) / bt >= cfg.get("scope_freeze_at", 0.85):
        return True
    return False


def critical_task(name):
    low = name.lower()
    if any(k in low for k in ["polish", "optional", "docs-only", "nice-to-have"]):
        return False
    return True


def estimate_cost(text, model, cfg):
    tokens = max(1, len(text) // 4)
    prices = cfg.get("cost_per_1k_tokens", {})
    usd = tokens / 1000.0 * prices.get(model, 0.0)
    return tokens, usd


def rotate_artifacts(cfg):
    evidence_dir = Path(cfg.get("evidence_dir", ".dark-factory-evidence"))
    if evidence_dir.exists():
        files = sorted(evidence_dir.glob("*"), key=lambda p: p.stat().st_mtime)
        max_files = int(cfg.get("max_evidence_files", 100))
        for p in files[:-max_files] if len(files) > max_files else []:
            try:
                p.unlink()
            except OSError:
                pass
    ledger_path = Path(cfg.get("ledger_file", ".dark-factory-ledger.jsonl"))
    if ledger_path.exists():
        lines = ledger_path.read_text().splitlines()
        max_lines = int(cfg.get("max_ledger_lines", 1000))
        if len(lines) > max_lines:
            ledger_path.write_text("\n".join(lines[-max_lines:]) + "\n")


def classify_failure(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ["timeout", "flaky", "random", "intermittent"]):
        return "flaky-test"
    if any(k in t for k in ["missing", "not found", "no such", "dependency", "crate"]):
        return "missing-dependency"
    if any(k in t for k in ["scope", "checkpoint", "changed contract", "destructive"]):
        return "scope-change"
    if any(k in t for k in ["drift", "stale", "mismatch"]):
        return "drift"
    return "implementation"


def load_task_graph(cfg):
    path = cfg.get("task_graph_file")
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except Exception:
        return None
    if isinstance(data, dict):
        data = data.get("tasks", [])
    return data if isinstance(data, list) else None


def is_viewer_task(title: str) -> bool:
    low = title.lower()
    return any(k in low for k in ["viewer", "display", "visual verify", "screenshot"])


def task_title(item):
    if isinstance(item, dict):
        return str(item.get("title") or item.get("name") or item.get("id"))
    return str(item)


def task_deps(item):
    if isinstance(item, dict):
        return list(item.get("depends_on", []))
    return []


def state_failed_entry(state, title):
    entry = state.get("failed", {}).get(title, {})
    if isinstance(entry, str):
        return {"reason": entry, "category": "unknown", "attempts": 1}
    if isinstance(entry, dict):
        entry.setdefault("attempts", 1)
        return entry
    return {"reason": str(entry), "category": "unknown", "attempts": 1}


def eligible_for_retry(state, title, max_retries):
    if title not in state.get("failed", {}):
        return True
    entry = state_failed_entry(state, title)
    return entry.get("attempts", 1) < max_retries


def task_kind(title: str) -> str:
    low = title.lower()
    if any(k in low for k in ("[code]", "implement", "add ", "fix ", "create ", "port ")):
        return "code"
    if any(k in low for k in ("[docs]", "document", "docs ", "docs page", "hand-write", "hand write")):
        return "docs"
    if any(k in low for k in ("[design]", "design ", "architecture", "docs page")):
        return "design"
    if any(k in low for k in ("[validate]", "validate", "verify", "check ")):
        return "validate"
    if any(k in low for k in ("[operator]", "approve", "decide ", "sign off")):
        return "operator"
    return "code"


def task_sources(cfg):
    sources = []
    if cfg.get("tasks_files"):
        sources.extend(Path(p) for p in cfg["tasks_files"])
    elif cfg.get("tasks_file"):
        sources.append(Path(cfg["tasks_file"]))
    for p in cfg.get("work_packages", []) or []:
        sources.append(Path(p))
    registry = Path(cfg.get("work_package_registry_file", ".dark-factory-work-packages.json"))
    if registry.exists():
        try:
            for p in json.loads(registry.read_text()):
                sources.append(Path(p))
        except Exception:
            pass
    seen = set()
    out = []
    for src in sources:
        key = str(src.resolve()) if src.exists() else str(src)
        if key in seen:
            continue
        seen.add(key)
        out.append(src)
    return out


def load_all_tasks(cfg):
    merged = []
    seen = set()
    for src in task_sources(cfg):
        for task in parse_tasks(src):
            if task in seen:
                continue
            seen.add(task)
            merged.append(task)
    return merged


def register_work_package(cfg, path):
    registry = Path(cfg.get("work_package_registry_file", ".dark-factory-work-packages.json"))
    current = []
    if registry.exists():
        try:
            current = json.loads(registry.read_text())
        except Exception:
            current = []
    resolved = str(Path(path).resolve())
    if resolved not in current:
        current.append(resolved)
        registry.write_text(json.dumps(current, indent=2))
    return registry


def watchdog_state(cfg, state, tasks):
    if state.get("paused"):
        return "paused"
    if not tasks and not state.get("completed") and not state.get("failed"):
        return "idle"
    failed = state.get("failed", {})
    retryable = [t for t in failed if (failed.get(t, {}) or {}).get("attempts", 1) < int(cfg.get("max_task_retries", 3))]
    if state.get("failed") and not retryable and not tasks:
        return "blocked"
    if tasks:
        return "running"
    return "queue_empty"


def dispatch(cfg, state, tasks, state_path):
    global ROOT
    global ROOT
    ok, reason = within_budget(state, cfg)
    if not ok:
        print("STOP:", reason)
        return False

    import os as _os
    max_failed_retries = int(cfg.get("max_task_retries", 3))
    normalized_failed = {}
    for task_name, meta in (state.get("failed") or {}).items():
        if isinstance(meta, str):
            meta = {"reason": meta, "category": classify_failure(meta), "attempts": 1}
        if isinstance(meta, dict):
            meta.setdefault("category", classify_failure(meta.get("reason", "")))
            meta.setdefault("attempts", 1)
        normalized_failed[task_name] = meta
    state["failed"] = normalized_failed

    if cfg.get("auto_clear_failed_on_blocked", False):
        _auto_clear_exhausted_failures(cfg, state, state_path)
    quarantined = set(state.get("auto_quarantined_failures", []))
    work = []
    if cfg.get("auto_clear_failed_on_blocked", False):
        _auto_clear_exhausted_failures(cfg, state, state_path)
    graph = load_task_graph(cfg)
    viewer_defer = not str(state.get("release_phase", "")).lower().startswith("candidate")
    work = []
    completed_set = set(state.get("completed", []))
    if graph is not None:
        for item in graph:
            title = task_title(item)
            if title in completed_set:
                continue
            if title in state.get("deferred", []):
                continue
            if is_viewer_task(title) and viewer_defer:
                continue
            entry = normalized_failed.get(title)
            if entry and entry.get("attempts", 1) >= max_failed_retries and title in state.get("failed", {}):
                continue
            deps = task_deps(item)
            if all(dep in completed_set for dep in deps):
                work.append(title)
    else:
        for t in tasks:
            if t in completed_set:
                continue
            if t in state.get("deferred", []):
                continue
            entry = normalized_failed.get(t)
            if entry and entry.get("attempts", 1) >= max_failed_retries:
                continue
            work.append(t)

    high_risk = [t for t in work if "[high]" in t.lower() or "security" in t.lower()]
    if high_risk and _os.environ.get("DARK_FACTORY_APPROVE_HIGH") != "1":
        print("high-risk tasks require DARK_FACTORY_APPROVE_HIGH=1; skipping")
        work = [t for t in work if t not in high_risk]

    if scope_freeze(cfg, state):
        work = [t for t in work if critical_task(t)]
        if not work:
            print("scope frozen: no critical tasks remaining")
            return False
    quarantined = set(state.get("auto_quarantined_failures", []))
    work = [t for t in work if t not in quarantined]
    if not work:
        blocked = False
        if state.get("failed"):
            retryable = [t for t in state.get("failed", {}) if (state.get("failed", {}).get(t, {}) or {}).get("attempts", 1) < int(cfg.get("max_task_retries", 3))]
            if not retryable:
                blocked = True
        if blocked:
            if cfg.get("auto_clear_failed", False) and _auto_clear_exhausted_failures(cfg, state, state_path):
                print("cleared exhausted task issues; continuing with the next pass")
                return True
            print("blocked: no runnable tasks with retry budget remaining")
            state["paused"] = True
            save_state(state_path, state)
            _triage(cfg, state_path)
        else:
            print("queue empty")
        return False

    task = work[0]
    kind = task_kind(task)

    if kind == "validate":
        cmd = cfg.get("runtime_test_command") or cfg.get("test_command")
        ok, out = run_tests(cmd)
        if not ok:
            raise TaskFailed("validation failed: " + out[-1000:])
        tasks_path = Path(cfg["tasks_file"])
        if tasks_path.exists():
            text = tasks_path.read_text()
            text = text.replace(f"- [ ] {task}", f"- [x] {task}", 1)
            tasks_path.write_text(text)
        state.setdefault("completed", []).append(task)
        save_state(state_path, state)
        print(f"validated: {task}")
        return True

    if kind in ("docs", "design", "operator"):
        state.setdefault("deferred", [])
        if task not in state["deferred"]:
            state["deferred"].append(task)
        save_state(state_path, state)
        print(f"deferred non-code task: {task}")
        return True

    task_failure_meta = normalized_failed.get(task)
    orig_root = ROOT
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", task)[:40]
    slug = f"{slug}-{int(time.time() * 1000)}"
    wt = orig_root / ".dark-factory" / "worktrees" / f"{slug}"
    branch = f"df-{slug}"
    # Stale branches/worktree metadata must not block a restarted task.
    subprocess.run(["git", "worktree", "prune"], cwd=str(orig_root), capture_output=True, text=True)
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
    subprocess.run(["git", "branch", "-D", branch], cwd=str(orig_root), capture_output=True, text=True)
    r = subprocess.run(["git", "worktree", "add", "-b", branch, str(wt), "HEAD"], cwd=str(orig_root), capture_output=True, text=True)
    if r.returncode != 0:
        print("worktree failed:", r.stderr or r.stdout)
        return False

    ROOT = wt
    success = False
    try:
        check_disk(cfg)
        from worker import run_ollama, parse_files, choose_model
        from review import independent_review

        prompt = (
            cfg.get("worker_brief_prefix", "You are a coding worker. Keep changes minimal.") + "\n\n"
            "GLOBAL CONSTRAINT:\nPreserve all existing public types, fields, and APIs unless the task explicitly says to remove them.\n\n"
            "TASK:\n" + task + "\n\n"
            + (("PRIOR FAILURE:\n" + str(task_failure_meta.get("reason", ""))[-2000:] +
               "\nFix that failure without reverting unrelated public APIs.\n\n") if task_failure_meta else "")
            + "Do not use markdown code fences. Output each changed file as:\n"
            "@@@FILE relative/path\n<file content>\n@@@END\n"
            "Use real newline characters, not escaped \\n text.\n"
        )
        model = cfg["model"]
        backup = cfg["backup_model"]
        changed = []
        attempt = 0
        while attempt < 2:
            used_model = choose_model(model, backup, attempt)
            ok, out = run_ollama(used_model, prompt, cfg.get("timeout", 600))
            if not ok:
                attempt += 1
                continue
            files = parse_files(out)
            tokens, usd = estimate_cost(prompt + out, used_model, cfg)
            u = state.setdefault("usage", {"tokens": 0, "usd": 0.0, "gpu_minutes": 0.0, "attempts": 0})
            u["tokens"] += tokens
            u["usd"] += usd
            u["attempts"] += 1
            if not files:
                attempt += 1
                continue
            for rel, content in files:
                rel = rel.strip()
                if not rel or rel.startswith("/") or ".." in Path(rel).parts:
                    raise TaskFailed(f"unsafe path from worker: {rel}")
                p = ROOT / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
                changed.append(rel)
            break
        else:
            raise TaskFailed("worker produced no usable output")

        verify_no_stubs(ROOT)

        attempts = int(cfg.get("test_attempts", 1))
        threshold = float(cfg.get("test_pass_rate", 1.0))
        ok, tail, passes, tried = run_tests_rate(cfg["test_command"], attempts, threshold)
        print(f"tests: {passes}/{tried}")
        if not ok:
            raise TaskFailed("tests failed: " + tail[-1000:])

        integration_cmd = cfg.get("integration_command")
        if integration_cmd:
            i_ok, i_out = run_tests(integration_cmd)
            if not i_ok:
                raise TaskFailed("integration gate: " + i_out[-1000:])

        runtime_cmd = cfg.get("runtime_test_command")
        if runtime_cmd:
            r_ok, r_out = run_tests(runtime_cmd)
            if not r_ok:
                raise TaskFailed("runtime gate: " + r_out[-1000:])

        qa_cmd = cfg.get("qa_command")
        if qa_cmd:
            q_ok, q_out = run_tests(qa_cmd)
            if not q_ok:
                raise TaskFailed("qa gate: " + q_out[-1000:])

        # dependency/supply-chain scan if dependency files changed
        dep_files = {"requirements.txt", "pyproject.toml", "Cargo.lock", "Cargo.toml",
                     "package-lock.json", "pnpm-lock.yaml", "go.mod", "go.sum"}
        if any(Path(c).name in dep_files for c in changed):
            scan_cmd = cfg.get("dependency_scan_command")
            if scan_cmd:
                sc_ok, sc_out = run_tests(scan_cmd)
                if not sc_ok:
                    raise TaskFailed("dependency scan: " + sc_out[-1000:])

        diff_proc = git("diff", "--no-color")
        diff_text = diff_proc.stdout or ""
        review_model = cfg.get("review_model", cfg.get("backup_model", cfg["model"]))
        ok_rev, review_out = independent_review(review_model, changed, diff_text, tail)
        if not ok_rev:
            raise TaskFailed("independent review: " + review_out[:1000])

        holdout_cmd = cfg.get("holdout_command")
        if holdout_cmd:
            okh, hout = run_tests(holdout_cmd)
            if not okh:
                raise TaskFailed("holdout: " + hout[-1000:])

        for eval_name in ("evaluate_functional_command", "evaluate_change_command"):
            eval_cmd = cfg.get(eval_name)
            if eval_cmd:
                try:
                    argv = shlex.split(eval_cmd)
                except ValueError:
                    argv = ["/bin/sh", "-c", eval_cmd]
                ep = subprocess.run(argv, capture_output=True, text=True, cwd=str(ROOT))
                if ep.returncode != 0:
                    raise TaskFailed(f"{eval_name}: " + (ep.stdout + ep.stderr)[-1000:])
        evidence_dir = Path(cfg.get("evidence_dir", ".dark-factory-evidence"))
        evidence_dir.mkdir(exist_ok=True)
        config_hash = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:12]
        slug_e = re.sub(r"[^a-zA-Z0-9_-]", "_", task)[:60]
        (evidence_dir / f"{slug_e}-{int(time.time())}.md").write_text(
            f"# Evidence pack: {task}\n\n"
            f"changed_files: {changed}\n"
            f"config_hash: {config_hash}\n"
            f"model: {cfg['model']}\n"
            f"review_model: {review_model}\n"
            f"test_command: {cfg['test_command']}\n"
            f"test_passes: {passes}/{tried}\n\n"
            f"## Diff\n{diff_text}\n\n"
            f"## Test output\n{tail}\n\n"
            f"## Independent review\n{review_out}\n"
        )

        for _c in changed:
            git("add", _c)
        git("commit", "-m", f"dark-factory: {task}")

        tasks_path = Path(cfg.get("tasks_file"))
        task_hash = hashlib.sha256(tasks_path.read_bytes()).hexdigest()[:16] if tasks_path.exists() else None
        ledger_path = Path(cfg.get("ledger_file", ".dark-factory-ledger.jsonl"))
        with open(ledger_path, "a") as lf:
            import json as _j
            lf.write(_j.dumps({"task": task, "status": "completed", "changed": changed,
                               "time": time.time(), "model": cfg["model"],
                               "release_phase": state.get("release_phase", "internal-alpha"),
                               "config_hash": config_hash,
                               "tasks_file_hash": task_hash,
                               "test_command": cfg["test_command"],
                               "test_passes": f"{passes}/{tried}",
                               "passes": {"tests": True, "integration": bool(cfg.get("integration_command")), "runtime": bool(cfg.get("runtime_test_command")), "review": True, "holdout": bool(cfg.get("holdout_command"))},
                               "tokens": state.get("usage", {}).get("tokens"),
                               "usd": state.get("usage", {}).get("usd")}) + "\n")

        tasks_path = Path(cfg["tasks_file"])
        if tasks_path.exists():
            text = tasks_path.read_text()
            text = text.replace(f"- [ ] {task}", f"- [x] {task}", 1)
            tasks_path.write_text(text)

        # merge branch back to original branch
        merge_proc = subprocess.run(["git", "merge", "--no-edit", "--ff-only", branch], cwd=str(orig_root), capture_output=True, text=True)
        if merge_proc.returncode != 0:
            raise TaskFailed("merge failed: " + (merge_proc.stderr or merge_proc.stdout)[-1000:])

        success = True

        # cleanup worktree/branch
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=str(orig_root), capture_output=True, text=True)
        subprocess.run(["git", "branch", "-D", branch], cwd=str(orig_root), capture_output=True, text=True)
        ROOT = orig_root

        rotate_artifacts(cfg)
        state["failed"].pop(task, None)
        state["completed"].append(task)
        state["current"] = None
        save_state(state_path, state)
        print(f"completed: {task}")
        return True

    except TaskFailed as e:
        print("TASK FAILED:", e)
        for _c in changed:
            try:
                git("checkout", "--", _c)
                (ROOT / _c).unlink(missing_ok=True)
            except Exception:
                pass
        meta = state["failed"].get(task, {})
        attempts = (meta.get("attempts", 1) if isinstance(meta, dict) else 1) + 1
        state["failed"][task] = {"reason": str(e)[:4000], "category": classify_failure(str(e)), "attempts": attempts}
        save_state(state_path, state)
        success = False
        return True
    except Exception as e:
        print("ERROR:", e)
        success = False
        meta = state["failed"].get(task, {})
        attempts = (meta.get("attempts", 1) if isinstance(meta, dict) else 1) + 1
        state["failed"][task] = {"reason": f"exception: {e}"[:4000], "category": classify_failure(str(e)), "attempts": attempts}
        try:
            save_state(state_path, state)
        except Exception:
            pass
        return False
    finally:
        if not success:
            subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=str(orig_root), capture_output=True, text=True)
            subprocess.run(["git", "branch", "-D", branch], cwd=str(orig_root), capture_output=True, text=True)
        ROOT = orig_root


def _heal_task(cfg, state_path, task):
    from worker import run_ollama, parse_files, choose_model
    from review import independent_review
    state = load_state(state_path)
    failure_tail = state.get("failed", {}).get(task, "unknown failure")
    attempts = int(cfg.get("heal_max_attempts", 3))
    brief = cfg.get("worker_brief_prefix", "You are a coding worker. Keep changes minimal.")
    model = cfg["model"]
    backup = cfg["backup_model"]
    for i in range(attempts):
        print(f"heal attempt {i + 1}/{attempts}")
        prompt = (
            brief + "\n"
            "Fix the failing task without weakening, skipping, or deleting tests.\n"
            "TASK:\n" + task + "\n\n"
            "Failure output:\n" + str(failure_tail)[-4000:] + "\n\n"
            "Output changed files as:\n@@@FILE relative/path\n<content>\n@@@END\n"
        )
        ok, out = run_ollama(choose_model(model, backup, i), prompt, cfg.get("timeout", 600))
        if not ok:
            continue
        files = parse_files(out)
        if not files:
            continue
        changed = []
        try:
            for rel, content in files:
                rel = rel.strip()
                if not rel or rel.startswith("/") or ".." in Path(rel).parts:
                    raise TaskFailed(f"unsafe path: {rel}")
                p = ROOT / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
                changed.append(rel)
        except Exception as exc:
            print("apply failed:", exc)
            continue

        ok, tail, passes, tried = run_tests_rate(cfg["test_command"], int(cfg.get("test_attempts", 1)), float(cfg.get("test_pass_rate", 1.0)))
        if not ok:
            print("tests still failing:", tail[-1000:])
            for _c in changed:
                tracked = subprocess.run(["git", "ls-files", "--error-unmatch", _c], cwd=str(ROOT), capture_output=True, text=True).returncode == 0
                git("checkout", "--", _c)
                if not tracked:
                    try:
                        (ROOT / _c).unlink(missing_ok=True)
                    except Exception:
                        pass
            failure_tail = tail
            _append_lesson(cfg, task, "test failure persists")
            continue

        diff_text = git("diff", "--no-color").stdout or ""
        ok_rev, review_out = independent_review(cfg.get("review_model", backup), changed, diff_text, tail)
        if not ok_rev:
            print("independent review failed:", review_out[:500])
            for _c in changed:
                tracked = subprocess.run(["git", "ls-files", "--error-unmatch", _c], cwd=str(ROOT), capture_output=True, text=True).returncode == 0
                git("checkout", "--", _c)
                if not tracked:
                    try:
                        (ROOT / _c).unlink(missing_ok=True)
                    except Exception:
                        pass
            failure_tail = review_out
            _append_lesson(cfg, task, "independent review failed")
            continue

        for _c in changed:
            git("add", _c)
        git("commit", "-m", f"dark-factory heal: {task}")
        state["failed"].pop(task, None)
        state.setdefault("completed", []).append(task)
        save_state(state_path, state)
        _append_lesson(cfg, task, "healed successfully")
        print("healed:", task)
        return

    state["failed"][task] = str(failure_tail)[:2000]
    save_state(state_path, state)
    _append_lesson(cfg, task, "heal exhausted")
    print("heal exhausted; task remains failed")


def _auto_clear_exhausted_failures(cfg, state, state_path):
    failed = state.get("failed", {}) or {}
    max_retries = int(cfg.get("max_task_retries", 3))
    retryable = [t for t in failed if ((failed.get(t, {}) or {}).get("attempts", 1) < max_retries)]
    if not failed or retryable:
        return False
    cleared = [t for t in failed if t not in state.get("auto_quarantined_failures", [])]
    state.setdefault("auto_quarantined_failures", []).extend(cleared)
    state["failed"] = {}
    save_state(state_path, state)
    print("auto-cleared blocked tasks:", ", ".join(cleared))
    return True

def _append_lesson(cfg, task, note):
    path = Path(cfg.get("lessons_file", ".dark-factory-lessons.md"))
    with open(path, "a") as f:
        f.write(f"- {datetime.datetime.now().isoformat()} | {task} | {note}\\n")


def _propose_improvement(cfg, state_path):
    state = load_state(state_path)
    lessons_path = Path(cfg.get("lessons_file", ".dark-factory-lessons.md"))
    lessons = lessons_path.read_text() if lessons_path.exists() else "(no lessons recorded)"
    failed = state.get("failed", {})
    usage = state.get("usage", {})
    out_dir = Path(cfg.get("improvement_proposal_dir", ".dark-factory-improvements"))
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"improvement-proposal-{stamp}.md"
    lines = [
        f"# Dark Factory Improvement Proposal ({stamp})",
        "",
        "## Summary",
        f"- completed: {len(state.get('completed', []))}",
        f"- failed: {len(failed)}",
        f"- usage: {usage}",
        "",
        "## Failed tasks",
    ]
    for k, v in failed.items():
        lines.append(f"- {k}: {str(v)[:300]}")
    lines += ["", "## Lessons", lessons, "", "## Proposed (human-reviewed) changes", "- Review recurring failures before editing controller.py.", "- Prefer config/prompt changes over code changes.", "- Add any new permanent guardrails only after review."]
    path.write_text("\n".join(lines) + "\n")
    print(f"proposal written: {path}")


def _triage(cfg, state_path):
    state = load_state(state_path)
    failed = state.get("failed", {})
    lines = ["# Dark Factory Triage", "", "## Blocked failures"]
    for task, meta in failed.items():
        if isinstance(meta, str):
            meta = {"reason": meta, "category": classify_failure(meta), "attempts": 1}
        cat = meta.get("category", "unknown")
        attempts = meta.get("attempts", 1)
        reason = meta.get("reason", "")
        suggestion = {
            "implementation": "reword task with crate path and integration target; include relevant source files",
            "missing-dependency": "create dependency/setup task first; verify library conflict",
            "drift": "reconcile changed assumptions/specs before implementation",
            "flaky-test": "stabilize test or rerun baseline; do not weaken it",
            "scope-change": "create explicit change request and approval",
        }.get(cat, "diagnose manually")
        lines.append(f"- {task}")
        lines.append(f"  - category: {cat}")
        lines.append(f"  - attempts: {attempts}")
        lines.append(f"  - suggestion: {suggestion}")
        lines.append(f"  - reason: {str(reason)[:500]}")
    out = Path(cfg.get("triage_file", ".dark-factory-triage.md"))
    out.write_text("\n".join(lines) + "\n")
    print(f"triage written: {out}")


def _reassess(cfg, state_path):
    state = load_state(state_path)
    model = cfg.get("analysis_model", cfg.get("model", "beam:cloud"))
    tasks_path = Path(cfg.get("tasks_file"))
    criteria_path = cfg.get("success_criteria_file")
    criteria_text = ""
    if criteria_path and Path(criteria_path).exists():
        criteria_text = Path(criteria_path).read_text()[:12000]
    packet = {
        "completed": state.get("completed", []),
        "failed": state.get("failed", {}),
        "remaining": parse_tasks(tasks_path) if tasks_path.exists() else [],
        "release_phase": state.get("release_phase", "internal-alpha"),
        "usage": state.get("usage", {}),
        "success_criteria": criteria_text,
    }
    prompt = (
        "You are a release planner. Compare completed work against success criteria. "
        "Return markdown with sections: Covered Criteria, Open Criteria, Gaps, Suggested Follow-up Tasks (only explicit gap-closure; no horizontal churn), and Scope Risk. "
        "Use only evidence provided. Do not invent gaps without criterion mapping.\n\n"
        "Packet:\n" + json.dumps(packet, indent=2, default=str)[:18000]
    )
    proc = subprocess.run(
        ["ollama", "run", model, prompt, "--think=false", "--hidethinking"],
        capture_output=True, text=True, timeout=int(cfg.get("timeout", 600)),
    )
    output = (proc.stdout or "").strip()
    out_dir = Path(cfg.get("reassessment_dir", ".dark-factory-reassessments"))
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"reassessment-{stamp}.md"
    path.write_text(f"# Milestone Reassessment ({stamp})\n\nModel: {model}\n\n{output}\n")
    print(f"reassessment written: {path}")


def _run_until_done(cfg, state_path, tasks_path):
    max_iterations = int(cfg.get("until_done_max_iterations", 100))
    for i in range(max_iterations):
        state = load_state(state_path)
        if state.get("paused"):
            print("paused; stopping unattended loop")
            return
        tasks = load_all_tasks(cfg)
        health = watchdog_state(cfg, state, tasks)
        if health in ("blocked", "idle", "queue_empty"):
            print(f"stopping: {health}")
            if health == "blocked":
                _triage(cfg, state_path)
            return
        try:
            progressed = dispatch(cfg, state, tasks, state_path)
        except Exception as e:
            print("ERROR:", e)
            progressed = False
        if progressed:
            _maybe_heal_failed(cfg, state_path)
        state2 = load_state(state_path)
        if state2.get("paused"):
            print("paused after dispatch; stopping")
            return
        time.sleep(int(cfg.get("until_done_sleep_seconds", 2)))


def _maybe_heal_failed(cfg, state_path):
    state = load_state(state_path)
    failed = state.get("failed", {})
    if not failed:
        return
    title = next(iter(failed))
    entry = state_failed_entry(state, title)
    if entry.get("attempts", 1) < int(cfg.get("max_task_retries", 3)):
        _heal_task(cfg, state_path, title)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--rollback-last", action="store_true")
    ap.add_argument("--pause", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--heal", nargs="?", const="__auto__")
    ap.add_argument("--propose-improvement", action="store_true")
    ap.add_argument("--triage", action="store_true")
    ap.add_argument("--reassess", action="store_true")
    ap.add_argument("--clear-failed", action="store_true")
    ap.add_argument("--register-work-package", metavar="PATH")
    ap.add_argument("--watchdog", action="store_true")
    ap.add_argument("--checkpoint-dirty", action="store_true")
    ap.add_argument("--until-done", action="store_true")
    args = ap.parse_args()
    if args.rollback_last:
        print(git("revert", "--no-edit", "HEAD").stderr or "rolled back last commit")
        return
    if args.checkpoint_dirty:
        st = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=str(ROOT))
        if st.stdout.strip():
            subprocess.run(["git", "add", "-A"], cwd=str(ROOT), check=True)
            cp = subprocess.run(["git", "commit", "-m", f"wip: auto checkpoint {datetime.datetime.now().isoformat()}"], cwd=str(ROOT), capture_output=True, text=True)
            print(cp.stdout or cp.stderr)
            if cp.returncode != 0:
                raise SystemExit(f"checkpoint failed: {cp.stderr}")
        else:
            print("working tree already clean")
        return
    cfg_path = Path(args.config)
    cfg = load_config(cfg_path)
    state_path = Path(cfg.get("state_file", ".dark-factory-state.json"))
    tasks_path = Path(cfg["tasks_file"])
    if cfg.get("auto_checkpoint_dirty", False):
        st = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=str(ROOT))
        if st.stdout.strip():
            subprocess.run(["git", "add", "-A"], cwd=str(ROOT), check=True)
            cp = subprocess.run(["git", "commit", "-m", f"wip: auto checkpoint {datetime.datetime.now().isoformat()}"], cwd=str(ROOT), capture_output=True, text=True)
            print("auto checkpoint:", (cp.stdout or cp.stderr).strip())
            if cp.returncode != 0:
                raise SystemExit(cp.stderr)
    if args.register_work_package:
        reg = register_work_package(cfg, args.register_work_package)
        print("registered work package; registry:", reg)
        return
    if args.watchdog:
        st = load_state(state_path)
        tasks = load_all_tasks(cfg)
        health = watchdog_state(cfg, st, tasks)
        print(json.dumps({"health": health, "completed": len(st.get("completed", [])),
                          "failed": len(st.get("failed", {})), "deferred": len(st.get("deferred", [])),
                          "remaining": len(tasks) - len(st.get("completed", []))}, indent=2))
        sys.exit(0 if health in ("running", "queue_empty", "idle") else 1)
    if args.pause:
        st = load_state(state_path)
        st["paused"] = True
        save_state(state_path, st)
        print("paused")
        return
    if args.resume:
        st = load_state(state_path)
        st["paused"] = False
        save_state(state_path, st)
        print("resumed")
        if not args.once:
            return
    if args.heal:
        target = args.heal
        if target == "__auto__":
            st = load_state(state_path)
            failed = st.get("failed", {})
            target = next(iter(failed), None)
        if not target:
            print("no failed task found to heal")
            return
        _heal_task(cfg, state_path, target)
        return
    if args.checkpoint_dirty:
        st = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=str(ROOT))
        if st.stdout.strip():
            subprocess.run(["git", "add", "-A"], cwd=str(ROOT), check=True)
            cp = subprocess.run(["git", "commit", "-m", f"wip: auto checkpoint {datetime.datetime.now().isoformat()}"], cwd=str(ROOT), capture_output=True, text=True)
            print(cp.stdout or cp.stderr)
            if cp.returncode != 0:
                raise SystemExit(f"checkpoint failed: {cp.stderr}")
        else:
            print("working tree already clean")
        return
    if args.until_done:
        _run_until_done(cfg, state_path, tasks_path)
        return
    if args.propose_improvement:
        _propose_improvement(cfg, state_path)
        return
    if args.triage:
        _triage(cfg, state_path)
        return
    if args.reassess:
        _reassess(cfg, state_path)
        return
    if args.clear_failed:
        _auto_clear_exhausted_failures(cfg, load_state(state_path), state_path)
        return
    if not cfg.get("started_at"):
        cfg["started_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    interval = cfg.get("interval_seconds", 300)
    lock_path = Path(cfg.get("lock_file", ".dark-factory.lock"))
    if lock_path.exists():
        try:
            pid = int(lock_path.read_text().strip())
            os.kill(pid, 0)
            print(f"controller already running (pid {pid})")
            return
        except (ValueError, OSError, ProcessLookupError):
            pass
    lock_path.write_text(str(os.getpid()))
    try:
        while True:
            state = load_state(state_path)
            if state.get("paused"):
                Path(cfg.get("heartbeat_file", ".dark-factory-heartbeat.json")).write_text(
                    json.dumps({"time": time.time(), "status": "paused", "completed": len(state.get("completed", []))}, indent=2))
                if args.once:
                    break
                time.sleep(interval)
                continue
            tasks = load_all_tasks(cfg)
            try:
                progressed = dispatch(cfg, state, tasks, state_path)
            except Exception as e:
                print("ERROR:", e)
                progressed = False
            retryable = [t for t in state.get("failed", {}) if (state.get("failed", {}).get(t, {}) or {}).get("attempts", 1) < int(cfg.get("max_task_retries", 3))]
            Path(cfg.get("heartbeat_file", ".dark-factory-heartbeat.json")).write_text(
                json.dumps({"time": time.time(), "release_phase": state.get("release_phase", "internal-alpha"),
                            "completed": len(state.get("completed", [])),
                            "failed": len(state.get("failed", {})),
                            "retryable_failed": len(retryable),
                            "remaining": len(tasks) - len(state.get("completed", [])),
                            "usage": state.get("usage", {})}, indent=2))
            if args.once:
                break
            time.sleep(interval)
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
