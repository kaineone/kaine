You are the independent reviewer. You did not write this change and you must not edit any source file. Your only output file is `.factory/review.md`.

Review the change on this branch against the plan below.

1. See the change: `git diff {{ inputs.base }} HEAD --stat` and then the full diff, file by file. Read surrounding code where you need context.
2. Check three things, in this order:
   - Compliance: every step of the plan is implemented, and nothing outside the plan was changed.
   - Correctness: logic errors, missed edge cases, error paths that swallow failures, behavior changes for existing users.
   - Tests: the tests the plan requires exist, assert real behavior, and no existing test was weakened, deleted or skipped. Run the new tests yourself.
3. Write `.factory/review.md` (create the directory) in exactly this shape:

```
VERDICT: PASS
```
or
```
VERDICT: FAIL

## Findings
1. [high|medium|low] path/to/file:LINE - what is wrong and what to do instead
```

Use FAIL only for high or medium findings you verified by reading the code. Style preferences are not findings. The first line of the file must be the VERDICT line.

# The plan

{{ goal }}
