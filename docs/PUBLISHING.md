# Publishing on GitHub

A step-by-step guide from an empty folder to a release with the image. Run all
commands from the `PiDiagOS-release` directory.

## 0. Prepare

```bash
git init -b main
git add .
git status          # make sure the image in deploy/ is NOT listed
```

The image (`deploy/*.img.xz`) is intentionally excluded via `.gitignore`:

- GitHub rejects repository files larger than 100 MB;
- Releases allow up to 2 GB per file and are the right place for the image.

If you want to version large files in git, use Git LFS
(`git lfs track "deploy/*.img.xz"`), though this is unnecessary for OS images.

Before your first commit, add your name to `LICENSE` (currently
“PiDiagOS contributors”) and set your donation link in `.github/FUNDING.yml`.

## 1. First Commit

```bash
git add .
git commit -m "PiDiagOS 1.0.0: diagnostic OS for Raspberry Pi 3/4/5"
```

Make sure the batch file retains CRLF:

```bash
git ls-files --eol check-wifi.bat
# expected: i/crlf  w/crlf
```

## 2. Create the Repository

### Using GitHub CLI

```bash
gh auth login
gh repo create PiDiagOS --public --source=. --remote=origin --push \
    --description "Diagnostic OS for Raspberry Pi 3/4/5: RAM, power, CPU, GPIO tests and browser reports"
```

### Using the website

1. Go to <https://github.com/new> → name it `PiDiagOS`, select Public, and do **not**
   initialize with README/LICENSE/.gitignore (they are already in the project).
2. Then run:

```bash
git remote add origin git@github.com:<username>/PiDiagOS.git
git push -u origin main
```

If you have not configured an SSH key, use the HTTPS URL; create a token under
Settings → Developer settings → Personal access tokens.

## 3. Configure the Repository

- **About** (right side of the home page): description, website link (if available),
  topics: `raspberry-pi`, `diagnostics`, `hardware-testing`, `linux`,
  `raspberrypi`, `pi-gen`, `python`.
- **Settings → General**: enable Issues and Discussions.
- **Settings → Code security**: enable Dependabot alerts (free).
- GitHub detects the license automatically from `LICENSE` (MIT).
- The **Actions** tab runs `.github/workflows/ci.yml` on the first push to check
  Python and shell script syntax.

## 4. Release the Image

```bash
git tag -a v1.0.0 -m "PiDiagOS 1.0.0"
git push origin v1.0.0

gh release create v1.0.0 \
    deploy/PiDiagOS.img.xz \
    deploy/PiDiagOS.img.xz.sha256 \
    --title "PiDiagOS 1.0.0" \
    --notes-file CHANGELOG.md
```

On the website: **Releases → Draft a new release** → tag `v1.0.0` → attach
`PiDiagOS.img.xz` and `.sha256` → add release notes → Publish.

Release guidelines:

- the tag and version must match (`v1.0.0` ↔ 1.0.0 in `CHANGELOG.md`);
- describe what changed and which boards were tested;
- provide the checksum as a separate file beside the image;
- do not replace an image in an existing release; create a new tag instead.

## 5. Donations

`.github/FUNDING.yml` contains a template. Fill in one of these options:

```yaml
github: <your-username>          # GitHub Sponsors
custom: ["https://boosty.to/<your-profile>"]
```

A “Sponsor” link will appear in the repository header. GitHub Sponsors requires
an application and a bank account in a supported country; Boosty and DonationAlerts
are available in Russia.

## 6. Post-Publication Checklist

- README renders correctly and links under `docs/` work;
- the image is in Releases and its size and SHA-256 match the local files;
- CI is green;
- `check-wifi.bat` downloads and runs (Windows may show a SmartScreen warning,
  which is normal for an unsigned `.bat` file);
- Issues are enabled and templates load.

## 7. Update the Version

```bash
# make code changes
git add -A
git commit -m "Fix: ..."
git tag -a v1.0.1 -m "PiDiagOS 1.0.1"
git push origin main --tags
gh release create v1.0.1 deploy/PiDiagOS.img.xz deploy/PiDiagOS.img.xz.sha256 \
    --title "PiDiagOS 1.0.1" --notes "What changed..."
```
