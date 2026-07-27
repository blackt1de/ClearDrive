---
paths:
  - "capture_scripts/**/*"
  - "obd_reader.py"
  - "ios/**/OBDManager.swift"
  - "ios/**/Services/*.swift"
  - "main.py"
---

# Vehicle safety — read-only diagnostics

This code talks to a real car that a real person drives. A wrong byte on the bus can disable ABS, deploy-arm an airbag module, or brick an ECU. There is no undo.

## Permitted on the vehicle

| Purpose | Bytes |
|---|---|
| Read DTC information (UDS) | `19 02 FF` |
| Extended diagnostic session, only when the module map says `session_required` | `10 03` |
| Tester present, only to hold a session open past S3 | `3E 80` |
| Standard OBD reads | Modes `01`, `02`, `03`, `06`, `07`, `09`, `0A` |
| Adapter configuration | `AT`/`ST` commands |

## Forbidden everywhere, no exceptions, no flags

`0x14` ClearDiagnosticInformation · `0x2E` WriteDataByIdentifier · `0x2F` InputOutputControl · `0x31` RoutineControl · `0x11` ECUReset · `0x27` SecurityAccess · `0x28` CommunicationControl · `0x85` ControlDTCSetting · OBD Mode `04` on any non-engine address.

Existing Mode `04` clear functionality stays confined to the engine ECU on its current code path. Do not generalize it, do not parameterize its address, do not call it from a sweep.

## Rules that are easy to get wrong

1. **A module that does not answer is `no_response`, never "no faults."** Reporting a silent airbag module as healthy is the single most dangerous bug this codebase can ship.
2. **No speculative addresses.** Every module address comes from `capture_scripts/uds/module_map.json` with a `source` field. Never scan an address range blind.
3. **Stationary only.** Multi-module capture requires speed == 0 or explicit user confirmation, and must abort if speed becomes non-zero mid-sweep. Preserve partial results on abort.
4. **No gateway bypass.** If a 2018+ vehicle's modules refuse, record a limitation string and stop. Do not attempt security access, seed/key, or any workaround.
5. **Partial captures are valid.** A failed optional command records `null` plus a limitation string and capture continues. Never fabricate a value to complete a payload.
6. **Restore adapter state.** Any `AT SH`/`AT CRA` change is restored before the next phase.

## Before you commit

The PreToolUse hook blocks forbidden service bytes in diffs, but it is a backstop, not permission to be careless. If a change adds any new byte sequence sent to the vehicle, say so explicitly in the PR body and name the source document that specifies it.
