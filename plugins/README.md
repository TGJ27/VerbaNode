# VerbaNode External Plugins

Each subfolder is one trusted local Python plugin. VerbaNode scans this folder at startup and when **Reload external plugins** is pressed.

Required files:

```text
plugins/my_plugin/
├── plugin.json
├── plugin.py
└── README.md        # optional
```

External plugins execute inside the VerbaNode Core Python process. Loader and runtime exceptions are isolated and reported in the Plugin Manager, but this is **not a security sandbox**. Only install code you trust.

See `docs/EXTERNAL_PLUGINS.md` and `plugins/example_echo/` for the supported SDK v1 contract.
