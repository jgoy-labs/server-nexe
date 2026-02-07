# Template Module

Copy this folder to create a new plugin module.

Steps:
1. Rename the folder and update `manifest.toml` (name, version, description).
2. Update `module.py` and export a `create_module()` factory.
3. Add your module name to `personality/server.toml` under `[plugins.modules].enabled`.

See `HOWTO_CREATE_PLUGIN.md` for details.
