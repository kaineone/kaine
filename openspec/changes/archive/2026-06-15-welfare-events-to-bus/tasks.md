# Tasks

## 1. Welfare observer publishes content-free gray-zone events
- [x] 1.1 Add a content-free bus-publish path to `WelfareObserver`
      (`_emit_gray_zone`): write to the sink AND publish `welfare.gray_zone`
      (source `welfare` → `welfare.out`) with label + numeric scalars only.
- [x] 1.2 Replace the four sink writes with `_emit_gray_zone`; add a
      comment-contract at each site that no source payload field is copied.
- [x] 1.3 Update the observer docstring (no longer strictly read-only — emits
      derived, content-free welfare signals).

## 2. Protective response covers all four categories
- [x] 2.1 `WelfareProtectiveMonitor` subscribes to `welfare.out`
      `welfare.gray_zone` (separate cursor) and feeds each event into the
      windowed-repeat arm; a windowed crossing fires `repeated_gray_zone`.
- [x] 2.2 Keep the existing soma.out sustained-distress arm.

## 3. Research log + raw archive capture
- [x] 3.1 `research_event_observer`: `welfare.out` in the curated streams; the
      `welfare.gray_zone` taxonomy entry present.
- [x] 3.2 Tighten the welfare numeric passthrough to an EXACT field allowlist.
- [x] 3.3 `raw_bus_archive_consumer`: add `welfare.out` to `_MODULE_OUT_STREAMS`.

## 4. Config
- [x] 4.1 Reuse `[preservation.welfare_response]` `repeat_window_s` /
      `repeat_threshold`; document that the repeat arm now covers all four
      gray-zone categories. No new keys.

## 5. Tests + validate
- [x] 5.1 Welfare observer publishes `welfare.gray_zone` with numeric+label only.
- [x] 5.2 Protective monitor acts on a repeated gray-zone crossing of a
      non-distress category.
- [x] 5.3 Research observer records `welfare.gray_zone`; content never leaks.
- [x] 5.4 `openspec validate welfare-events-to-bus --strict`.
