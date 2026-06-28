"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/_shared/cli_scaffold.py
Description: Shared Typer CLI scaffold for plugin modules (MC-096).
             build_module_cli() returns a Typer app with the standard
             info/health/test/workflow commands; each caller passes its own
             help text, location, workflow message and module hooks.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Any, Callable, Dict

import typer


def build_module_cli(
    *,
    help_text: str,
    location: str,
    workflow_msg: str,
    get_module_instance: Callable[[], Any],
    get_health: Callable[[], Dict[str, Any]],
) -> typer.Typer:
    """Build the standard module CLI (info/health/test/workflow).

    Args:
        help_text:           Typer app help text.
        location:            __file__ of the calling __main__.py (test dir resolution).
        workflow_msg:        Message printed by the ``workflow`` command.
        get_module_instance: Returns the module singleton (caller's .manifest).
        get_health:          Returns the module health dict (caller's .health).
    """
    app = typer.Typer(help=help_text)

    @app.command()
    def info():
        """Show module information."""
        module = get_module_instance()
        data = module.get_info()
        for k, v in data.items():
            typer.echo(f"{k}: {v}")

    @app.command()
    def health():
        """Show health status."""
        result = get_health()
        typer.echo(f"Status: {result.get('status', 'unknown')}")

    @app.command()
    def test():
        """Run module tests."""
        import subprocess
        import sys
        from pathlib import Path
        module_dir = Path(location).parent
        test_dir = module_dir / "tests"
        result = subprocess.run(  # nosec B603: sys.executable + literal pytest invocation; test_dir is location-derived
            [sys.executable, "-m", "pytest", str(test_dir), "-v", "--tb=short"],
            cwd=str(module_dir.parent.parent)
        )
        raise typer.Exit(code=result.returncode)

    @app.command()
    def workflow():
        """Workflow nodes info."""
        typer.echo(workflow_msg)

    return app
