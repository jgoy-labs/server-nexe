# Contributing to nexe-app

Thank you for your interest in contributing!

## Before you start

- Read [README.md](README.md) for project overview.
- Read [TEMPLATE.md](TEMPLATE.md) if you want to fork this as a base for your own app.
- Check existing [ADRs](docs/adr/README.md) to understand architectural decisions.

## Development setup

```bash
# Prerequisites
brew install rust node pnpm   # macOS
rustup update stable

# Install Tauri CLI
cargo install tauri-cli --version "^2.10"

# Install JS deps
pnpm install

# Run in dev mode
pnpm tauri dev
```

## Running tests

```bash
# Rust unit tests
cd src-tauri && cargo test --locked

# JS/Vitest tests
pnpm test

# Lints
cd src-tauri && cargo clippy --locked -- -D warnings
pnpm run build  # also catches TS/JS errors
```

## Making changes

1. Fork and create a branch: `git checkout -b feat/your-feature`
2. Make changes. Keep scope small and focused.
3. Run all tests (both Rust and JS) — they must all pass.
4. If you change architecture: add or update an ADR in `docs/adr/`.
5. Update `CHANGELOG.md` under `[Unreleased]`.
6. Open a PR with a clear description.

## Plugin development

Plugins live under `plugins-dev/<name>/ui/`. Each plugin needs:
- `manifest.toml` with `[plugin]` and `[integrity]` sections
- `ui/index.html` as entry point

After editing a plugin, recompute its hash:
```bash
./scripts/compute-plugin-hash.sh plugins-dev/<name>
```

Then update `manifest.toml` with the new `sha256` value.

## Security

Please report security issues privately. See [SECURITY.md](SECURITY.md) for details.

## Code style

- Rust: `rustfmt` (enforced by CI) + `clippy --deny warnings`
- JS: no linter enforced yet (F080 roadmap)
- Comments in Catalan or English, technical terms in English

## License

By contributing, you agree your contributions are licensed under [Apache-2.0](LICENSE).
