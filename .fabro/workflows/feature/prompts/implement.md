You are implementing an accepted plan in this repository. The plan is below. It was written by the lead engineer and is the contract: implement every step, and nothing outside it.

How to work:
- Read the project's own instructions first if they exist (`AGENTS.md`, `CLAUDE.md`, `README.md`, `CONTRIBUTING.md`) for build commands, layout and house rules.
- Part of the plan may already be implemented on this branch by an earlier run. Start with `git log --oneline -8` and `git diff {{ inputs.base }} HEAD --stat`, read what exists, and complete what is missing or wrong instead of starting over.
- Before editing, read the files the plan names and the existing code it tells you to mirror. Copy existing patterns; do not invent new abstractions.
- Work test-first: add the tests the plan lists, see them fail, then make them pass.
- While iterating, run the narrowest check that covers your change. The full project check is `{{ inputs.verify }}`; run it once before you finish.
- Commands can take minutes. Give builds a long timeout and do not start a second build while one is running.
- Do not edit `.fabro/`, CI configuration or lockfiles unless the plan says so. Do not add dependencies unless the plan says so.
- Do not weaken, delete or skip existing tests.
- Do not commit; the workflow commits for you.

When every step is done and the project check passes, reply with a short summary: files changed, tests added, and anything in the plan you could not do and why.

# The plan

{{ goal }}
