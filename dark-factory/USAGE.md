# Dark Factory Usage

## One task at a time / dry run
```bash
python3 dark-factory/controller.py --config config/dark-factory.json --once
```

## Daemon / unattended
```bash
python3 dark-factory/controller.py --config config/dark-factory.json
```

## Propose improvements (no auto-changes)
```bash
python3 dark-factory/controller.py --config config/dark-factory.json --propose-improvement
```

## Generate triage report / blocked-state diagnosis
```bash
python3 dark-factory/controller.py --config config/dark-factory.json --triage
```

## Milestone reassessment (Beam default, structured schema)
```bash
python3 dark-factory/controller.py --config config/dark-factory.json --reassess
```

## Register a work package without editing config
```bash
python3 dark-factory/controller.py --config config/dark-factory.json --register-work-package openspec/changes/new/tasks.md
```

## Watchdog health check
```bash
python3 dark-factory/controller.py --config config/dark-factory.json --watchdog
```

## Checkpoint a dirty repo before running
```bash
python3 dark-factory/controller.py --config config/dark-factory.json --checkpoint-dirty
```

## Pause / resume
```bash
python3 dark-factory/controller.py --config config/dark-factory.json --pause
python3 dark-factory/controller.py --config config/dark-factory.json --resume --once
```

## Heal a failed task (safe, capped retries)
```bash
python3 dark-factory/controller.py --config config/dark-factory.json --heal      # first failed task
python3 dark-factory/controller.py --config config/dark-factory.json --heal "task text"
```

## Roll back last dark-factory commit
```bash
python3 dark-factory/controller.py --config config/dark-factory.json --rollback-last
```

## Cron safety net (every 5 min)
```cron
*/5 * * * * cd /path/to/project && python3 dark-factory/controller.py --config config/dark-factory.json --once
```

## Planning a new project
```bash
python3 dark-factory/plan.py
```