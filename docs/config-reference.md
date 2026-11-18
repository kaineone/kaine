# KAINE Configuration Reference

This page explains every key in kaine.yaml. Each explanation covers what the key controls and when you would reach for it. Every value shown below is a default, so you only need to copy the keys you actually want to change. Put your edited keys in kaine.yaml at the root of your repository.

The annotated config below is an indented block, not a fence, so the comments stay readable in plain text viewers too.

    project:
      # name: The display name KAINE uses in logs, reports, and commit trailers.
      # Change it when the repo belongs to a new product or team, or when two
      # repos would otherwise produce identically labeled output.
      name: my-app
      # description: One sentence about what the repo does. KAINE feeds this to
      # the model as context when it plans work.
      # Change it when the repo's purpose shifts, or when the model keeps
      # planning around the wrong assumptions about your codebase.
      description: A short statement about this repository.

    spec:
      # directory: Where OpenSpec change proposals live, relative to the repo
      # root. KAINE reads and writes proposals, specs, and tasks here.
      # Change it only if your team stores specs somewhere other than the
      # openspec convention, such as a dedicated docs repository layout.
      directory: openspec

    model:
      # provider: Which API backend KAINE talks to. Accepted values depend on
      # the providers installed in your environment.
      # Change it when your organization switches vendors or when one provider
      # is having an outage and you need a working alternative.
      provider: anthropic
      # name: The exact model KAINE requests from the provider.
      # Change it to trade cost against quality, or when a newer model becomes
      # available and you have verified it behaves well on your tasks.
      name: claude-sonnet-4-5
      # temperature: How random the model's answers are, on a 0 to 1 scale.
      # Lower values give steadier, more predictable output. Higher values give
      # more varied output.
      # Lower it when the model drifts away from instructions. Raise it only
      # for brainstorming-style work, never for code edits you plan to keep.
      temperature: 0.2
      # max_tokens: The ceiling on a single model response.
      # Raise it when the model's output gets cut off mid-file. Lower it to
      # trim spending on providers that bill per token.
      max_tokens: 8192
      # timeout_seconds: How long KAINE waits for the provider before giving
      # up on a request.
      # Raise it on slow networks or with heavyweight models. Leave it alone
      # otherwise, because a very high value can hide a stuck request.
      timeout_seconds: 120
      # max_retries: How many times KAINE repeats a failed request before it
      # reports an error to you.
      # Raise it if your provider rate-limits often. Keep it low during
      # debugging so failures surface quickly instead of after several minutes
      # of silent retries.
      max_retries: 3
      # fallback_model: The model KAINE switches to after the primary one
      # exhausts its retries. Empty means no fallback.
      # Set it when you want work to continue through a provider outage, and
      # pick a model you trust enough to finish real tasks.
      fallback_model: ""

    agent:
      # max_steps: The most tool calls KAINE will make in one task run.
      # Raise it for large multi-file refactors that legitimately need many
      # edits and test runs. Lower it on cheap or weak models to stop runaway
      # loops before they burn through your budget.
      max_steps: 50
      # parallel_workers: How many independent tasks KAINE may work on at the
      # same time.
      # Raise it on fast machines with generous API rate limits. Drop it to 1
      # if workers ever edit the same files at once or if your provider
      # throttles you.
      parallel_workers: 1
      # auto_approve: Whether KAINE applies its own edits without asking first.
      # Turn it on for trusted, well-scoped tasks. Turn it off whenever the
      # task touches production config, migrations, or anything that is hard to
      # revert.
      auto_approve: false
      # plan_checkpoints: Whether KAINE pauses to show you its plan before it
      # starts editing files.
      # Leave it on for unfamiliar tasks. Turn it off for repeatable chores
      # where you already know what the plan will look like.
      plan_checkpoints: true

    tools:
      # allow: The tool names KAINE may call. Anything not listed is refused.
      # Edit this list when you add a new integration, or when you want to
      # strip a capability you no longer trust the agent with.
      allow: [read_file, write_file, list_files, run_shell, git]
      # deny: Tool names that stay off even if something else enables them.
      # The deny list wins over the allow list.
      # Add entries here as a hard block when a blanket ban is clearer than
      # carefully trimming the allow list.
      deny: []
      # shell.enabled: Whether KAINE can run shell commands at all.
      # Turn it off in shared or sandboxed environments where arbitrary
      # commands are a risk. Keep it on for normal development, since most
      # tasks need to run tests and builds.
      enabled: true
      # git.enabled: Whether KAINE can stage, commit, and branch.
      # Turn it off when you want to review changes in a raw diff before any
      # history gets written.
      git:
        enabled: true

    workspace:
      # root: The directory KAINE treats as the top of your project. All
      # relative paths the model uses resolve from here.
      # Change it only if your repo root is not where you launch KAINE from,
      # such as when you run the tool from a wrapper script elsewhere.
      root: .
      # cache_dir: Where KAINE stores intermediate results, conversation
      # state, and downloaded model metadata.
      # Change it when the default location sits on a small or slow disk, or
      # when several projects fight over one cache.
      cache_dir: .kaine/cache
      # snapshots: Whether KAINE saves a copy of your working tree before each
      # edit batch, so you can roll back.
      # Keep it on unless disk space is genuinely tight. Rollback is cheaper
      # than reconstruction.
      snapshots: true
      # snapshot_interval: How many edit batches happen between snapshots.
      # Lower it, meaning more frequent snapshots, when tasks are risky or
      # long. Raise it when snapshotting noticeably slows the run.
      snapshot_interval: 1

    logging:
      # level: How much detail lands in the log. From quietest to loudest the
      # order is error, warn, info, debug.
      # Use debug when you are diagnosing a problem. Stay at info or warn for
      # everyday runs, because debug logs grow fast and can include prompts.
      level: info
      # format: The shape of each log line, either text for humans or json for
      # log pipelines.
      # Switch to json when you ship logs to a search system such as
      # Elasticsearch or CloudWatch. Stay on text for terminal use.
      format: text
      # file: Where logs are written in addition to the console. Empty means
      # console only.
      # Set a path when you need an audit trail or when you are reporting a
      # bug and want a complete record to attach.
      file: ""
      # redact_secrets: Whether KAINE scans outgoing logs for tokens and keys
      # and blanks them out.
      # Leave this on. Turn it off only briefly, and only when redaction is
      # hiding a value you need to see while debugging, and turn it back on
      # right after.
      redact_secrets: true

    git:
      # branch_prefix: The text KAINE puts at the front of every branch it
      # creates.
      # Change it to match your team's naming rules so branch filters and CI
      # triggers keep working.
      branch_prefix: kaine/
      # commit_style: The commit message format KAINE follows. The default
      # follows the conventional commit style.
      # Change it if your project enforces a different format through commit
      # linting.
      commit_style: conventional
      # push: Whether KAINE pushes finished branches to the remote on its own.
      # Turn it off when you always want a human to inspect the branch locally
      # before it leaves the machine.
      push: false
      # sign_commits: Whether commits get a cryptographic signature.
      # Turn it on if your repository requires signed commits, and make sure
      # your signing key is available to the KAINE process first.
      sign_commits: false

## Reading order for new setups

Start with model.name and model.provider, since nothing else matters until KAINE can reach a working model. Then check agent.auto_approve and tools, because those two decide how much trust you extend on the first run. Everything else can stay at defaults until you hit a specific problem, and each comment above tells you what that problem looks like.

## Compatibility notes

Unknown keys are ignored with a warning, not an error, so older configs keep working when the tool gains new options. Removing a key restores its default. Renamed keys keep their old name working for at least one major release, and the startup log tells you when you are relying on a deprecated name.