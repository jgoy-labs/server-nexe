# Contributing

Thanks for helping improve Nexe.

**Workflow**
1. Fork and create a feature branch.
2. Keep changes focused and small.
3. Open a PR with a clear description and test notes.

**Code Style**
- Follow existing project style and patterns.
- Avoid introducing new hardcoded user-facing strings.
- If you use formatters locally, prefer `black` and `ruff` conventions.

**i18n Guidelines**
- Wrap user-facing strings with `t()` or `t_modular()`.
- Add keys to `messages_*.json` for all supported languages.
- Run `python3 scripts/i18n_lint.py` and `python3 scripts/lint_i18n.py`.

**Testing**
- Add or update tests for new behavior.
- Example: `pytest core/contracts/tests/ tests/integration/ -v`

**Security**
- Avoid weakening security defaults.
- If adding new public endpoints, review CSRF exemptions in `personality/server.toml`.
