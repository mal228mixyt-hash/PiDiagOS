#!/bin/bash
# Build the PiDiagOS image with pi-gen (bookworm, arm64).
# PIDIAG_BUILD_MODE=docker (default) runs pi-gen in a container; Docker is required.
# PIDIAG_BUILD_MODE=native runs pi-gen directly; root and dependencies are required.
# Build takes 30–60 minutes and requires about 10 GB of free space.
#
# Default credentials: login Admin / PiDiagOS, Wi-Fi PiDiagOS / PiDiagOS.
# Override with PIDIAG_USER_PASS, PIDIAG_WIFI_SSID, and PIDIAG_WIFI_PASS.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The pi-gen working directory must support symlinks: on NTFS
# (/mnt/c), debootstrap fails with tar: Cannot create symlink. Override with
# PIDIAG_WORK_DIR, for example to a directory on WSL ext4.
WORK_DIR="${PIDIAG_WORK_DIR:-${ROOT_DIR}/.work/pi-gen}"
STAGE_SRC="${ROOT_DIR}/image/stage-pidiag"
FILES_DIR="${STAGE_SRC}/00-install-diag/files"
DEPLOY_DIR="${ROOT_DIR}/deploy"
BUILD_MODE="${PIDIAG_BUILD_MODE:-docker}"

# Credentials: one password for the entire device (SSH, sudo, and web panel).
ADMIN_USER="Admin"
ADMIN_PASS="${PIDIAG_USER_PASS:-PiDiagOS}"
WIFI_SSID="${PIDIAG_WIFI_SSID:-PiDiagOS}"
WIFI_PASS="${PIDIAG_WIFI_PASS:-PiDiagOS}"
HOSTNAME="${PIDIAG_HOSTNAME:-pidiag}"
ENABLE_SSH="${PIDIAG_SSH:-1}"
# pi-gen service account: required during the build and locked after installation.
BASE_USER="diag"

# pi-gen's arm64 branch moved to trixie, so pin the bookworm-arm64 tag
# for reproducible builds matching RELEASE below.
PIGEN_REPO="${PIDIAG_PIGEN_REPO:-https://github.com/RPi-Distro/pi-gen.git}"
PIGEN_REF="${PIDIAG_PIGEN_REF:-2026-10-06-raspios-bookworm-arm64}"
# debootstrap mirror URL: pi-gen hardcodes http://, which fails where port 80
# is blocked.
DEBIAN_MIRROR="${PIDIAG_DEBIAN_MIRROR:-https://deb.debian.org/debian/}"

die() { echo "[PiDiagOS] $*" >&2; exit 1; }

# Pass the password to chpasswd via a file so special characters do not break the shell
if [ -z "${ADMIN_PASS}" ] || [ -z "${WIFI_PASS}" ]; then
    die "PIDIAG_USER_PASS and PIDIAG_WIFI_PASS must not be empty"
fi
if [ "${#WIFI_PASS}" -lt 8 ] || [ "${#WIFI_PASS}" -gt 63 ]; then
    die "PIDIAG_WIFI_PASS must be 8–63 characters long (WPA2-PSK)"
fi

if ! command -v git >/dev/null; then
    die "git is required"
fi

case "${BUILD_MODE}" in
    docker)
        if ! command -v docker >/dev/null; then
            die "docker is required (see PIDIAG_BUILD_MODE=native)"
        fi
        ;;
    native)
        if [ "$(id -u)" -ne 0 ]; then
            die "A native pi-gen build requires root"
        fi
        missing=""
        for tool in quilt parted realpath qemu-arm-static debootstrap zerofree zip \
                    mkdosfs mke2fs capsh bsdtar grep rsync xz curl xxd file git lsmod \
                    bc gpg pigz arch-test qemu-aarch64-static; do
            command -v "${tool}" >/dev/null 2>&1 || missing="${missing} ${tool}"
        done
        if [ -n "${missing}" ]; then
            echo "[PiDiagOS] Missing tools:${missing}" >&2
            echo "Debian/Ubuntu: apt-get install quilt parted coreutils qemu-user-static binfmt-support debootstrap zerofree zip dosfstools e2fsprogs libcap2-bin libarchive-tools rsync xz-utils curl xxd file git kmod bc gpg pigz arch-test" >&2
            exit 1
        fi
        # arm64 binaries run through qemu-user; binfmt_misc is required
        if ! mountpoint -q /proc/sys/fs/binfmt_misc; then
            mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc
        fi
        # In containers and WSL without systemd, qemu-user-static is not registered automatically
        if ! arch-test arm64 >/dev/null 2>&1; then
            printf '%s\n' ':qemu-aarch64:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:/usr/bin/qemu-aarch64-static:F' \
                > /proc/sys/fs/binfmt_misc/register
            arch-test arm64 >/dev/null 2>&1 || {
                die "arm64 emulation unavailable: check qemu-user-static and binfmt_misc"
            }
        fi
        ;;
    *)
        die "PIDIAG_BUILD_MODE must be docker or native"
        ;;
