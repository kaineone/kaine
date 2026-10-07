#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Headless Kimi worker harness (Ollama HTTP API).

usage: worker.py BRIEF OUT_DIR --allow PATH... [--apply REPO] [--think high] [--reapply]

Sends BRIEF to --model (default kimi-k2.7-code:cloud, through the local Ollama
endpoint), saves response.txt / thinking.txt in OUT_DIR,
parses complete-file blocks

@@@FILE relative/path
<full file body>
@@@END

strips control characters and a wrapping markdown fence, and (with --apply) writes
ONLY the allow-listed paths into REPO. Fails loudly on empty responses, unknown
paths or zero blocks.
"""
import pathlib
import argparse
import json
import os
import re
import sys
import urllib.request

MODEL = os.environ.get("WORKER_MODEL", "kimi-k2.7-code:cloud")
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|\x1b\[[0-9;?]*[A-Za-z]")
BLOCK = re.compile(r"^@@@FILE[ \t]+(\S+)[ \t]*\n(.*?)^@@@END[ \t]*$", re.S | re.M)


def _unfence(content: str) -> str:
    lines = content.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) >= 2 and re.match(r"^```[\w+-]*\s*$", lines[0]) and lines[-1].strip() == "```":
        lines = lines[1:-1]
    return "\n".join(lines) + "\n"



def inside(repo, rel: str):
    """``repo/rel`` if ``rel`` is a plain relative path that stays inside ``repo``."""
    from pathlib import Path as _P
    p = _P(rel)
    if p.is_absolute() or ".." in p.parts:
        raise SystemExit(f"refusing path outside the checkout: {rel}")
    root = _P(repo).resolve()
    dest = (root / p).resolve()
    if root != dest and root not in dest.parents:
        raise SystemExit(f"refusing path outside the checkout: {rel}")
    return dest

def _finish(resp: str, a) -> int:
    if a.text:
        # A plain-text answer (a review): there are no file blocks to check.
        return 0
    blocks = [(p, _unfence(c)) for p, c in BLOCK.findall(resp)]
    if not blocks:
        print("NO @@@FILE BLOCKS in response", file=sys.stderr)
        return 3
    bad = [p for p, _ in blocks if p not in a.allow]
    for p, content in blocks:
        flag = "  <-- NOT ALLOWED" if p in bad else ""
        print(f"  block: {p} ({len(content.splitlines())} lines){flag}")
    if bad:
        return 4
    if a.apply:
        for p, content in blocks:
            dest = str(inside(a.apply, p))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w") as fh:
                fh.write(content)
        print(f"applied {len(blocks)} file(s) to {a.apply}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("brief")
    ap.add_argument("out")
    ap.add_argument("--allow", nargs="*", default=[])
    ap.add_argument("--apply")
    ap.add_argument("--think", default="high")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--ctx", type=int, default=int(os.environ.get("WORKER_CTX", "131072")))
    ap.add_argument("--num-predict", type=int, default=65536)
    ap.add_argument("--reapply", action="store_true")
    ap.add_argument("--text", action="store_true", help="the answer is plain text, not file blocks")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.reapply:
        return _finish(pathlib.Path(os.path.join(a.out, "response.txt")).read_text(), a)
    prompt = pathlib.Path(a.brief).read_text()
    body = {"model": a.model, "prompt": prompt, "stream": False, "think": a.think,
            "options": {"num_predict": a.num_predict, "num_ctx": a.ctx}}
    req = urllib.request.Request("http://localhost:11434/api/generate",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        res = json.load(r)
    resp = CTRL.sub("", res.get("response", ""))
    with open(os.path.join(a.out, "response.txt"), "w") as fh:
        fh.write(resp)
    with open(os.path.join(a.out, "thinking.txt"), "w") as fh:
        fh.write(res.get("thinking", "") or "")
    stats = {k: res.get(k) for k in ("total_duration", "load_duration", "prompt_eval_count",
                                      "prompt_eval_duration", "eval_count", "eval_duration", "done_reason")}
    stats["model"] = a.model
    with open(os.path.join(a.out, "stats.json"), "w") as fh:
        json.dump(stats, fh)
    print(f"model={a.model} response {len(resp)} chars, thinking {len(res.get('thinking') or '')} chars, "
          f"done_reason={res.get('done_reason')}, eval_count={res.get('eval_count')}")
    if len(resp.strip()) < 10:
        print("EMPTY RESPONSE — read thinking.txt: likely a defective brief", file=sys.stderr)
        return 2
    return _finish(resp, a)


if __name__ == "__main__":
    sys.exit(main())
