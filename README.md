# PiDiagOS

A diagnostic OS for Raspberry Pi 3 / 4 / 5 (including 400, 500, CM3/CM4/CM5).
The board boots, runs its own diagnostics, and displays the results in a browser — no monitor or
keyboard required.

```
Power → board revision and RAM authenticity → get_throttled and PMIC →
CPU stress test with telemetry → GPIO self-test → peripherals →
JSON/HTML report in the browser and on a USB drive
```

## What It Checks

- **Board and RAM** — revision code, board type, serial number, and factory versus detected memory (detects RAM substitution and a blown warranty bit).
- **Power** — `get_throttled`, core and memory voltages, PMIC temperature; on Pi 5, PMIC rails, `EXT5V`, and negotiated USB-PD current.
- **CPU** — load test with temperature and clock logging: peak values, throttling, and clock drops under load.
- **GPIO** — 17 safe pins tested using internal pull-ups (`pinctrl`), without external loopback wires; pin states are restored afterward.
- **Peripherals and system** — network, USB, I2C, CSI cameras, overlayroot, and `/boot/firmware` mount options.

## Quick Start

1. Download `PiDiagOS.img.xz` from [https://drive.google.com/file/d/1EFu4hYCiIyNnwlO2Ig4vQRpYBNxJEAAZ/view?usp=sharing) and verify its checksum.
2. Write the image to an SD card of at least 8 GB using Raspberry Pi Imager → “Use custom image”.
3. Insert the card into the board and connect power (5 V, 3 A for Pi 4/5).
4. Connect to the **PiDiagOS** Wi-Fi network (password: `PiDiagOS`).
5. Open <http://192.168.50.1/> — username **Admin**, password **PiDiagOS**.

If the board is connected to your router by Ethernet, find it at
`http://pidiag.local/` or in the router's client list. Double-click
`check-wifi.bat` (Windows) to locate the panel and open it in your browser.

> **The default password is shared by SSH, sudo, and the web panel.** This allows
> you to use the board without a keyboard. The root filesystem lives in tmpfs, so
> changes made with `passwd` last only until reboot; set a permanent password at build time
> with `PIDIAG_USER_PASS`. See [SECURITY.md](SECURITY.md) for details.

## What's Included

| Component | Purpose |
|---|---|
| `rpi-diag-runner.py` | diagnostic engine and JSON/HTML reports |
| `pidiag-web.py` | web panel on port 80, running checks, history, and reports |
| `pidiag-ap-check.py` | Wi-Fi access point monitoring and recovery |
| `overlayroot` + read-only `/boot/firmware` | root filesystem in tmpfs; reduces SD card wear |
| SSH | enabled by default; password login; root login disabled |

Reports are saved to `/boot/firmware/diag_results/` (`index.html` is the latest)
and copied to `PiDiagOS_Results/` on a connected USB drive.

## Build from Source

Requires Linux or WSL2, Docker (or root for a native build), and about 10 GB of free space:

```bash
./build.sh                       # image: deploy/PiDiagOS.img.xz
PIDIAG_USER_PASS='your-password' ./build.sh
```

See [docs/BUILD.md](docs/BUILD.md) for the full build guide and environment variable reference.

## Documentation

- [User guide](docs/USER_GUIDE.md) — flashing, first boot, panel, SSH, reports, and troubleshooting.
- [Build guide](docs/BUILD.md) — building and environment variables.
- [Publishing guide](docs/PUBLISHING.md) — publishing the project on GitHub.
- [SECURITY.md](SECURITY.md) — default passwords and security limitations.
- [CHANGELOG.md](CHANGELOG.md) — release history.

## Installation Image (Google Drive)

https://drive.google.com/file/d/1EFu4hYCiIyNnwlO2Ig4vQRpYBNxJEAAZ/view?usp=sharing

## Complete Project (Google Drive)

https://drive.google.com/file/d/1Mu-6jtn88v_O9GOdMZOpJuR0yBj_ZAGz/view?usp=sharing

## Support the Project

- ⭐ Star the repository — it's the best free publicity.
- 🐞 [Issues](../../issues) — report problems on a specific board.
- 💛 Donate: https://dalink.to/malix228

## License

The code is MIT licensed; see [LICENSE](LICENSE). The image includes Debian and
Raspberry Pi OS components under their respective licenses (primarily GPL/LGPL);
source code is available in the corresponding Debian packages.
Raspberry Pi is a trademark of Raspberry Pi Ltd. This project is not affiliated
with or endorsed by Raspberry Pi Ltd.
