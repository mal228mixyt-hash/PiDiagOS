# PiDiagOS — User Guide

This guide is for anyone using a Raspberry Pi for the first time and wanting to
test it without a monitor, keyboard, or Linux experience.

---

## 1. What You Need

| Item | Requirements |
|---|---|
| Board | Raspberry Pi 3B/3B+, 4B, 400, 500, CM3/CM4/CM5, Pi 5 |
| Storage | microSD card, 8 GB or larger, A1/A2 class |
| Power supply | 5 V / 2.5 A for Pi 3; 5 V / 3 A (USB-C) for Pi 4/5 |
| Computer | Windows, macOS, or Linux with Wi-Fi |
| Browser | Any modern browser |

The power supply matters more than you might expect: if voltage drops, the power
test will correctly report FAIL even if the board itself is healthy.

---

## 2. Flash the Image to the Card

### Raspberry Pi Imager (recommended)

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Choose OS → Use custom image → select `PiDiagOS.img.xz`.
3. Choose storage → select your card. Make sure it is the correct device:
   flashing erases all its contents.
4. Select Write, wait for completion, then insert the card into the board.

### Command line

```bash
rpi-imager --cli PiDiagOS.img.xz /dev/sdX    # Linux/macOS; sdX is your card
```

Verify the checksum before flashing:

```bash
sha256sum -c PiDiagOS.img.xz.sha256
```

---

## 3. First Boot

1. Insert the card and connect power. Boot takes **30–60 seconds**.
2. For the first ~25 seconds, the board runs checks without a load test; then it
   starts the Wi-Fi access point and web panel.
3. Board LED indicators:
   - **Green blinking** — diagnostics are running.
   - **Both LEDs on** — result PASS.
   - **Green off, red blinking** — result FAIL.

The boot-time check skips the stress test so a weak power supply does not crash
the board at startup. Start the full test from the panel.

---

## 4. Connect to the Panel

### Option A: Board access point (no router)

1. Open the Wi-Fi network list on your computer or phone.
2. Connect to **PiDiagOS**, password **PiDiagOS**.
3. Open <http://192.168.50.1/>.
4. Username **Admin**, password **PiDiagOS**.

This network has no internet access; it is only for accessing the panel. Up to
5–8 devices can connect at once.

### Option B: Through your router (Ethernet)

1. Connect the board to your router with an Ethernet cable.
2. Open <http://pidiag.local/> (the hostname is advertised via mDNS/avahi).
3. If the hostname does not resolve, find the board's address in the router's
   client list or ping the hostname `pidiag`.

### Option C: Windows helper

Double-click `check-wifi.bat` in the project folder. It:

- shows which Wi-Fi network the computer is connected to;
- detects the default gateway;
- checks `192.168.50.1`, `pidiag.local`, `pidiag`, and the gateway;
- opens the panel in your browser when found.

To only display the address without opening a browser:

```bat
check-wifi.bat /nobrowser
```

Requires Windows 10/11; uses the built-in `curl` (with PowerShell as fallback).

---

## 5. Web Panel

| Button | Action | Duration |
|---|---|---|
| Quick Check | power, revision, RAM, GPIO, peripherals | 5–15 s |
| Full Test (60 s stress test) | same checks plus a 60 s all-core load | ~1.5 min |
| Open Report | latest HTML report | — |
| Check Wi-Fi | restart the access point if it fails | up to 30 s |

The page shows the board model, RAM capacity, peak temperature, `get_throttled`,
access point status, connected devices, and the last 10 checks.

The panel is protected by Basic Auth. Credentials are set when the image is
built; the defaults are `Admin` / `PiDiagOS`.

---

## 6. SSH

SSH is enabled by default:

```bash
ssh Admin@192.168.50.1      # from the PiDiagOS network
ssh Admin@pidiag.local      # from the local network
```

The password is the same as for the panel (default: `PiDiagOS`). Root login is
disabled; `Admin` has passwordless sudo access.

If `PIDIAG_SSH_PUBKEY` was supplied at build time, key-based login is available
alongside password authentication.

---

## 7. Reports

- `/boot/firmware/diag_results/` — JSON and HTML reports from each check;
  `index.html` is always the latest report.
- `/boot/firmware/diag_boot.log` — boot log and network status.
- Connected USB drive (vfat/ext4/exfat/ntfs) — copies are saved under `PiDiagOS_Results/`.

`/boot/firmware` is mounted read-only. The board temporarily remounts it as
writable while saving, then switches it back to read-only.

---

## 8. Understanding the Results

- **PASS** — all required checks passed.
- **FAIL** — a problem was found: counterfeit/mismatched RAM, undervoltage,
  throttling under load, overheating, or faulty GPIO pins.
- **SKIP** — a check does not apply: no camera, Bluetooth disabled, or `pinctrl` missing.
- The score shows each component's contribution. “System” receives points when
  overlayroot is active and `/boot/firmware` is mounted read-only.

Common causes of FAIL:

| Symptom | Cause |
|---|---|
| undervoltage / `0x50000` | weak power supply or cable |
| throttling after 60 seconds | no heatsink or poor case ventilation |
| RAM mismatch | board has been reworked or its revision is counterfeit |
| GPIO FAIL on one pin | damaged pin or external load connected |

---

## 9. System Characteristics

- **Root filesystem in tmpfs (`overlayroot`).** The SD card is not worn by system
  writes, but system changes (passwords, SSH keys, network settings) last only
  until reboot. Persistent changes require rebuilding the image (`PIDIAG_USER_PASS`,
  `PIDIAG_WIFI_SSID`, `PIDIAG_WIFI_PASS`).
- **Change password for one session:** run `passwd` (or `sudo passwd Admin`).
- **Wi-Fi:** the network is named `PiDiagOS`; the board address is always `192.168.50.1`.
- **Swap and unnecessary services are disabled:** saves RAM on boards with 1 GB.

---

## 10. Troubleshooting

**PiDiagOS network is not visible**
- Wait 60 seconds after connecting power.
- Make sure the card was fully flashed (not written as a “raw” copy of the file).
- Boards without Wi-Fi (for example, a CM4 without a wireless module) cannot
  start the access point; use Ethernet instead.

**Panel does not open at 192.168.50.1**
- Make sure the computer is connected to the PiDiagOS network, not your home network.
- Check that the address was assigned automatically (DHCP), not configured manually.

**Panel asks for a password but rejects it**
- The username is case-sensitive: use `Admin`, not `admin`.
- The default password is `PiDiagOS`; if the image was built with a different
  `PIDIAG_USER_PASS`, use that password.

**Board reboots under load**
- This indicates a voltage drop: replace the power supply and cable, then rerun the test.

**Need the log without a monitor**
- Power off the board, insert the card into a computer, and open `diag_boot.log`
  from the boot partition.

---

## 11. Limitations

- The image is built and tested on Pi 3/4/5. CM and Pi 400/500 use the same
  components but have been tested less extensively.
- The stress test assumes stock cooling. Pi 4/5 boards without a heatsink may
  throttle; this is an expected result, not an error.
- The access point has no internet access and does not isolate clients. Do not
  connect the board to untrusted networks while using the known default password.
