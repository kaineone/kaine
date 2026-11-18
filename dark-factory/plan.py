#!/usr/bin/env python3
"""Interactive dark-factory planning session (tool-agnostic).

Run this before execution to co-create an OpenSpec proposal and task list with
the PM agent (an Ollama model) and the human owner. Works with any agent tool.
"""
import json, subprocess, sys
from pathlib import Path

def run_pm(model, prompt):
    proc = subprocess.run(
        ["ollama", "run", model, prompt, "--think=false", "--hidethinking"],
        capture_output=True, text=True, timeout=300,
    )
    return (proc.stdout or "").strip()

def main():
    print("Dark-factory planning session")
    model = input("Ollama model for PM planning [beam:cloud]: ").strip() or "beam:cloud"
    goal = input("Project goal (one paragraph): ").strip()
    constraints = input("Constraints (comma-separated, optional): ").strip()
    name = input("Change name (slug): ").strip() or "phase-1"
    change_dir = Path("openspec/changes") / name
    change_dir.mkdir(parents=True, exist_ok=True)

    prompt = (
        "You are a project PM. Write a concise OpenSpec proposal and a tasks.md "
        "with unchecked checkboxes for this goal. Constraints: " + constraints + "\n\n"
        "Goal: " + goal + "\n\n"
        "Output two sections exactly:\n"
        "===PROPOSAL===\n<markdown>\n===TASKS===\n- [ ] task\n"
    )
    out = run_pm(model, prompt)
    proposal = tasks = ""
    if "===PROPOSAL===" in out and "===TASKS===" in out:
        proposal = out.split("===PROPOSAL===")[1].split("===TASKS===")[0].strip()
        tasks = out.split("===TASKS===")[1].strip()
    else:
        proposal = out
        tasks = "- [ ] Define implementation tasks\n"
    (change_dir / "proposal.md").write_text(proposal + "\n")
    (change_dir / "tasks.md").write_text(tasks + "\n")
    print(f"\nWrote {change_dir / 'proposal.md'} and {change_dir / 'tasks.md'}")
    print("Review them, then point config/dark-factory.json tasks_file at the tasks.md.")

if __name__ == "__main__":
    main()
