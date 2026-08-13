# VerbaNode Windows Application and Online Installer

VerbaNode supports two parallel workflows: normal source development and a packaged Windows application. Packaging is intentionally additive; source development uses the single root `run.bat` entry point.

## Source development

Use:

```bat
run.bat
```

Source mode keeps repository-local development data paths. `run.bat` exports the repository root for Python imports, activates the `verbanode` Conda environment, and starts `launcher.py`, which owns HTTPS certificate creation/refresh.

## Frozen Windows application

`build_windows.bat` creates an onedir PyInstaller application:

```text
dist\
└── VerbaNode\
    ├── VerbaNode.exe
    └── _internal\
```

The native launcher:

- starts and supervises the HTTPS backend;
- reports VerbaNode Core, Audio Engine, AI Engine, and Ollama health;
- discovers usable localhost/LAN/Wi-Fi HTTPS dashboard addresses;
- exposes dashboard PIN Show / Hide / Copy actions;
- provides dashboard launch, restart, minimize, and graceful Exit controls;
- uses the packaged VerbaNode branding and a fixed adaptive utility-window layout.

The application uses **onedir** instead of PyInstaller onefile because VerbaNode includes multiprocessing, PyTorch/FunASR, native audio libraries, model runtimes, and UI resources. Onedir provides clearer native-library loading, faster repeat startup, and easier diagnostics.

## Persistent installed data

Program binaries are installed separately from writable user state.

```text
C:\Program Files\VerbaNode\
    VerbaNode.exe
    _internal\
```

Mutable installed state lives under:

```text
%LOCALAPPDATA%\VerbaNode\
```

This includes application-managed configuration, databases, certificates, external plugins, diagnostics, backups, logs, runtime audio, and VerbaNode-managed model assets.

External caches continue to use their normal user locations where applicable:

```text
%USERPROFILE%\.cache\whisper\
%USERPROFILE%\.cache\modelscope\
%USERPROFILE%\.ollama\
```

Upgrades are designed to replace Program Files binaries without deleting agents, scripts, Information, settings, plugins, databases, certificates, or downloaded model caches.

## Reproducible build environment

Starting with v0.7.7, `build_windows.bat` uses a separate Conda environment named:

```text
verbanode-build
```

This keeps packaging changes away from the normal `verbanode` development environment. Packaging-tool versions are pinned in:

```text
packaging\requirements-packaging.txt
```

The build environment name can be overridden with `VERBANODE_CONDA_ENV` when needed.

The application version is defined in:

```text
app\version.py
```

and the build scripts derive Windows build/installer version metadata from that source.

## Build the application

From the repository root:

```bat
build_windows.bat
```

PyInstaller is platform-specific, so the Windows executable should be built on Windows.

## Build the online installer

After the application build succeeds:

```bat
build_installer.bat
```

The installer is generated under:

```text
dist-installer\VerbaNode-Setup-<version>.exe
```

The Inno Setup wizard supports application installation/upgrades plus optional preparation of configured AI components. Existing SenseVoice, Whisper, Kokoro, Ollama, and Ollama model installations are detected and reused instead of blindly downloading them again. Existing VerbaNode installations default to an application-only update path unless the user chooses to review/add AI components.

## Database upgrades

Installer-triggered setup backs up the current database before migration. v0.7.7 adds a numbered `schema_version` migration foundation under `app/migrations/` so future schema changes can be ordered and applied without resetting user data. Legacy compatibility migrations remain supported.

## Branding

Windows branding assets live under:

```text
packaging\assets\
├── VerbaNode.ico
└── VerbaNode.png
```

The ICO is used for the application/installer/shortcuts, while the PNG is bundled for launcher UI branding.
