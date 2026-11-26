# Security

## Threat Model

PiDiagOS is a disposable diagnostic environment for hardware testing. It is not
intended for permanent deployment, data storage, or use on untrusted networks.

Known and intentional characteristics:

- **Shared default password.** `Admin` / `PiDiagOS` is used for SSH, sudo, and
  the web panel; the default Wi-Fi password is `PiDiagOS`. This makes it possible
  to use the board without a keyboard. The password is known to anyone who downloads the image.
- **SSH is enabled and accepts password authentication.** Anyone within Wi-Fi
  range who guesses the password can use `sudo` without additional authentication.
- **Root filesystem in tmpfs (`overlayroot`).** Changes to `/etc` do not persist
  across reboots: password changes made with `passwd` last only until power-off.
  Persistent passwords can only be set at build time (`PIDIAG_USER_PASS`,
  `PIDIAG_WIFI_PASS`).
- **No internet access.** The access point does not route traffic; there are no
  updates or telemetry.

## Risk Mitigation

1. Build the image with your own passwords:
   `PIDIAG_USER_PASS='long-password' PIDIAG_WIFI_PASS='another-password' ./build.sh`
2. Use the board on an isolated network or as an access point, not on a shared
   office network.
3. For remote access, use your own SSH key:
   `PIDIAG_SSH_PUBKEY=~/.ssh/id_ed25519.pub ./build.sh` — key-based login is
   added while password authentication remains enabled.
4. Do not power off the board with untrusted USB devices connected: the runner
   copies reports to the first removable partition.

## What Qualifies as a Vulnerability

- bypassing web panel Basic Auth;
- reading files over HTTP outside `/boot/firmware/diag_results`;
- command injection in `check-wifi.bat` (for example, through a Wi-Fi network name);
- root code execution through a crafted report or USB drive;
- password leakage from the image, except for the default password documented above.

## Reporting a Vulnerability

Do not open a public issue. Contact the address in the GitHub profile
(or use the private Security → Report a vulnerability form) and include:

- image version (from `diag_boot.log`, line `=== PiDiagOS boot log ...`);
- board model and connection method;
- reproduction steps.

You will receive a response within 7 days. Fixes are released under a separate tag.
