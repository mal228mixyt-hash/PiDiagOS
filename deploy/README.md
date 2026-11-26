# Build Artifacts

After running `./build.sh`, this directory contains:

- `PiDiagOS.img.xz` — ready-to-use image for Raspberry Pi Imager;
- `PiDiagOS.img.xz.sha256` — checksum file.

These files are **not committed** (see `.gitignore`); they are published as
GitHub Release assets.

Users should download the image from:

```
https://github.com/<owner>/PiDiagOS/releases/latest/download/PiDiagOS.img.xz
```

Update the Raspberry Pi Imager manifest with:

```bash
python3 imager/make_manifest.py deploy/PiDiagOS.img.xz \
    --url https://github.com/<owner>/PiDiagOS/releases/latest/download/PiDiagOS.img.xz
```
