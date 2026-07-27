#!/usr/bin/env bash
# PreToolUse hook — blocks writes containing forbidden vehicle-bus service requests.
#
# Why this exists: CLAUDE.md and .claude/rules/ are context, not enforced configuration.
# Claude reads them and usually complies. "Usually" is not an acceptable safety margin for
# code that writes to a car's CAN bus. This hook executes regardless of what the model decides.
#
# Install: chmod +x .claude/hooks/block-forbidden-uds.sh
# Register in .claude/settings.json:
#   { "hooks": { "PreToolUse": [ { "matcher": "Write|Edit",
#       "hooks": [ { "type": "command", "command": ".claude/hooks/block-forbidden-uds.sh" } ] } ] } }

set -euo pipefail

payload="$(cat)"

# Only inspect content destined for files that can talk to the vehicle.
path="$(printf '%s' "$payload" | grep -oE '"file_path"[[:space:]]*:[[:space:]]*"[^"]+"' | head -1 | sed 's/.*"\(.*\)"$/\1/' || true)"

case "$path" in
  *OBDManager.swift|*obd_reader.py|*capture_scripts/*|*main.py|*/Services/*.swift) ;;
  *) exit 0 ;;
esac

# Forbidden UDS/OBD service requests. Matches common literal forms:
#   "2E 01 F1", "0x2E", "sendCommand(\"31 01 ...\")", "2F0130"
# Deliberately noisy: a false positive costs one explanation, a false negative costs an ECU.
patterns=(
  '\b0x14\b' '"14 '        # ClearDiagnosticInformation
  '\b0x2E\b' '"2E '        # WriteDataByIdentifier
  '\b0x2F\b' '"2F '        # InputOutputControl
  '\b0x31\b' '"31 '        # RoutineControl
  '\b0x11\b' '"11 0'       # ECUReset
  '\b0x27\b' '"27 '        # SecurityAccess
  '\b0x28\b' '"28 '        # CommunicationControl
  '\b0x85\b' '"85 '        # ControlDTCSetting
)

hits=""
for p in "${patterns[@]}"; do
  if printf '%s' "$payload" | grep -qiE "$p"; then
    hits="${hits}  - matched pattern: ${p}\n"
  fi
done

if [ -n "$hits" ]; then
  {
    echo "BLOCKED: this edit appears to send a forbidden diagnostic service to the vehicle."
    echo ""
    printf '%b' "$hits"
    echo ""
    echo "Permitted on the bus: 19 02 FF (ReadDTCInformation), 10 03 (extended session),"
    echo "3E 80 (tester present), standard OBD modes 01/02/03/06/07/09/0A, and AT/ST adapter commands."
    echo ""
    echo "Forbidden: 0x14, 0x2E, 0x2F, 0x31, 0x11, 0x27, 0x28, 0x85, and Mode 04 on any"
    echo "non-engine address. See .claude/rules/obd-safety.md."
    echo ""
    echo "If this is a false positive (e.g. an unrelated constant that happens to match),"
    echo "say so explicitly and ask the user to approve, rather than reformatting the code"
    echo "to evade this check."
  } >&2
  exit 2
fi

exit 0
