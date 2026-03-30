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

## Troubleshooting

### "No bundled Python runtime in app"
Run `bash installer/build-python-bundle.sh` first.

### "No signing identity found"
Install the Developer ID certificate or set `NEXE_SIGNING_IDENTITY` env var.

### Swift compilation fails
Ensure Xcode CLT is installed: `xcode-select --install`

### Notarization fails
Check Keychain credentials: `xcrun notarytool history --keychain-profile "nexe"`
