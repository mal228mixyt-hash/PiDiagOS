#!/bin/bash -e
# Copy the previous stage's rootfs, as required by pi-gen
# for custom stages.
if [ ! -d "${ROOTFS_DIR}" ]; then
    copy_previous
fi
