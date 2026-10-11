#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Apply @@@EDIT blocks in order to the evolving file text (docs only).
Each SEARCH must match exactly once at the time it is applied; failures are
reported and skipped. Usage: apply_seq.py RESPONSE REPO --allow PATH..."""
import re, sys, pathlib
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


resp, repo = sys.argv[1], pathlib.Path(sys.argv[2])
if '--allow' not in sys.argv:
    sys.exit("usage: apply_seq.py RESPONSE REPO --allow PATH...")
allow = set(sys.argv[sys.argv.index('--allow')+1:])
text = pathlib.Path(resp).read_text()
blocks = re.findall(r'^@@@EDIT[ \t]+(\S+)[ \t]*\n(.*?)^@@@END[ \t]*$', text, re.S | re.M)
ok = fail = 0
for i, (path, body) in enumerate(blocks, 1):
    m = re.match(r'<<<<<<< SEARCH\n(.*?)\n?=======\n(.*?)\n?>>>>>>> REPLACE\s*$', body, re.S)
    if not m or path not in allow:
        print(f"edit {i}: {path}: malformed or not allowed"); fail += 1; continue
    search, repl = m.group(1), m.group(2)
    search = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', search); repl = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', repl)
    p = inside(repo, path); src = p.read_text()
    n = src.count(search)
    if n != 1:
        print(f"edit {i}: {path}: SEARCH matched {n} times: {search[:120]!r}"); fail += 1; continue
    p.write_text(src.replace(search, repl, 1)); ok += 1
print(f"applied {ok}, failed {fail}")
