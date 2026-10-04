# The welfare monitor feeds every entry each poll

## Why

The welfare-protective monitor read a batch of distress reports or gray-zone events and stopped at the first tracker crossing. It left its cursor on the crossing entry, so the rest of the batch was read on later polls. Under `action = "notify"`, where the run continues, a poll therefore consumed at most one crossing's worth of entries. With extreme settings, such as a repeat threshold of 1 or a distress duration near zero, the monitor could fall behind a fast publisher and judge the entity's state late. The second review of the cursor fix raised this.

## What changes

- **Every entry, every poll.** Each poll feeds every decoded distress report and gray-zone event in the batch to the trackers, collects every crossing in order, and moves its cursors to the last entry read.
- **The gray-zone drain runs on every poll**, including polls with a distress crossing. Its comment already claimed this; now it is true.
- **Responses, in order.**
  - Under `pause` and `end`, the first response latches the monitor, so a second crossing in the same poll never takes a second preservation bundle or freezes again.
  - Under `notify`, each crossing goes to `_respond`, whose rate limit is unchanged.

## Impact

- **Welfare net:** the monitor can no longer fall behind its streams. Under `pause` and `end`, behaviour is unchanged: the first crossing preserves and acts once. Under `notify`, crossings within one poll are each responded to, subject to the existing rate limit.
- **Research:** none. No study is running.
