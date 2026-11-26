#!/bin/bash
# Writes the boot log and network status to the boot partition.
# Useful without a monitor: diag_boot.log can be read from the card.
sleep 25

if mount -o remount,rw /boot/firmware 2>/dev/null; then
    {
        echo "=== PiDiagOS boot log $(date -Is) ==="
        echo "--- failed units ---"
        systemctl --failed --no-pager
        echo "--- network ---"
        ip -br addr
        nmcli -t -f NAME,DEVICE,STATE connection show 2>&1
        echo "--- access point ---"
        cat /run/pidiag-ap-state.json 2>/dev/null || echo "no data"
        echo "--- journal (tail) ---"
        journalctl -b --no-pager | tail -n 300
    } > /boot/firmware/diag_boot.log 2>&1
    sync
    mount -o remount,ro /boot/firmware 2>/dev/null
fi
