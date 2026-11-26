# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versions: [SemVer](https://semver.org/).

## [1.0.0] — 2026-11-06

### Added

- A shared `Admin` account with a build-time password for SSH, sudo, and the web panel.
  The default password is `PiDiagOS`; override it with `PIDIAG_USER_PASS`.
- SSH enabled by default (password login; root login disabled). Optionally add
  a public key with `PIDIAG_SSH_PUBKEY`.
- Wi-Fi access point built into the same image as diagnostics; no separate
  `apply_webap.sh` step is required.
- `pidiag.local` via avahi: access the panel by hostname as well as IP address.
- `check-wifi.bat` for Windows: detects the network and gateway, then opens the panel.
- Documentation for usage, building, publishing, and security.
- CI checks Python and shell syntax on every push.

### Fixed

- The “System” section in the score always showed 0 points because its status was
  `INFO` while the score expected `PASS`.
- The web panel displayed a “VNC Screen” button pointing to unused port 6080
  (VNC is not installed in the image).
- Panel demo mode failed when `/opt/pidiag/report_template.html` was missing.
- Removed a duplicate `mount -o remount,rw` when saving reports.
- `pidiag-bootlog.service` did not run because its unit had no `[Install]` section,
  so `diag_boot.log` was not written to the card.
- Access point self-check failed when the Wi-Fi profile was missing; it now reports
  the issue and does not try to bring up an empty connection.
- `rfkill` now automatically clears the software Wi-Fi block.

### Changed

- Journal size limited to 24 MB (`Storage=volatile`); with overlayroot it previously
  consumed the board's RAM.
- Disabled SD card swap, Bluetooth, ModemManager, automatic updates, and maintenance
  timers to reduce SD card writes and memory use.
- Packages `dnsmasq-base`, `avahi-daemon`, `libnss-mdns`, `wireless-tools`, and
  `openssh-server` are installed during the build.

## [0.9.0] — 2026-11-05

- First built release: board, RAM, power, CPU, GPIO, and peripheral checks.
- Web panel, JSON/HTML reports, USB copy, and overlayroot.
