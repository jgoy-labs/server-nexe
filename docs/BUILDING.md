# Building Install Nexe.dmg

How to build the macOS installer DMG from source.

## Prerequisites (one-time setup)

- macOS 13+ (Ventura or later)
- Xcode Command Line Tools: `xcode-select --install`
- Signing certificate: "Developer ID Application: Jordi Goy (NHG3THR2AF)"
- Notarization credentials in Keychain (profile "nexe")

## Step 1: Build Python bundle (one-time, ~2 min)

```bash
bash installer/build-python-bundle.sh
```

Creates `InstallNexe.app/Contents/Resources/python/` (~49 MB).
This is **gitignored** — it's a build artifact, not source code. Only needs to run once unless Python version changes.

The script downloads [python-build-standalone](https://github.com/indygreg/python-build-standalone) (cpython 3.12.8), trims unnecessary modules, fixes dylib paths, and codesigns the binaries.

## Step 2: Build DMG

```bash
# Quick test build (unsigned for notarization)
bash installer/build_dmg.sh --no-notarize

# Full release build (signed + notarized)
bash installer/build_dmg.sh
```

Output: `Install Nexe.dmg` at the project root (~20 MB).

### What `build_dmg.sh` does

1. Compiles Swift wizard (`installer/swift-wizard/`)
2. Creates macOS app bundle with Info.plist
3. Exports model catalog (JSON from Python)
4. Packages payload (`core/`, `plugins/`, `installer/`, etc.)
5. Signs all embedded Python binaries with Developer ID
6. Signs app bundle with entitlements
7. Creates DMG with background image
8. Signs and notarizes DMG (unless `--no-notarize`)

## Bumping version

**Single source of truth:** `pyproject.toml` `[project].version`.

Tot el que necessita la versió del projecte s'actualitza des d'aquí:

```bash
# 1. Edita pyproject.toml — canvia [project].version: "0.9.7" → "0.9.8"
# 2. Sincronitza els Info.plist dels bundles macOS:
python3 -m installer.sync_plist_versions
# 3. Verifica que tot quadra:
pytest core/tests/test_version.py core/tests/test_plist_versions.py
```

### Mapa de propagació

| Destinatari | Com rep la versió | Cal bump manual? |
|-------------|-------------------|------------------|
| Codi Python (`from core.version import __version__`) | `core/version.py` llegeix `pyproject.toml` en runtime | ❌ automàtic |
| `Nexe.app/Contents/Info.plist` | `installer/sync_plist_versions.py` | ❌ automàtic (sync) |
| `installer/NexeTray.app/Contents/Info.plist` | `installer/sync_plist_versions.py` | ❌ automàtic (sync) |
| `InstallNexe.app` / `Install Nexe.app` / `swift-wizard/Resources/Info.plist` | Versió pròpia de l'**installer** (no de server-nexe) | ✅ manual si bumps l'installer |

El `build_dmg.sh` executa `sync_plist_versions.py` abans de bundlejar, així que una release de DMG mai no porta versions stale als bundles sincronitzats.

### Afegir un nou bundle a sincronitzar

Afegeix la ruta a `SYNCED_PLISTS` a `installer/sync_plist_versions.py`. El test `test_synced_plists_match_pyproject` hi passarà automàticament en cada CI run.

### CHANGELOG

Cada bump ha d'actualitzar `CHANGELOG.md` amb una secció nova `[X.Y.Z] — YYYY-MM-DD`.

---

## Step 3: Publish release

```bash
gh release create vX.Y.Z "Install Nexe.dmg" \
  --title "vX.Y.Z" \
  --notes "Release notes here"
```

## What's gitignored (build artifacts)

These files are created during the build but **never committed**:

| Artifact | Size | Purpose |
|----------|------|---------|
| `InstallNexe.app/` | ~70 MB | App bundle with Python + Swift wizard |
| `Install Nexe.dmg` | ~20 MB | Final distributable DMG |
| `installer/swift-wizard/.build/` | ~50 MB | Swift compilation cache |

## Build flow

```
installer/build-python-bundle.sh    (one-time)
         |
         v
InstallNexe.app/Contents/Resources/python/   (gitignored)
         |
         v
installer/build_dmg.sh              (each release)
         |
         v
Install Nexe.dmg                    (gitignored)
         |
         v
gh release create                   (GitHub Releases)
```

## Post-install layout

After a clean install from the DMG, `/Applications/` contains:

```
/Applications/
├── Nexe.app                      ← visible launcher (copy)
└── server-nexe/                  ← install dir (install_path)
    ├── Nexe.app                  ← same launcher, bundled inside
    ├── installer/NexeTray.app
    ├── core/, plugins/, venv/, storage/
    └── nexe                      ← shell launcher
```

### Why two copies of `Nexe.app`

This is **intentional duplication**, not a bug. `install_headless.py`
(see the `DESIGN NOTE` block around the `/Applications/Nexe.app` copy)
maintains both:

- `<install_path>/Nexe.app` — shipped with the install dir, keeps
  everything self-contained under `/Applications/server-nexe/`.
- `/Applications/Nexe.app` — a physical copy placed at the Applications
  root so the user sees a normal "Nexe" icon without digging into a
  subfolder. Dock icons, Login Items, and Launch Services anchor to
  this stable path.

Both are plain copies (not hardlink / symlink). The tray uninstaller
(`installer/tray_uninstaller.py`) removes both locations, so a clean
uninstall leaves no orphans. Fresh-install flow via the DMG always
rewrites both in lockstep.

Known caveat: if someone manually updates one bundle in isolation (e.g.
patching files in `<install_path>/Nexe.app/` without touching
`/Applications/Nexe.app/`), the two will drift and Launch Services may
pick the stale copy. Treat a full reinstall from DMG (or the wizard
update flow) as the only supported update path for these bundles.

## Troubleshooting

### "No bundled Python runtime in app"
Run `bash installer/build-python-bundle.sh` first.

### "No signing identity found"
Install the Developer ID certificate or set `NEXE_SIGNING_IDENTITY` env var.

### Swift compilation fails
Ensure Xcode CLT is installed: `xcode-select --install`

### Notarization fails
Check Keychain credentials: `xcrun notarytool history --keychain-profile "nexe"`
