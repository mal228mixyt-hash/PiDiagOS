# Contributing

Thank you for your interest in contributing. These brief guidelines help us review
changes quickly.

## Contributions Welcome

- reports from specific boards (model, revision, power supply);
- fixes to `pinctrl`, `vcgencmd`, and board revision parsing;
- new peripheral checks that do not require external loopback wires;
- web panel improvements without external dependencies;
- documentation translations.

## Process

1. Open an issue describing the problem or proposal.
2. Fork the repository and create a branch such as `fix/short-name` or `feat/short-name`.
3. Keep changes minimal and consistent with the surrounding code.
4. Run these checks locally:
   ```bash
   python -m py_compile image/stage-pidiag/00-install-diag/files/*.py
   bash -n build.sh image/stage-pidiag/00-install-diag/01-run.sh
   ```
5. Open a pull request against `main`, describing what changed, why, and how it was tested.

## Code Requirements

- Python 3.11+ (bookworm), no external packages: use the standard library only.
- Shell scripts must use POSIX-compatible bash and `set -e` in executable scripts.
- Do not include secrets in the repository; pass passwords through environment variables.
- Files included in the image must not contain CRLF (the build cleans them, but LF is preferred).
- Write comments in English and use them only where the code is not self-explanatory.

## Commit Message Style

```
Area: short description

Why this is needed and what changed.
```

Areas: `runner`, `web`, `ap`, `build`, `docs`, `ci`.

## Hardware Testing

For changes to diagnostics, include the board model, revision, image version,
and result (`PASS`/`FAIL`) in the pull request. Changes to the diagnostic engine
cannot be accepted without this information because `vcgencmd` behaves differently
across SoCs.
