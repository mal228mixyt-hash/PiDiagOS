#!/bin/bash -e
# PiDiagOS: install diagnostics, access point, and storage protection.

install -m 755 files/rpi-diag-runner.py "${ROOTFS_DIR}/usr/local/bin/rpi-diag-runner.py"
install -m 755 files/pidiag-web.py "${ROOTFS_DIR}/usr/local/bin/pidiag-web.py"
install -m 755 files/pidiag-ap-check.py "${ROOTFS_DIR}/usr/local/bin/pidiag-ap-check.py"
install -m 755 files/pidiag-bootlog.sh "${ROOTFS_DIR}/usr/local/bin/pidiag-bootlog.sh"
install -m 644 files/rpi-diag.service "${ROOTFS_DIR}/etc/systemd/system/rpi-diag.service"
install -m 644 files/pidiag-web.service "${ROOTFS_DIR}/etc/systemd/system/pidiag-web.service"
install -m 644 files/pidiag-bootlog.service "${ROOTFS_DIR}/etc/systemd/system/pidiag-bootlog.service"
install -m 644 files/pidiag-ap-check.service "${ROOTFS_DIR}/etc/systemd/system/pidiag-ap-check.service"
install -m 644 files/pidiag-ap-check.timer "${ROOTFS_DIR}/etc/systemd/system/pidiag-ap-check.timer"

install -d -m 755 "${ROOTFS_DIR}/etc/pidiag"

# The web panel password hash and username are generated at build time (build.sh).
if [ -f files/web-password ]; then
    install -m 600 files/web-password "${ROOTFS_DIR}/etc/pidiag/web-password"
fi
if [ -f files/web-user ]; then
    install -m 644 files/web-user "${ROOTFS_DIR}/etc/pidiag/web-user"
else
    printf 'Admin\n' > "${ROOTFS_DIR}/etc/pidiag/web-user"
fi
# Password for the user account: applied inside chroot and immediately removed
if [ -f files/user-password ]; then
    install -m 600 files/user-password "${ROOTFS_DIR}/etc/pidiag/user-password"
fi
# Optional SSH public key
if [ -f files/admin_authorized_keys ]; then
    install -m 644 files/admin_authorized_keys "${ROOTFS_DIR}/etc/pidiag/admin_authorized_keys"
fi

# Wi-Fi access point: NetworkManager profile is prepared by build.sh (SSID and PSK)
install -d -m 755 "${ROOTFS_DIR}/etc/NetworkManager/system-connections"
if [ -f files/pidiag-ap.nmconnection ]; then
    install -m 600 files/pidiag-ap.nmconnection \
        "${ROOTFS_DIR}/etc/NetworkManager/system-connections/pidiag-ap.nmconnection"
fi

# SSH: password login enabled, root login disabled. Drop-in is read before sshd_config,
# so these settings take priority. build.sh creates the marker when PIDIAG_SSH=1.
if [ -f files/ssh-enabled ]; then
    install -d -m 755 "${ROOTFS_DIR}/etc/ssh/sshd_config.d"
    cat > "${ROOTFS_DIR}/etc/ssh/sshd_config.d/00-pidiag.conf" <<'EOF'
PasswordAuthentication yes
KbdInteractiveAuthentication no
PermitRootLogin no
MaxAuthTries 4
ClientAliveInterval 300
EOF
fi

# The journal lives in tmpfs (overlayroot), so limit its size; otherwise
# journald can consume the board's 1 GB of RAM.
install -d -m 755 "${ROOTFS_DIR}/etc/systemd/journald.conf.d"
cat > "${ROOTFS_DIR}/etc/systemd/journald.conf.d/00-pidiag.conf" <<'EOF'
[Journal]
Storage=volatile
RuntimeMaxUse=24M
SystemMaxUse=24M
Compress=yes
EOF

# Swap on the SD card is unnecessary: the root filesystem is in tmpfs and the card is read-only
install -d -m 755 "${ROOTFS_DIR}/etc/sysctl.d"
cat > "${ROOTFS_DIR}/etc/sysctl.d/60-pidiag.conf" <<'EOF'
vm.swappiness = 1
vm.dirty_writeback_centisecs = 1500
EOF

# Automatic updates are unnecessary: the image is used for one diagnostic session
cat > "${ROOTFS_DIR}/etc/apt/apt.conf.d/20auto-upgrades" <<'EOF'
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Unattended-Upgrade "0";
EOF

cat > "${ROOTFS_DIR}/etc/motd" <<'EOF'

  PiDiagOS — Raspberry Pi diagnostics
  -----------------------------------
  Panel:    http://<board-address>/      (login: Admin)
  Reports:  /boot/firmware/diag_results/
  Change password: sudo passwd Admin

EOF

# config.txt is appended to, not replaced: it contains arm_64bit=1 and [cm4]/[cm5]
# sections required to boot the 64-bit image on Pi 3/4.
# The marker at the start of the block prevents duplication on rebuild (CONTINUE=1).
CFG="${ROOTFS_DIR}/boot/firmware/config.txt"
if ! grep -q '^# PiDiagOS additions' "${CFG}"; then
    cat files/config.txt >> "${CFG}"
fi

