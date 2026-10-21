## Why

The cycle-control file control.json holds a freeze stack written by two processes, the cycle and the dashboard (kaine/dashboard/cycle_control.py:80-86), with no lock, and state_io.write_json_atomic writes through one fixed .tmp name. Two writers can interleave a read-modify-write, so an operator resume can drop a welfare freeze, and two writers can clobber each other's temp file.

## What Changes

- A locked read-modify-write helper (an exclusive file lock beside the file) updates control.json, and both writers use it.\n- Atomic JSON writes use a unique temp file in the same directory, then os.replace.\n- The freeze stack's semantics are unchanged.

## Capabilities

### Modified Capabilities

- `cognitive-cycle`: freeze-stack writes to control.json are locked and use unique temp files

## Impact

- control-freeze-lock0
- Behaviour: control-freeze-lock1
