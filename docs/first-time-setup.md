# First-time setup with the questionnaire

This page walks through a clean first run of KAINE. It uses the built-in questionnaire to turn a new install into a working profile you can edit later.

## Before you start

Install KAINE and make sure the command is available in your shell. Open the folder you want KAINE to help with, or start in an empty workspace if you are exploring. Have your project goal in mind. A short sentence is enough.

## Start the questionnaire

Run KAINE for the first time from your project root. If setup has not been completed, KAINE opens the questionnaire. You can also open it again from the docs or settings entry point when you want to revise earlier answers.

Move one screen at a time. Use the default when it fits. Change it when it does not.

## Answer the profile questions

The questionnaire asks for the basics that shape later behavior.

Name the profile so you can recognize it. Pick the kind of work you expect most, such as docs, tests, refactoring, or review. Choose how much confirmation you want before changes are applied. Set the preferred file scope, from narrow edits to wider repo awareness. Add any paths KAINE should ignore.

If a question feels unclear, keep the safer option. You can tighten behavior after the first task.

## Connect the project context

Point KAINE at the folders that matter. Include source, tests, and docs when they are relevant. Exclude generated output, vendor code, secrets, and large data files. This keeps prompts focused and reduces noisy suggestions.

Review the detected project summary when it appears. Fix obvious mismatches now rather than after a long session.

## Review the first plan

When the questionnaire finishes, KAINE shows a setup summary. Read it like a checklist. Confirm the profile name, scope, confirmation level, ignored paths, and first recommended action.

Save the profile. KAINE writes the local setup state and then returns to the normal workflow.

## Run a small first task

Start with a request that has a clear finish line. Ask for a README note, one failing test fix, or a narrow cleanup. Watch how KAINE reads context, proposes edits, and asks for approval. Accept only the parts you want.

After the run, inspect the changed files and the test result. If the behavior felt too loose, raise confirmation. If it felt slow, widen trust one step at a time.

## If you skipped the questionnaire

You can still work, but defaults may not match the project. Reopen setup from settings, then answer only the questions that need changes. Existing edits are left alone. The goal is a profile that fits the repo, not a perfect interview.

## Next steps

Read the command reference for daily operations. Use the configuration guide when you need durable rules. Check the privacy notes before adding credentials or external services.