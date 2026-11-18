# Troubleshooting

## Test commands with `&&`, pipes, or redirections fail
The framework intentionally uses argument splitting (no shell). Use one executable, a script, or a Make target:
```bash
test_command: "make test"
```

## Model emits `\\n` instead of real newlines
The parser now supports both forms. Still, prompt workers to emit real line breaks and no markdown fences.

## Worktree creation fails
The repo baseline must be clean. Commit or stash changes before running the daemon.

## Paused/blocked state
Use `--triage` to generate a diagnosis file; resolve tasks or set `DARK_FACTORY_APPROVE_HIGH=1` for high-risk work.

## Model produces no usable output
- Increase `timeout`.
- Add relevant source code to `worker_brief_prefix`.
- Switch `model` and/or `backup_model`.
- Reduce task size.