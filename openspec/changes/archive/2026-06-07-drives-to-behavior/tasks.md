## 1. Drive-biased policy

- [x] 1.1 Implement `DriveBiasedActionSelectionPolicy` (in `kaine/workspace/`,
      e.g. `drive_policy.py`) subsuming `DefaultActionSelectionPolicy`'s
      user-communication handling and adding drive-driven intents:
      `social_drive`→`speak`, `curiosity`/`boredom`/`restlessness`→`think`.
- [x] 1.2 Enforce: inhibition gate (inherited via Volition), one `speak`/tick,
      user utterance outranks social-drive speak, separate speak/think
      in-flight guards (cleared when own `lingua.external`/`lingua.internal`
      output becomes conscious), never respond to own output.
- [x] 1.3 Recognize `thymos.drive` events by source `thymos` + type
      `thymos.drive`, reading the `drive` name from the payload.

## 2. Wire it in

- [x] 2.1 In `kaine/boot.py`, construct `Volition` with the drive-biased policy
      when `[volition].drive_initiative` is enabled (default on). Default on in
      code; report the `[volition].drive_initiative` knob for the operator.
      NOTE: live `Volition` is constructed in `kaine/cycle/__main__.py` (not
      boot.py); wired there, reading `[volition].drive_initiative` (default on).

## 3. Tests (fakes only — no live boot)

- [x] 3.1 social_drive crossing (non-inhibited, no user utterance, speak free)
      → one `speak` intent.
- [x] 3.2 curiosity/boredom/restlessness crossing → one `think` intent.
- [x] 3.3 inhibited snapshot with drive crossings → no intent.
- [x] 3.4 user utterance + social_drive crossing → the one speak intent is the
      user response.
- [x] 3.5 in-flight guards prevent stacked speak/think; cleared on own output.
- [x] 3.6 drive-initiative disabled → behaves exactly like the default policy.

## 4. Verify

- [x] 4.1 Full suite green — no skips/xfails added; fix root causes.
- [x] 4.2 `openspec validate "drives-to-behavior"` passes.
