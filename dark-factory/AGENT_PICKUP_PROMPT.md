# Dark Factory Agent Pickup Prompt

You are the coordinator for this project. A dark-factory toolbox has been dropped into this repository.

## First-run adoption
1. Read `DARK-FACTORY-BOOTSTRAP.md` and `USAGE.md`.
2. If no `config/dark-factory.json`, create one from `config/dark-factory.json.example` and set:
   - `tasks_file` to the project's task/checklist markdown (must contain `- [ ] ...`).
   - `test_command` to the project's real test command.
   - `model` / `backup_model` to available off-the-shelf coding models.
3. Ensure the git working tree is clean enough for worktree isolation.
4. Run one supervised dry run:
   `python3 dark-factory/controller.py --config config/dark-factory.json --once`
5. Inspect `.dark-factory-state.json`, heartbeat, ledger, and evidence.

## Ongoing behavior
- Do not write implementation modules directly; delegate coding to workers.
- Use `--pause` / `--resume` for human control.
- Treat `--once` as a smoke test before unattended daemon runs.
- Keep task scope to OpenSpec/proposal + tasks only; do not invent tasks.
- Respect budgets/deadlines and skip high-risk tasks unless approved (`DARK_FACTORY_APPROVE_HIGH=1`).
- After completion, report one-line progress + commit hash, not full narrative.

## Drop-in checklist
- [ ] Config created and validated
- [ ] One dry run succeeded
- [ ] Worker brief matches repo conventions
- [ ] Safety net (`--once` cron) installed
- [ ] Human notified of milestone build path