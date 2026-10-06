## ADDED Requirements

### Requirement: Input loss is measured in unfrozen time
The input-loss watcher SHALL measure how long every configured input has been silent with a clock that does not advance while the freeze stack holds any entry. A freeze, including one that switches perception off, SHALL NOT by itself produce an input-loss notice. An input that stays silent after the freeze is released SHALL be reported once its unfrozen silence passes `[caretaker].input_loss_after_s`.

#### Scenario: An operator freeze is not input loss
- **WHEN** the operator freezes the cycle for longer than the input-loss threshold and the freeze switches perception off
- **THEN** no input-loss notice is sent

#### Scenario: A real loss during a freeze is still reported
- **WHEN** the camera is unplugged during a freeze and stays unplugged after release
- **THEN** an input-loss notice is sent once the silence after release passes the threshold
