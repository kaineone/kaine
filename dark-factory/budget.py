#!/usr/bin/env python3
"""Budget, deadline, and scope protections for dark-factory."""
import datetime, json
from pathlib import Path


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def parse_deadline(v):
    if not v:
        return None
    return datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))


def within_budget(state, cfg):
    """Return (ok, reason). Hard-stop if any cap exceeded."""
    usage = state.setdefault("usage", {"tokens": 0, "usd": 0.0, "gpu_minutes": 0.0, "attempts": 0})
    if cfg.get("budget_tokens") is not None and usage["tokens"] >= cfg["budget_tokens"]:
        return False, "token budget exhausted"
    if cfg.get("budget_usd") is not None and usage["usd"] >= cfg["budget_usd"]:
        return False, "cost budget exhausted"
    if cfg.get("gpu_minutes") is not None and usage["gpu_minutes"] >= cfg["gpu_minutes"]:
        return False, "gpu budget exhausted"
    dl = parse_deadline(cfg.get("deadline"))
    if dl and now() >= dl:
        return False, "deadline reached"
    return True, "ok"


def scope_freeze(cfg, state):
    """True when behind schedule/budget: only critical work may proceed."""
    dl = parse_deadline(cfg.get("deadline"))
    if not dl:
        return False
    total = (dl - parse_deadline(cfg.get("started_at", dl.isoformat()))).total_seconds()
    if total <= 0:
        return True
    elapsed = (now() - parse_deadline(cfg.get("started_at", dl.isoformat()))).total_seconds()
    if elapsed / total >= cfg.get("scope_freeze_at", 0.85):
        return True
    usage = state.get("usage", {})
    if cfg.get("budget_tokens") and usage.get("tokens", 0) / cfg["budget_tokens"] >= cfg.get("scope_freeze_at", 0.85):
        return True
    return False


def critical_task(name):
    low = name.lower()
    if any(k in low for k in ["polish", "optional", "docs-only", "nice-to-have"]):
        return False
    if any(k in low for k in ["core", "integration", "critical", "wire", "verify"]):
        return True
    return True


def estimate_cost(text, model, cfg):
    # crude: 1 token ~= 4 chars
    tokens = max(1, len(text) // 4)
    usd = 0.0
    prices = cfg.get("cost_per_1k_tokens", {})
    if model in prices:
        usd = tokens / 1000.0 * prices[model]
    return tokens, usd
PYEOF
