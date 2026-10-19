## ADDED Requirements

### Requirement: Felt report trigger
The self-initiated report policy SHALL accept `about_style` `"numeric"` (default) or `"felt"`. In felt mode each speak, think and interrupt intent SHALL carry an `about` that names the top event's source in plain words with a graded surprise word and no digit, `about_kind` `"event"` (only drive phrases are `"felt"`), and `about_values` holding the source, type and surprise. In numeric mode the intent SHALL be unchanged: `about` `"<source> (surprise=<x.xxx>)"`, `about_kind` `"event"` and no `about_values` on the wire. The cycle SHALL select the style from `[language].awareness_rendering`, and the planning proposal source SHALL use the same style for its summary of events that are neither heard speech nor drive crossings.

#### Scenario: Felt think about
- **WHEN** the policy is in felt mode and a vision event with surprise 0.588 crosses the think bar
- **THEN** the think intent's `about` is "Something in what I see stands out noticeably.", its `about_kind` is `"event"` and its payload's `about_values` is `{"source": "vision", "type": "vision.report", "surprise": 0.588}`

#### Scenario: Numeric about unchanged
- **WHEN** the policy is in numeric mode and the same event crosses the think bar
- **THEN** the `about` is "vision (surprise=0.588)", the `about_kind` is `"event"` and the payload has no `about_values` key
