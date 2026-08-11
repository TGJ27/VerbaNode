# Windows packaging

This directory contains build-time files only.

- `VerbaNode.spec` — PyInstaller onedir application definition.
- `VerbaNode.iss` — Inno Setup online-installer definition.
- `requirements-packaging.txt` — packaging-only Python dependencies.
- `assets/VerbaNode.ico` and `assets/VerbaNode.png` — application/installer branding.

Build from the repository root:

```bat
build_windows.bat
build_installer.bat
```

Detailed packaging notes are in `docs/packaging/`.
