# Contributing to Nexe

Thank you for your interest in contributing to Nexe! We welcome contributions from everyone.

## Getting Started

1.  **Fork the repository** on GitHub.
2.  **Clone your fork** locally:
    ```bash
    git clone https://github.com/StartYourFork/nexe.git
    cd nexe
    ```
3.  **Install dependencies**:
    ```bash
    ./setup.sh
    # or manually:
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

## Development Workflow

1.  Create a new branch for your feature or bugfix:
    ```bash
    git checkout -b feature/my-new-feature
    ```
2.  Make your changes.
3.  **Test your changes**:
    - Run the server: `./nexe go`
    - Verify functionality in the Web UI or via API.
    - Check logs: `./nexe logs`
4.  **Linting & Formatting**:
    - We use `ruff` for linting and formatting (if configured).
    - Ensure all user-facing strings are wrapped in `t()` for i18n support.
    - Run `python3 scripts/lint_i18n.py` (if available) to check for untranslated strings.

## Code Style

-   Follow PEP 8 guidelines.
-   Use type hints wherever possible.
-   Write clear, concise comments.
-   Keep functions small and focused.

## I18n (Internationalization)

Nexe supports multiple languages (CA/ES/EN).
-   **Do not hardcode strings.**
-   Use `t("key.subkey", "Default English text")`.
-   Add translations to `personality/i18n/`.

## Pull Requests

1.  Push your branch to your fork.
2.  Open a Pull Request against the `main` branch.
3.  Describe your changes clearly in the PR description.
4.  Link to any related issues.

## Reporting Bugs

Please open an issue on GitHub if you encounter any bugs. Include:
-   Steps to reproduce.
-   Expected behavior.
-   Actual behavior.
-   Logs/Error messages.
-   System information (OS, Python version).

Thank you for contributing!
