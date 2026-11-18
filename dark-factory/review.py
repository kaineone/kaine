#!/usr/bin/env python3
"""Context-separated independent verification for dark-factory."""
import subprocess, json
from pathlib import Path


def independent_review(model, changed_files, diff, test_output):
    prompt = (
        "You are an independent reviewer. Decide whether the change is safe to merge. "
        "Respond with PASS or FAIL on the first line, then reasons.\n\n"
        "Changed files:\n" + "\n".join(changed_files) + "\n\n"
        "Diff:\n" + diff[:12000] + "\n\n"
        "Test output (tail):\n" + test_output[-4000:] + "\n"
    )
    proc = subprocess.run(
        ["ollama", "run", model, prompt, "--think=false", "--hidethinking"],
        capture_output=True, text=True, timeout=300,
    )
    out = (proc.stdout or "").strip()
    first = out.splitlines()[0].strip().upper() if out.splitlines() else "FAIL"
    return first.startswith("PASS"), out