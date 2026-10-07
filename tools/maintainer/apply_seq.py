# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Apply @@@EDIT blocks in order to the evolving file text (docs only).
Each SEARCH must match exactly once at the time it is applied; failures are
reported and skipped. Usage: apply_seq.py RESPONSE REPO --allow PATH..."""
import re, sys, pathlib
resp, repo = sys.argv[1], pathlib.Path(sys.argv[2])
allow = set(sys.argv[sys.argv.index('--allow')+1:]) if '--allow' in sys.argv else None
text = open(resp).read()
blocks = re.findall(r'^@@@EDIT[ \t]+(\S+)[ \t]*\n(.*?)^@@@END[ \t]*$', text, re.S | re.M)
ok = fail = 0
for i, (path, body) in enumerate(blocks, 1):
    m = re.match(r'<<<<<<< SEARCH\n(.*?)\n?=======\n(.*?)\n?>>>>>>> REPLACE\s*$', body, re.S)
    if not m or (allow is not None and path not in allow):
        print(f"edit {i}: {path}: malformed or not allowed"); fail += 1; continue
    search, repl = m.group(1), m.group(2)
    search = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', search); repl = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', repl)
    p = repo / path; src = p.read_text()
    n = src.count(search)
    if n != 1:
        print(f"edit {i}: {path}: SEARCH matched {n} times: {search[:120]!r}"); fail += 1; continue
    p.write_text(src.replace(search, repl, 1)); ok += 1
print(f"applied {ok}, failed {fail}")