esac

if ! command -v python3 >/dev/null; then
    die "python3 is required to hash the web panel password"
fi

# Clone pi-gen at the requested version on first run; fetch when the tag changes
if [ ! -d "${WORK_DIR}/.git" ]; then
    mkdir -p "$(dirname "${WORK_DIR}")"
    git clone --depth 1 --branch "${PIGEN_REF}" "${PIGEN_REPO}" "${WORK_DIR}"
else
    git -C "${WORK_DIR}" fetch --depth 1 origin "${PIGEN_REF}"
    git -C "${WORK_DIR}" checkout -q FETCH_HEAD
fi

# Custom stage
rm -rf "${WORK_DIR}/stage-pidiag"
cp -r "${STAGE_SRC}" "${WORK_DIR}/stage-pidiag"

# debootstrap downloads bookworm using the URL in stage0/prerun.sh; HTTP does not work there
sed -i "s|http://deb.debian.org/debian/|${DEBIAN_MIRROR}|" "${WORK_DIR}/stage0/prerun.sh"
# sources.list and raspi.list in stage0 also use http://, and port 80 is blocked
sed -i 's|http://deb.debian.org|https://deb.debian.org|g; s|http://archive.raspberrypi.com|https://archive.raspberrypi.com|g' \
    "${WORK_DIR}/stage0/00-configure-apt/files/sources.list" \
    "${WORK_DIR}/stage0/00-configure-apt/files/raspi.list"

# Files may have passed through Windows: remove CR to avoid breaking bash/python3
# shebangs, then restore executable bits; pi-gen silently skips non-executable *-run.sh files.
find "${WORK_DIR}/stage-pidiag" -type f -exec sed -i 's/\r$//' {} +
find "${WORK_DIR}/stage-pidiag" -type f -name "*-run.sh" -exec chmod 755 {} +
chmod 755 "${WORK_DIR}/stage-pidiag/prerun.sh"
STAGE_FILES="${WORK_DIR}/stage-pidiag/00-install-diag/files"

# The intermediate stage must not export its own image
rm -f "${WORK_DIR}/stage2/EXPORT_IMAGE" "${WORK_DIR}/stage2/EXPORT_NOOBS"

# pi-gen service account password: random and locked after installation
BASE_PASS="$(od -An -N9 -tx1 /dev/urandom | tr -d ' \n' | cut -c1-12)"

# Main account password: plaintext only in .work and only until chroot
printf '%s\n' "${ADMIN_PASS}" > "${STAGE_FILES}/user-password"
chmod 600 "${STAGE_FILES}/user-password"
printf '%s\n' "${ADMIN_USER}" > "${STAGE_FILES}/web-user"
chmod 644 "${STAGE_FILES}/web-user"

