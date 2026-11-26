#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PiDiagOS access point self-check.

Runs at boot and on a timer. If the access point is down, tries to bring it up
again. Writes its result to /run/pidiag-ap-state.json, which is read by the web
panel to display status and connected devices.
"""

import glob
import json
import os
import re
import subprocess
import time
from datetime import datetime

STATE_PATH = "/run/pidiag-ap-state.json"
PROFILE = "/etc/NetworkManager/system-connections/pidiag-ap.nmconnection"
IFACE = "wlan0"


def run(cmd, timeout=20):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


def profile_values():
    values = {"id": "", "ssid": "", "psk": ""}
    try:
        with open(PROFILE, encoding="utf-8") as f:
            for line in f:
                for key in values:
                    if line.startswith(key + "=") and not values[key]:
                        values[key] = line.split("=", 1)[1].strip()
    except OSError:
        pass
    return values


def iface_exists():
    return os.path.isdir("/sys/class/net/" + IFACE)


def ap_active(conn_id):
    rc, out, _ = run(["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"])
    if rc != 0:
        return False
    for line in out.splitlines():
        if ":" not in line:
            continue
        name, dev = line.rsplit(":", 1)
        if dev == IFACE and (name == conn_id or name.lower().startswith("pidiag")):
            return True
    return False


def iface_ip():
    rc, out, _ = run(["ip", "-4", "-o", "addr", "show", IFACE])
    if rc != 0:
        return ""
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
    return m.group(1) if m else ""


def clients():
    leases = []
    for pattern in ("/var/lib/NetworkManager/*.leases", "/var/lib/misc/dnsmasq*.leases"):
        leases.extend(glob.glob(pattern))
    out = []
    for path in leases:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 4:
                        out.append({
                            "expires": parts[0],
                            "mac": parts[1],
                            "ip": parts[2],
                            "name": "" if parts[3] == "*" else parts[3],
                        })
        except OSError:
            continue
    return out


def check():
    prof = profile_values()
    actions = []
    ok = False
    note = ""

    # On a fresh image, the brcmfmac driver may take a while to create wlan0
    for _ in range(15):
        if iface_exists():
            break
        time.sleep(1)

    if not iface_exists():
        note = "no wireless adapter"
    elif not prof["id"]:
        note = "access point profile not found"
    else:
        # A software radio block can occur after flashing the image to a new card
        run(["rfkill", "unblock", "wifi"], timeout=10)

        rc, out, _ = run(["systemctl", "is-active", "NetworkManager"])
        if rc != 0 or out != "active":
            actions.append("starting NetworkManager")
            run(["systemctl", "start", "NetworkManager"], timeout=40)
            time.sleep(3)

        if not ap_active(prof["id"]):
            actions.append("bringing up access point %s" % (prof["id"] or "pidiag-ap"))
            run(["nmcli", "connection", "up", prof["id"]], timeout=40)
            time.sleep(4)

        ok = ap_active(prof["id"]) and bool(iface_ip())
        if not ok:
            note = "access point failed to start"
            actions.append("restarting NetworkManager")
            run(["systemctl", "restart", "NetworkManager"], timeout=60)
            time.sleep(8)
            run(["nmcli", "connection", "up", prof["id"]], timeout=40)
            time.sleep(4)
            ok = ap_active(prof["id"]) and bool(iface_ip())
            if not ok:
                note = "access point failed to start after restart"

    state = {
        "checked": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ok": ok,
        "note": note,
        "ssid": prof["ssid"],
        "id": prof["id"],
        "ip": iface_ip(),
        "iface": IFACE,
        "clients": clients(),
        "actions": actions,
    }
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return state


if __name__ == "__main__":
    result = check()
    print(json.dumps(result, ensure_ascii=False))
