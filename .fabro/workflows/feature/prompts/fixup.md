The Verify step failed. Its output is in your context. The command it runs is `{{ inputs.verify }}`.

Fix every reported failure in the code you changed for the plan below. Rules:
- Fix the cause in the implementation. Do not weaken, delete or skip tests, and do not silence lints unless the same pattern already exists nearby.
- Re-run the failing check yourself before finishing.
- If a failure is clearly unrelated to this change (it fails the same way on untouched code), say so in your summary instead of editing around it.
- Stay inside the plan's scope. Do not commit.

# The plan

{{ goal }}
