# How to Create a Plugin

This is a minimal, OSS-friendly guide for adding a new module under `plugins/`.

## 1. Create the folder
```
plugins/my_module/
```

## 2. Add a minimal `manifest.toml`
```toml
manifest_version = "1.0"

[module]
name = "my_module"
version = "0.1.0"
type = "module"
description = "My module description"
enabled = true
auto_start = false
priority = 10
author = "Your Name"

[capabilities]
has_api = false
has_ui = false
has_cli = false
has_tests = false
```

## 3. Add a minimal `module.py`
```python
class MyModule:
    def __init__(self):
        self.name = "my_module"
        self.version = "0.1.0"


def create_module():
    return MyModule()
```

## 4. (Optional) Add API/UI/CLI
- If you enable `has_api = true`, add an API router and set the `[api]` section in the manifest.
- If you enable `has_ui = true`, add `ui/index.html` and fill the `[ui]` section.
- If you enable `has_cli = true`, add a CLI entry point and fill the `[cli]` section.

See `README_PLUGINS.md` for the full UnifiedManifest schema.

## 5. Enable the module
Add it to `personality/server.toml`:
```toml
[plugins.modules]
enabled = ["my_module", ...]
```

## 6. Validate (optional)
```bash
python3 -c "from core.contracts import load_manifest_from_toml; print(load_manifest_from_toml('plugins/my_module/manifest.toml').module.name)"
```
