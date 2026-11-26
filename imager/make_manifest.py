#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Populate the Raspberry Pi Imager JSON manifest with actual image sizes and SHA256 values.

Imager validates extract_size/extract_sha256 (the unpacked image) and
image_download_size/image_download_sha256 (the downloaded file).

Usage:
    python3 imager/make_manifest.py deploy/PiDiagOS.img.xz \
        --url https://server.local/images/PiDiagOS.img.xz

Without --out, the manifest is overwritten in place (imager/pidiagos_repo.json).
"""

import argparse
import gzip
import hashlib
import json
import lzma
import os
import sys
from datetime import date

CHUNK = 1024 * 1024


def open_stream(path):
    if path.endswith(".xz"):
        return lzma.open(path, "rb")
    if path.endswith(".gz"):
        return gzip.open(path, "rb")
    if path.endswith(".img"):
        return open(path, "rb")
    raise ValueError("Supported formats are .img, .img.xz, and .img.gz: %s" % path)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_image(path):
    """Compute the unpacked image size and SHA256 in a single pass."""
    digest = hashlib.sha256()
    size = 0
    with open_stream(path) as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("image", help="deploy/PiDiagOS.img.xz")
    parser.add_argument("--url", help="Image URL for the manifest")
    parser.add_argument("--template", help="Manifest template (defaults to the file next to this script)")
    parser.add_argument("--out", help="Output file path")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    template = args.template or os.path.join(script_dir, "pidiagos_repo.json")
    out = args.out or template

    compressed_size = os.path.getsize(args.image)
    extract_size, extract_sha = scan_image(args.image)
    download_sha = sha256_of(args.image)

    with open(template, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    entry = manifest["os_list"][0]
    if args.url:
        entry["url"] = args.url
    entry["extract_size"] = extract_size
    entry["extract_sha256"] = extract_sha
    entry["image_download_size"] = compressed_size
    entry["image_download_sha256"] = download_sha
    entry["release_date"] = date.today().isoformat()

    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("image            : %s" % args.image)
    print("download size    : %d bytes" % compressed_size)
    print("download sha256  : %s" % download_sha)
    print("extract size     : %d bytes" % extract_size)
    print("extract sha256   : %s" % extract_sha)
    print("manifest         : %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