# Web panel password hash: scrypt works in both bookworm (3.11) and trixie (3.13),
# unlike the crypt/spwd modules removed in Python 3.13.
python3 - "${ADMIN_PASS}" > "${STAGE_FILES}/web-password" <<'PY'
import hashlib, os, sys
salt = os.urandom(16)
digest = hashlib.scrypt(sys.argv[1].encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
print("scrypt$16384$%s$%s" % (salt.hex(), digest.hex()))
PY
chmod 600 "${STAGE_FILES}/web-password"

# Wi-Fi access point profile: PSK is supplied via the environment
cat > "${STAGE_FILES}/pidiag-ap.nmconnection" <<EOF
[connection]
id=${WIFI_SSID}
uuid=$(cat /proc/sys/kernel/random/uuid)
type=wifi
interface-name=wlan0
autoconnect=true
autoconnect-priority=100

[wifi]
mode=ap
ssid=${WIFI_SSID}
band=bg
channel=6

[wifi-security]
key-mgmt=wpa-psk
psk=${WIFI_PASS}

[ipv4]
method=shared
address1=192.168.50.1/24

[ipv6]
method=ignore
EOF
chmod 600 "${STAGE_FILES}/pidiag-ap.nmconnection"

# Optional public key: the owner can use key-based login alongside password login
rm -f "${STAGE_FILES}/admin_authorized_keys"
if [ -n "${PIDIAG_SSH_PUBKEY:-}" ]; then
    if [ -f "${PIDIAG_SSH_PUBKEY}" ]; then
        SSH_PUBKEY="$(cat "${PIDIAG_SSH_PUBKEY}")"
    else
        SSH_PUBKEY="${PIDIAG_SSH_PUBKEY}"
    fi
    # Keep only key type and body: a comment may break parsing
    SSH_PUBKEY="$(printf '%s\n' "${SSH_PUBKEY}" | awk 'NF >= 2 { print $1, $2; exit }')"
    case "${SSH_PUBKEY}" in
        ssh-*|ecdsa-*|sk-*) ;;
        *) die "PIDIAG_SSH_PUBKEY does not look like an SSH public key: ${SSH_PUBKEY}" ;;
    esac
    printf '%s\n' "${SSH_PUBKEY}" > "${STAGE_FILES}/admin_authorized_keys"
    chmod 644 "${STAGE_FILES}/admin_authorized_keys"
fi

rm -f "${STAGE_FILES}/ssh-enabled"
if [ "${ENABLE_SSH}" = "0" ]; then
    SSH_CONFIG="ENABLE_SSH=0
PUBKEY_ONLY_SSH=0"
    echo "[PiDiagOS] PIDIAG_SSH=0: SSH is disabled." >&2
else
    : > "${STAGE_FILES}/ssh-enabled"
    # Password login is enabled; a key is not required, but is used if provided
    SSH_CONFIG="ENABLE_SSH=1
PUBKEY_ONLY_SSH=0"
fi

cat > "${WORK_DIR}/config" <<EOF
IMG_NAME="PiDiagOS"
RELEASE="bookworm"
DEPLOY_COMPRESSION="xz"
ARCHIVE_FILENAME="PiDiagOS"
TARGET_HOSTNAME="${HOSTNAME}"
FIRST_USER_NAME="${BASE_USER}"
FIRST_USER_PASS="${BASE_PASS}"
STAGE_LIST="stage0 stage1 stage2 stage-pidiag"
${SSH_CONFIG}
EOF

echo "[PiDiagOS] pi-gen: ${PIGEN_REF}"
echo "[PiDiagOS] Build mode: ${BUILD_MODE}"
echo "[PiDiagOS] Login: ${ADMIN_USER} (password set at build time via PIDIAG_USER_PASS)"
echo "[PiDiagOS] Wi-Fi access point: ${WIFI_SSID}, address 192.168.50.1"
if [ "${ADMIN_PASS}" = "PiDiagOS" ]; then
    echo "[PiDiagOS] WARNING: using the default password. Set PIDIAG_USER_PASS" >&2
fi

cd "${WORK_DIR}"
if [ "${BUILD_MODE}" = "docker" ]; then
    ./build-docker.sh
else
    ./build.sh
fi

mkdir -p "${DEPLOY_DIR}"
cp -f "${WORK_DIR}/deploy/PiDiagOS.img.xz" "${DEPLOY_DIR}/"
cd "${DEPLOY_DIR}"
sha256sum PiDiagOS.img.xz | tee PiDiagOS.img.xz.sha256
echo "[PiDiagOS] Done: ${DEPLOY_DIR}/PiDiagOS.img.xz"
