#!/bin/bash
set -euo pipefail

FULL=false

# Commandline args parsing
while test $# -gt 0
  do
      case "$1" in
      (-f|--full)
          FULL=true
          shift
          ;;
      esac
  done

# Check for commandline arg to do a full clean instead of just clearing the app data
if [[ "$FULL" = true ]]; then
  # 1. Wipe the off-device backup FIRST — otherwise reinstall restores it
  adb shell bmgr wipe com.google.android.gms/.backup.BackupTransportService com.cjpa.notes

  # 2. Uninstall (sandbox + keystore keys go with it)
  adb uninstall com.cjpa.notes

  # 3. Verify nothing remains
  adb shell pm list packages | grep cjpa          # expect: no output
  adb shell bmgr list sets                        # restore sets still on the device
else
  # Most often this is all we need:
  adb shell pm clear com.cjpa.notes
exit 0
fi