# vc4-kms-v3d is usually already present in the default file; do not add a duplicate
if ! grep -q '^dtoverlay=vc4-kms-v3d' "${CFG}"; then
    printf '\n[all]\ndtoverlay=vc4-kms-v3d\nmax_framebuffers=2\n' >> "${CFG}"
fi

# overlayroot over tmpfs, without recursion: external USB drives remain writable
cat > "${ROOTFS_DIR}/etc/overlayroot.local.conf" <<'EOF'
overlayroot="tmpfs:recurse=0"
EOF

# Add the cmdline.txt parameter only once
CMDLINE="${ROOTFS_DIR}/boot/firmware/cmdline.txt"
if ! grep -q 'overlayroot=' "${CMDLINE}"; then
    sed -i '1s/[[:space:]]*$/ overlayroot=tmpfs:recurse=0/' "${CMDLINE}"
fi

# /boot/firmware is mounted read-only; the runner remounts it read-write while saving reports
FSTAB="${ROOTFS_DIR}/etc/fstab"
if ! grep -Eq '^[^#]+[[:space:]]+/boot/firmware[[:space:]]+[^[:space:]]+[[:space:]]+[^[:space:]]*ro' "${FSTAB}"; then
    sed -i -E 's#^([^#][^[:space:]]*[[:space:]]+/boot/firmware[[:space:]]+[^[:space:]]+[[:space:]]+)([^[:space:]]+)#\1\2,ro#' "${FSTAB}"
fi

on_chroot << 'EOF'
set -e

systemctl enable rpi-diag.service
systemctl enable pidiag-web.service
systemctl enable pidiag-bootlog.service
systemctl enable pidiag-ap-check.timer
systemctl enable NetworkManager.service
if [ -f /etc/ssh/sshd_config.d/00-pidiag.conf ]; then
    systemctl enable ssh.service
else
    systemctl disable ssh.service 2>/dev/null || true
fi
systemctl enable avahi-daemon.service
systemctl set-default multi-user.target

# Operator account. pi-gen creates lowercase usernames only, so
# add Admin separately; adduser --force-badname bypasses Debian's check.
ACCOUNT=Admin
if ! id -u "${ACCOUNT}" >/dev/null 2>&1; then
    if ! adduser --force-badname --disabled-password --gecos "PiDiagOS operator" "${ACCOUNT}"; then
        ACCOUNT=admin
        adduser --disabled-password --gecos "PiDiagOS operator" "${ACCOUNT}"
        echo "[PiDiagOS] Could not create Admin; falling back to admin login" >&2
    fi
fi

# One password for the entire device: SSH, sudo, and web panel
if [ -s /etc/pidiag/user-password ]; then
    PASSWORD="$(cat /etc/pidiag/user-password)"
    printf '%s:%s\n' "${ACCOUNT}" "${PASSWORD}" | chpasswd
    rm -f /etc/pidiag/user-password
fi

for GROUP in adm dialout cdrom audio video plugdev games users sudo input netdev gpio i2c spi render; do
    groupadd -f -r "${GROUP}" 2>/dev/null || true
    adduser "${ACCOUNT}" "${GROUP}" >/dev/null 2>&1 || true
done

# Install the key if it was provided at build time
if [ -s /etc/pidiag/admin_authorized_keys ]; then
    install -d -m 700 -o "${ACCOUNT}" -g "${ACCOUNT}" "/home/${ACCOUNT}/.ssh"
    install -m 600 -o "${ACCOUNT}" -g "${ACCOUNT}" /etc/pidiag/admin_authorized_keys \
        "/home/${ACCOUNT}/.ssh/authorized_keys"
    rm -f /etc/pidiag/admin_authorized_keys
fi

# Passwordless sudo: the default device password is public, and an extra prompt
# only makes keyboard-free operation harder
printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' "${ACCOUNT}" > /etc/sudoers.d/020_pidiag
chmod 440 /etc/sudoers.d/020_pidiag

# pi-gen service account is no longer needed
if id -u diag >/dev/null 2>&1; then
    usermod -L -s /usr/sbin/nologin diag
fi
rm -f /etc/sudoers.d/010_pi-nopasswd

# Build initramfs for both kernels: overlayroot installs hooks only for the kernel
# used to run update-initramfs; otherwise protection would not activate on Pi 5.
for kdir in /lib/modules/*; do
    kver="$(basename "${kdir}")"
    update-initramfs -c -k "${kver}"
    [ -f "/boot/initrd.img-${kver}" ] || continue
    case "${kver}" in
        *2712*) cp -f "/boot/initrd.img-${kver}" /boot/firmware/initramfs_2712 ;;
        *v8*)   cp -f "/boot/initrd.img-${kver}" /boot/firmware/initramfs8 ;;
    esac
done

# The first boot after flashing the image must not launch raspi-config
rm -f /etc/profile.d/raspi-config.sh || true

# Disable background load and unnecessary writers to the SD card
systemctl disable dphys-swapfile.service 2>/dev/null || true
systemctl mask dphys-swapfile.service 2>/dev/null || true
systemctl disable bluetooth.service hciuart.service 2>/dev/null || true
systemctl disable triggerhappy.service ModemManager.service 2>/dev/null || true
systemctl disable apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
systemctl disable man-db.timer e2scrub_all.timer 2>/dev/null || true

# Package cache is not needed in the image
apt-get clean
rm -rf /var/lib/apt/lists/*
EOF
