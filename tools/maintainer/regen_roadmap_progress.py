#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Refresh docs/appendix-d-roadmap.md from openspec/: the Progress column of
each active-change row, rows for changes that are no longer active, and the
totals line. usage: regen_roadmap_progress.py WORKTREE"""
import os, re, sys
root = sys.argv[1]
ch = os.path.join(root, 'openspec/changes')
active = {d for d in os.listdir(ch) if d != 'archive' and os.path.isdir(os.path.join(ch, d))}
def progress(name):
    s = open(os.path.join(ch, name, 'tasks.md')).read()
    done = len(re.findall(r'^\s*- \[x\]', s, re.M | re.I)); todo = len(re.findall(r'^\s*- \[ \]', s, re.M))
    total = done + todo
    return f"{done}/{total} ({round(100*done/total) if total else 0}%)"
p = os.path.join(root, 'docs/appendix-d-roadmap.md'); L = open(p).read().split('\n')
out = []; seen = set(); in_active = False
for line in L:
    if line.startswith('## '):
        in_active = line.strip() == '## Active changes'
    m = re.match(r'^\| ([a-z0-9-]+) \| (\d+/\d+ \(\d+%\)) \| (.*)$', line) if in_active else None
    if m:
        name = m.group(1)
        if name not in active:
            print('drop row', name); continue
        seen.add(name); new = progress(name)
        if new != m.group(2): print(f'{name}: {m.group(2)} -> {new}')
        line = f'| {name} | {new} | {m.group(3)}'
    out.append(line)
missing = active - seen
if missing: print('ACTIVE BUT NOT LISTED:', sorted(missing))
s = '\n'.join(out)
n_arch = len(os.listdir(os.path.join(ch, 'archive'))); n_specs = len(os.listdir(os.path.join(root, 'openspec/specs')))
s, k = re.subn(r'The roadmap contains \d+ active changes, \d+ archived changes and \d+ capability specs\.',
               f'The roadmap contains {len(active)} active changes, {n_arch} archived changes and {n_specs} capability specs.', s)
assert k == 1, 'totals line not found'
open(p, 'w').write(s)
print(len(active), 'active;', n_arch, 'archived;', n_specs, 'specs')
