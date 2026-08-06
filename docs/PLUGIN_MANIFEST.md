# Plugin manifest reference

External plugins use `plugin.json` and SDK major version `1`.

## Required fields

- `id`: lowercase letters, numbers, and underscores; must not collide with a built-in or another external plugin.
- `name`: 1–100 characters.
- `version`: semantic version such as `1.0.0` or `1.2.0-beta.1`.
- `author`: 1–120 characters.
- `description`: 1–1000 characters.
- `entry`: a non-symlink `.py` file inside the plugin folder.
- `sdk_version`: major version `1`.

Optional fields are `category`, `priority`, `permissions`, `homepage`, `license`, and extension keys beginning with `x_`.

## Supported permission labels

`internet`, `network`, `filesystem_read`, `filesystem_write`, `camera`, `microphone`, `display`, `robot`, `serial`, `mqtt`, and `shell`.

Permission labels are validated and displayed to the operator. They are not operating-system access controls.

## Package limits

Defaults can be changed through `.env`:

- Manifest: 65,536 bytes.
- Entry module: 2,097,152 bytes.
- Folder names: letters, numbers, dots, underscores, and hyphens.
- Symbolic-link folders, manifests, and entry files are rejected.
