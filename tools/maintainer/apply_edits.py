#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Apply anchored `@@@EDIT path` SEARCH/REPLACE blocks from a worker response.

@@@EDIT relative/path
<<<<<<< SEARCH
exact existing text (must occur exactly once in the file)
=======
replacement text
>>>>>>> REPLACE
@@@END

Edits apply in order; each SEARCH must match exactly once in the file as it is
at that moment. Any miss or ambiguity aborts before anything is written.
usage: apply_edits.py RESPONSE REPO --allow PATH...
"""
import argparse
import re
import sys
from pathlib import Path

BLOCK = re.compile(r"^@@@EDIT[ \t]+(\S+)[ \t]*\n(.*?)^@@@END[ \t]*$", re.S | re.M)
PAIR = re.compile(r"^<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n?>>>>>>> REPLACE[ \t]*$", re.S | re.M)



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

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("response")
    ap.add_argument("repo")
    ap.add_argument("--allow", nargs="*", default=[])
    ap.add_argument(
        "--loose-blank-lines",
        action="store_true",
        help="on a miss, retry allowing blank lines between SEARCH lines (unique match only)",
    )
    a = ap.parse_args()
    resp = Path(a.response).read_text()
    edits = [(path, se, re_) for path, body in BLOCK.findall(resp) for se, re_ in PAIR.findall(body)]
    if not edits:
        print("NO @@@EDIT BLOCKS", file=sys.stderr)
        return 3
    staged: dict[str, str] = {}
    for i, (path, search, replace) in enumerate(edits, 1):
        if path not in a.allow:
            print(f"edit {i}: {path} NOT ALLOWED", file=sys.stderr)
            return 4
        text = staged.get(path)
        if text is None:
            text = inside(a.repo, path).read_text()
        n = text.count(search)
        if n == 0 and a.loose_blank_lines:
            # Workers often drop blank lines from anchors (import groups).
            lines = [ln for ln in search.split("\n") if ln.strip()]
            pattern = r"\n(?:[ \t]*\n)*".join(re.escape(ln) for ln in lines)
            found = [m.group(0) for m in re.finditer(pattern, text)]
            if len(found) == 1:
                print(f"  edit {i}: {path}: loose blank-line match", file=sys.stderr)
                search, n = found[0], 1
        if n != 1:
            print(f"edit {i}: {path}: SEARCH matched {n} times:\n{search[:300]}", file=sys.stderr)
            return 5
        staged[path] = text.replace(search, replace, 1)
        print(f"  edit {i}: {path} ok")
    # Compile every staged file before writing any, so a failure writes nothing.
    for path, text in staged.items():
        if path.endswith(".py"):
            try:
                compile(text, path, "exec")
            except SyntaxError as exc:
                print(f"{path}: does not compile after edits: {exc}", file=sys.stderr)
                return 6
    for path, text in staged.items():
        inside(a.repo, path).write_text(text)
    print(f"applied {len(edits)} edit(s) to {len(staged)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
