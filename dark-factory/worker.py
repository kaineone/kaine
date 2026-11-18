#!/usr/bin/env python3
"""Ollama cloud worker dispatcher for dark-factory."""
import subprocess, time
from typing import List, Optional, Tuple


def run_ollama(model: str, prompt: str, timeout: int = 600, think: str = "false") -> Tuple[bool, str]:
    """Run ollama non-interactively. Returns (ok, stdout). Retries empty responses."""
    cmd = ["ollama", "run", model, prompt, f"--think={think}", "--hidethinking"]
    for attempt in range(3):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, "TIMEOUT"
        out = (proc.stdout or "").strip()
        if out:
            return True, out
        # Empty response: likely bad brief; retry once with reasoning visible,
        # then fall back to backup handled by caller.
        time.sleep(2)
    return False, "EMPTY_RESPONSE"


def parse_files(text: str) -> List[Tuple[str, str]]:
    """Parse @@@FILE path / @@@END blocks from worker output."""
    files = []
    current = None
    buf = []
    for line in text.splitlines():
        if line.startswith("@@@FILE "):
            current = line[len("@@@FILE "):].strip()
            buf = []
            continue
        if line.strip() == "@@@END":
            if current is not None:
                files.append((current, "\n".join(buf)))
            current = None
            buf = []
            continue
        if current is not None:
            buf.append(line)
    if files:
        return files
    # Fallback for models that emit literal \\n sequences on one line.
    import re
    for m in re.finditer(r"@@@FILE\s+(\S+)\s*\\n(.*?)\\n@@@END", text, re.S):
        path = m.group(1).strip()
        content = m.group(2).replace("\\n", "\n")
        files.append((path, content))
    return files


def choose_model(preferred: str, backup: str, attempt: int) -> str:
    if attempt == 0:
        return preferred
    return backup
