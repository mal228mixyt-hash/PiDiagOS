# Building the Image

Build the image on Linux or WSL2 using [pi-gen](https://github.com/RPi-Distro/pi-gen).
pi-gen does not run in Git Bash on Windows: it requires loop devices, mounts,
and chroot.

## Requirements

- Linux / WSL2, root (native build), or Docker;
- about 10 GB of free space;
- 30–60 minutes;
- network access to `deb.debian.org` and `archive.raspberrypi.com`.

The pi-gen working directory **must** be on a filesystem that supports symlinks.
On NTFS (`/mnt/c`), debootstrap fails with `tar: Cannot create symlink`, so in
WSL set the directory to a location on ext4:

```bash
export PIDIAG_WORK_DIR=/root/pidiag-pigen/pi-gen
```

## Quick Start

```bash
./build.sh
# output: deploy/PiDiagOS.img.xz and deploy/PiDiagOS.img.xz.sha256
```

Docker is used by default. If Docker is unavailable (for example, if
`registry-1.docker.io` is blocked), build natively as root:

```bash
apt-get install quilt parted coreutils qemu-user-static binfmt-support debootstrap \
    zerofree zip dosfstools e2fsprogs libcap2-bin libarchive-tools rsync xz-utils \
    curl xxd file git kmod bc gpg pigz arch-test

PIDIAG_BUILD_MODE=native PIDIAG_WORK_DIR=/root/pidiag-pigen/pi-gen ./build.sh
```

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `PIDIAG_USER_PASS` | `PiDiagOS` | SSH, sudo, and web panel password |
| `PIDIAG_WIFI_SSID` | `PiDiagOS` | access point name |
| `PIDIAG_WIFI_PASS` | `PiDiagOS` | Wi-Fi password (WPA2, 8–63 characters) |
| `PIDIAG_HOSTNAME` | `pidiag` | network hostname |
| `PIDIAG_SSH` | `1` | set to `0` to disable SSH |
| `PIDIAG_SSH_PUBKEY` | — | path to a public key or the key itself |
| `PIDIAG_BUILD_MODE` | `docker` | `docker` or `native` |
| `PIDIAG_WORK_DIR` | `./.work/pi-gen` | pi-gen directory (must be on ext4) |
| `PIDIAG_PIGEN_REPO` | RPi-Distro/pi-gen | pi-gen source repository |
| `PIDIAG_PIGEN_REF` | `2026-10-06-raspios-bookworm-arm64` | pi-gen tag |
| `PIDIAG_DEBIAN_MIRROR` | `https://deb.debian.org/debian/` | debootstrap mirror |

Example build for a specific deployment:

```bash
PIDIAG_USER_PASS='S3cret-pass' \
PIDIAG_WIFI_SSID='DiagLab' \
PIDIAG_WIFI_PASS='lab-pass-2026' \
./build.sh
```

## Build Process

1. `build.sh` clones the requested pi-gen tag into `PIDIAG_WORK_DIR`.
2. Copies `image/stage-pidiag` into the working directory and removes CRLF.
3. Generates secrets: the web panel password hash (scrypt), username, access
   point profile, and optionally an SSH key. The plaintext password exists only
   in `.work` and is removed inside chroot.
4. Patches `stage0` to use HTTPS for debootstrap and apt.
5. Runs pi-gen and copies the result to `deploy/`.

## What the `stage-pidiag` Stage Does

- installs `overlayroot`, `stress`, `i2c-tools`, `dnsmasq-base`, `avahi-daemon`,
  `wireless-tools`, and `openssh-server`;
- creates the `Admin` account (`adduser --force-badname`) with the build password
  and passwordless sudo; disables pi-gen's service account `diag`;
- enables SSH (password login; root login disabled);
- starts the `PiDiagOS` Wi-Fi access point at `192.168.50.1`;
- enables `rpi-diag`, `pidiag-web`, `pidiag-bootlog`, and `pidiag-ap-check.timer`;
- enables overlayroot (`tmpfs:recurse=0`) and mounts `/boot/firmware` read-only;
- disables swap, Bluetooth, ModemManager, and automatic updates; limits the
  journal to 24 MB;
- builds initramfs for both kernel families (Pi 3/4 and Pi 5).

## Verify the Result Without a Board

```bash
# size and checksum
ls -lh deploy/PiDiagOS.img.xz
sha256sum -c deploy/PiDiagOS.img.xz.sha256

# inspect image contents (Linux)
xz -dk deploy/PiDiagOS.img.xz
fdisk -l deploy/PiDiagOS.img
```

## Common Errors

| Error | Solution |
|---|---|
| `tar: Cannot create symlink` | `PIDIAG_WORK_DIR` is on NTFS; move it to ext4 |
| `Bad owner or permissions` | run as root for a native build |
| `arch-test arm64` fails | install `qemu-user-static` and `binfmt-support` |
| apt cannot download packages | set `PIDIAG_DEBIAN_MIRROR` |
| not enough disk space | allow 10 GB for `.work` plus 1 GB for `deploy` |
